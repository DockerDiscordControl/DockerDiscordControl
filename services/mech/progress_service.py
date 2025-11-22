#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Progress Service                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
DockerDiscordControl Progress Service (SPOT, Service-First)
- Event Sourcing + Snapshots on filesystem (JSON)
- Integer-only accounting (no floats)

Features:
- 11 levels (1..11), parallel Power & Evolution accumulation from donations
- Dynamic difficulty fixed only at next-level start (bins -> requirement)
- Exact-hit rule: on level-up, Power=1 if evo hits exact threshold, else 0
- Power daily decay (per mech-type configurable)
- Monthly gift (1..3 power) when power==0 (deterministic, idempotent)
- Donation deletion via tombstone + deterministic replay from snapshot checkpoint
- Idempotency keys for donations; optimistic concurrency on snapshots

Data layout:
  config/progress/events.jsonl                # global append-only event log
  config/progress/snapshots/{mech_id}.json    # last consolidated state per mech
  config/progress/config.json                 # service config (bins, requirements, decay)
  config/progress/member_count.json           # cached status-channel member count
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import logging

from services.mech.progress import get_progress_runtime

logger = logging.getLogger('ddc.mech.progress_service')

runtime = get_progress_runtime()

# ---------------------
# Config & Constants
# ---------------------

DEFAULT_CONFIG = {
    "timezone": "Europe/Zurich",
    # 21 bins (1..21). Values are inclusive lower bounds of concurrent users
    "difficulty_bins": [
        0, 25, 50, 100, 150, 200, 300, 400, 500, 750,
        1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 7500, 10000
    ],
    # HYBRID COST SYSTEM: Base costs per level (in cents) - these are MINIMUM costs
    # Even a 1-person channel must pay these base costs
    "level_base_costs": {
        "1": 1000,   # Level 1→2: $10.00 base
        "2": 1500,   # Level 2→3: $15.00 base
        "3": 2000,   # Level 3→4: $20.00 base
        "4": 2500,   # Level 4→5: $25.00 base
        "5": 3000,   # Level 5→6: $30.00 base
        "6": 3500,   # Level 6→7: $35.00 base
        "7": 4000,   # Level 7→8: $40.00 base
        "8": 4500,   # Level 8→9: $45.00 base
        "9": 5000,   # Level 9→10: $50.00 base
        "10": 10000  # Level 10→11: $100.00 base
    },
    # Dynamic costs per bin (in cents) - ADDED to base cost
    # These scale with community size
    "bin_to_dynamic_cost": {
        "1": 400,    # Bin 1: +$4.00
        "2": 900,    # Bin 2: +$9.00
        "3": 1800,   # Bin 3: +$18.00
        "4": 3100,   # Bin 4: +$31.00
        "5": 4900,   # Bin 5: +$49.00
        "6": 7200,   # Bin 6: +$72.00
        "7": 9900,   # Bin 7: +$99.00
        "8": 13000,  # Bin 8: +$130.00
        "9": 16600,  # Bin 9: +$166.00
        "10": 20700, # Bin 10: +$207.00
        "11": 25300, # Bin 11: +$253.00
        "12": 30400, # Bin 12: +$304.00
        "13": 36000, # Bin 13: +$360.00
        "14": 42100, # Bin 14: +$421.00
        "15": 48700, # Bin 15: +$487.00
        "16": 55800, # Bin 16: +$558.00
        "17": 63400, # Bin 17: +$634.00
        "18": 71500, # Bin 18: +$715.00
        "19": 80100, # Bin 19: +$801.00
        "20": 89200, # Bin 20: +$892.00
        "21": 99000  # Bin 21: +$990.00
    },
    # decay per day by mech_type (or default) - in cents
    "mech_power_decay_per_day": {
        "default": 100  # $1 per day
    },
}

runtime.configure_defaults(DEFAULT_CONFIG)

PATHS = runtime.paths
DATA_DIR = PATHS.data_dir
EVENT_LOG = PATHS.event_log
SNAPSHOT_DIR = PATHS.snapshot_dir
CONFIG_FILE = PATHS.config_file
SEQ_FILE = PATHS.seq_file
MEMBER_COUNT_FILE = PATHS.member_count_file
LOCK = runtime.lock


def load_config(refresh: bool = False) -> Dict[str, Any]:
    """Load the persisted progress configuration."""

    return runtime.load_config(refresh=refresh, default_config=DEFAULT_CONFIG)


CFG = load_config()
TZ = runtime.timezone()

# ---------------------
# Models
# ---------------------

@dataclass
class Snapshot:
    mech_id: str
    level: int = 1
    evo_acc: int = 0  # Evolution accumulator (cents)
    power_acc: int = 0  # Power accumulator (cents)
    goal_requirement: int = 0  # Requirement for next level (cents)
    difficulty_bin: int = 1
    goal_started_at: str = ""
    last_decay_day: str = ""  # YYYY-MM-DD (local)
    power_decay_per_day: int = 100  # cents
    version: int = 0
    last_event_seq: int = 0
    mech_type: str = "default"
    last_user_count_sample: int = 0
    cumulative_donations_cents: int = 0  # Total donations ever (never resets)

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "Snapshot":
        return Snapshot(**d)


@dataclass
class Event:
    seq: int
    ts: str  # ISO
    type: str
    mech_id: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {"seq": self.seq, "ts": self.ts, "type": self.type, "mech_id": self.mech_id, "payload": self.payload}


@dataclass
class ProgressState:
    """UI-ready state for display"""
    level: int
    power_current: float  # dollars (for display)
    power_max: float  # dollars (for display)
    power_percent: int  # 0-99
    evo_current: float  # dollars (for display)
    evo_max: float  # dollars (for display)
    evo_percent: int  # 0-100
    total_donated: float  # dollars (for display)
    can_level_up: bool
    is_offline: bool  # power == 0
    difficulty_bin: int
    difficulty_tier: str
    member_count: int


# ---------------------
# Storage helpers
# ---------------------

def now_utc_iso() -> str:
    return datetime.utcnow().replace(tzinfo=ZoneInfo("UTC")).isoformat()


def today_local_str() -> str:
    return datetime.now(TZ).date().isoformat()


def read_events() -> List[Event]:
    evts: List[Event] = []
    if not EVENT_LOG.exists():
        return evts  # Return empty list if file doesn't exist
    with open(EVENT_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            evts.append(Event(**raw))
    return evts


def append_event(evt: Event) -> None:
    # Ensure directory exists
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt.to_json(), separators=(",", ":")) + "\n")


def next_seq() -> int:
    tail_file = SEQ_FILE
    if tail_file.exists():
        with open(tail_file, "r", encoding="utf-8") as f:
            s = int(f.read().strip() or 0)
    else:
        s = 0
    s += 1
    with open(tail_file, "w", encoding="utf-8") as f:
        f.write(str(s))
    return s


def snapshot_path(mech_id: str) -> Path:
    safe = mech_id.replace("/", "_")
    return SNAPSHOT_DIR / f"{safe}.json"


def load_snapshot(mech_id: str) -> Snapshot:
    p = snapshot_path(mech_id)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return Snapshot.from_json(json.load(f))
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Corrupted snapshot file - log warning and recreate from events
            logger.warning(f"Corrupted snapshot file detected ({e}), rebuilding from events...")
            # Delete corrupted file and let rebuild_from_events create a fresh one
            p.unlink(missing_ok=True)
            # Fall through to create new snapshot below

    # First-time snapshot → initialize goal for level 1
    snap = Snapshot(mech_id=mech_id)
    set_new_goal_for_next_level(snap, user_count=0)
    snap.last_decay_day = today_local_str()
    persist_snapshot(snap)
    return snap


def persist_snapshot(snap: Snapshot) -> None:
    """
    Persist snapshot to disk using atomic write to prevent corruption.

    CRITICAL: Uses atomic rename to ensure snapshot is never left in corrupted state.
    If write fails mid-operation, original snapshot remains intact.
    """
    import tempfile
    import shutil

    p = snapshot_path(snap.mech_id)

    # Write to temporary file first (atomic write pattern)
    # Create temp file in same directory to ensure atomic rename works (same filesystem)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=p.parent,
        prefix=f".{p.name}.",
        suffix=".tmp"
    )

    try:
        # Write JSON to temp file
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(snap.to_json(), f, indent=2)
            f.flush()  # Ensure data is written to OS buffer
            os.fsync(f.fileno())  # Force write to disk (prevent data loss on crash)

        # Atomic rename: if this succeeds, snapshot is guaranteed to be valid
        # If this fails, original snapshot is untouched
        shutil.move(temp_path, p)

    except Exception:
        # Cleanup temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise  # Re-raise original exception


# ---------------------
# Domain utils
# ---------------------

def current_bin(user_count: int) -> int:
    bins = CFG["difficulty_bins"]
    idx = 1
    for i, lb in enumerate(bins, start=1):
        if user_count >= lb:
            idx = i
    return min(idx, 21)


def requirement_for_bin(b: int) -> int:
    """DEPRECATED: Use requirement_for_level_and_bin instead"""
    return int(CFG.get("bin_to_requirement", {}).get(str(b), 0))


def requirement_for_level_and_bin(level: int, b: int, member_count: int = None) -> int:
    """
    Calculate total requirement respecting Static Difficulty Override setting.

    The "Static Difficulty Override" toggle in Web UI controls the behavior:
    - Override OFF (use_dynamic=true): Pure dynamic difficulty based on community size
      → Cost = base + dynamic (multiplier ignored)
    - Override ON (use_dynamic=false): Static custom difficulty from slider
      → Cost = (base + dynamic) × multiplier

    Evolution mode is stored in config/evolution_mode.json and managed by ConfigService.

    Dynamic cost formula: First 10 members are FREE, then $0.10 per additional member.
    - 0-10 members: $0 dynamic cost
    - 11+ members: (member_count - 10) × $0.10
    """
    # =========================
    # INPUT VALIDATION & BOUNDS
    # =========================

    # Validate level (must be 1-11)
    if not isinstance(level, int) or level < 1 or level > 11:
        logger.error(f"Invalid level: {level} (type: {type(level)}). Must be int between 1-11. Using level 1.")
        level = 1

    # Validate bin (must be 1-21)
    if not isinstance(b, int) or b < 1 or b > 21:
        logger.warning(f"Invalid bin: {b} (type: {type(b)}). Must be int between 1-21. Using bin 1.")
        b = 1

    # Validate member_count if provided
    if member_count is not None:
        if not isinstance(member_count, int):
            try:
                member_count = int(member_count)
            except (TypeError, ValueError):
                logger.error(f"Invalid member_count type: {type(member_count)}. Using None.")
                member_count = None
        elif member_count < 0:
            logger.warning(f"Negative member_count: {member_count}. Using 0.")
            member_count = 0
        elif member_count > 100000:  # Discord's theoretical limit
            logger.warning(f"Member_count {member_count} exceeds Discord limit. Capping at 100000.")
            member_count = 100000

    # =========================
    # BASE COST CALCULATION
    # =========================

    # Get base cost for this level (minimum cost even for 1-person channel)
    base_cost = int(CFG.get("level_base_costs", {}).get(str(level), 0))

    # Validate base cost
    if base_cost <= 0:
        logger.error(f"Invalid base cost for level {level}: {base_cost}. Using default $10.00")
        base_cost = 1000  # Default $10.00
    elif base_cost > 1000000:  # Cap at $10,000
        logger.warning(f"Base cost {base_cost} exceeds max $10,000. Capping.")
        base_cost = 1000000

    # =========================
    # DYNAMIC COST CALCULATION
    # =========================

    # Calculate PRECISE dynamic cost based on actual member count
    # Formula: First 10 members FREE, then $0.10/member
    if member_count is not None and member_count >= 0:
        # Use precise member-based calculation
        FREEBIE_MEMBERS = 10
        COST_PER_MEMBER_CENTS = 10  # $0.10 = 10 cents

        if member_count <= FREEBIE_MEMBERS:
            dynamic_cost = 0
        else:
            billable_members = member_count - FREEBIE_MEMBERS
            # Check for potential overflow
            if billable_members > 999990:  # Would exceed $100k
                logger.warning(f"Dynamic cost would exceed $100k with {billable_members} billable members. Capping.")
                dynamic_cost = 1000000  # Cap at $10,000
            else:
                dynamic_cost = billable_members * COST_PER_MEMBER_CENTS
    else:
        # Fallback to bin-based cost if member_count not provided
        dynamic_cost = int(CFG.get("bin_to_dynamic_cost", {}).get(str(b), 0))
        if dynamic_cost < 0:
            logger.warning(f"Negative dynamic cost for bin {b}: {dynamic_cost}. Using 0.")
            dynamic_cost = 0
        elif dynamic_cost > 1000000:  # Cap at $10,000
            logger.warning(f"Dynamic cost {dynamic_cost} exceeds max $10,000. Capping.")
            dynamic_cost = 1000000

    # =========================
    # TOTAL COST CALCULATION
    # =========================

    # Base calculation with overflow protection
    try:
        subtotal = base_cost + dynamic_cost

        # Final validation: ensure total is reasonable
        if subtotal <= 0:
            logger.error(f"Invalid subtotal: {subtotal}. Using minimum $10.00")
            subtotal = 1000  # Minimum $10.00
        elif subtotal > 10000000:  # Cap at $100,000
            logger.warning(f"Subtotal {subtotal} exceeds max $100,000. Capping.")
            subtotal = 10000000

    except (OverflowError, ValueError) as e:
        logger.error(f"Overflow in cost calculation: base={base_cost}, dynamic={dynamic_cost}. Error: {e}")
        subtotal = 1000  # Safe fallback to $10.00

    # Check evolution mode to determine if we should apply multiplier
    try:
        from services.config.config_service import get_config_service, GetEvolutionModeRequest
        config_service = get_config_service()
        mode_request = GetEvolutionModeRequest()
        mode_result = config_service.get_evolution_mode_service(mode_request)

        if mode_result.success:
            use_dynamic = mode_result.use_dynamic
            multiplier = mode_result.difficulty_multiplier

            if use_dynamic:
                # Static Difficulty Override OFF: Use pure dynamic difficulty (community-based)
                total = subtotal
                member_info = f", {member_count} members" if member_count else ""
                logger.debug(f"Requirement for Level {level}→{level+1}, Bin {b}{member_info}: "
                            f"${base_cost/100:.2f} base + ${dynamic_cost/100:.2f} dynamic = ${total/100:.2f} "
                            f"(Dynamic mode - multiplier ignored)")
            else:
                # Static Difficulty Override ON: Apply custom multiplier
                total = int(subtotal * multiplier)
                member_info = f", {member_count} members" if member_count else ""
                logger.debug(f"Requirement for Level {level}→{level+1}, Bin {b}{member_info}: "
                            f"(${base_cost/100:.2f} base + ${dynamic_cost/100:.2f} dynamic) × {multiplier} = ${total/100:.2f} "
                            f"(Static mode - custom multiplier)")
        else:
            # Fallback: Use dynamic mode if config service fails
            logger.warning(f"Failed to get evolution mode: {mode_result.error}, using dynamic mode (no multiplier)")
            total = subtotal

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (config service unavailable)
        logger.warning(f"Service dependency error checking evolution mode: {e}, using dynamic mode (no multiplier)")
        total = subtotal
    except (KeyError, ValueError, TypeError) as e:
        # Data access/processing errors (config structure, value types)
        logger.warning(f"Data error checking evolution mode: {e}, using dynamic mode (no multiplier)")
        total = subtotal

    return total


def decay_per_day(mech_type: str) -> int:
    return int(CFG["mech_power_decay_per_day"].get(mech_type, CFG["mech_power_decay_per_day"]["default"]))


def bin_to_tier_name(b: int) -> str:
    """Get difficulty tier name from bin"""
    if b <= 1:
        return "Tiny Community"
    elif b <= 2:
        return "Small Community"
    elif b <= 3:
        return "Medium Community"
    elif b <= 5:
        return "Large Community"
    elif b <= 10:
        return "Huge Community"
    else:
        return "Massive Community"


def apply_decay_on_demand(snap: Snapshot) -> None:
    """
    DEPRECATED: Continuous decay is now calculated in compute_ui_state() based on elapsed time.
    This function is kept for backwards compatibility but does nothing.
    """
    # Set last_decay_day if not set (for backwards compatibility)
    if not snap.last_decay_day:
        snap.last_decay_day = today_local_str()
    # No actual decay application - done in compute_ui_state() instead


def set_new_goal_for_next_level(snap: Snapshot, user_count: int) -> None:
    """Set goal requirement using HYBRID COST SYSTEM: base cost (level) + dynamic cost (member count)"""
    b = current_bin(user_count)

    # HYBRID COST: Base cost (level progression) + Dynamic cost (precise member count)
    # Pass member_count for precise calculation: First 10 members FREE, then $0.10/member
    req = requirement_for_level_and_bin(snap.level, b, member_count=user_count)

    snap.difficulty_bin = b
    snap.goal_requirement = req
    snap.goal_started_at = now_utc_iso()
    snap.power_decay_per_day = decay_per_day(snap.mech_type)
    snap.last_user_count_sample = user_count

    # Get base and dynamic costs for logging
    base_cost = int(CFG.get("level_base_costs", {}).get(str(snap.level), 0))
    dynamic_cost = int(CFG.get("bin_to_dynamic_cost", {}).get(str(b), 0))

    logger.info(f"Set new goal for mech {snap.mech_id}: Level {snap.level} -> {snap.level + 1}, "
                f"requirement=${req/100:.2f} (${base_cost/100:.2f} base + ${dynamic_cost/100:.2f} dynamic, "
                f"bin={b}, users={user_count})")


def compute_ui_state(snap: Snapshot) -> ProgressState:
    # Calculate CONTINUOUS power decay based on elapsed time
    # Formula: current_power = power_acc - (elapsed_seconds / 86400) * decay_per_day
    power_acc_with_decay = snap.power_acc
    if snap.goal_started_at:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            goal_time = datetime.fromisoformat(snap.goal_started_at.replace('Z', '+00:00'))
            now = datetime.now(ZoneInfo("UTC"))
            elapsed_seconds = (now - goal_time).total_seconds()

            dpp = decay_per_day(snap.mech_type)
            decay_amount = (elapsed_seconds / 86400.0) * dpp
            power_acc_with_decay = max(0, snap.power_acc - int(decay_amount))
        except ImportError as e:
            # Import errors (zoneinfo module not available)
            logger.warning(f"Import error calculating continuous decay: {e}")
        except (ValueError, TypeError, KeyError) as e:
            # Data processing errors (datetime parsing, attribute access, calculations)
            logger.warning(f"Data error calculating continuous decay: {e}")

    power_max_cents = snap.goal_requirement + 100 if snap.goal_requirement > 0 else 100  # +$1
    power_percent = int((power_acc_with_decay * 100) // power_max_cents)
    power_percent = min(power_percent, 99 if snap.level < 11 else 100)

    evo_percent = 100 if snap.goal_requirement == 0 else int((snap.evo_acc * 100) // snap.goal_requirement)
    evo_percent = min(evo_percent, 100)

    # Use cumulative donations for total
    total_cents = snap.cumulative_donations_cents

    return ProgressState(
        level=snap.level,
        power_current=power_acc_with_decay / 100.0,
        power_max=power_max_cents / 100.0,
        power_percent=power_percent,
        evo_current=snap.evo_acc / 100.0,
        evo_max=snap.goal_requirement / 100.0,
        evo_percent=evo_percent,
        total_donated=total_cents / 100.0,
        can_level_up=snap.level < 11 and snap.evo_acc >= snap.goal_requirement,
        is_offline=snap.power_acc == 0,
        difficulty_bin=snap.difficulty_bin,
        difficulty_tier=bin_to_tier_name(snap.difficulty_bin),
        member_count=snap.last_user_count_sample
    )


def deterministic_gift_1_3(mech_id: str, campaign_id: str) -> int:
    h = hashlib.sha256((mech_id + "|" + campaign_id).encode("utf-8")).hexdigest()
    n = int(h[:8], 16)
    return ((n % 3) + 1) * 100  # 1-3 dollars in cents


# ---------------------
# Core logic
# ---------------------

def apply_donation_units(snap: Snapshot, units_cents: int) -> Tuple[Snapshot, List[Event], Optional[Event]]:
    """Apply donation units to evo & power; may trigger multiple LevelUpCommitted and ExactHitBonusGranted events."""
    # Track cumulative donations
    snap.cumulative_donations_cents += units_cents

    if snap.level >= 11:
        snap.power_acc += units_cents
        return snap, [], None

    new_evo = snap.evo_acc + units_cents
    snap.power_acc += units_cents

    if new_evo < snap.goal_requirement:
        snap.evo_acc = new_evo
        return snap, [], None

    # Process multiple level-ups if donation is large enough
    level_up_events = []
    bonus_event = None  # Only for the LAST exact hit

    while new_evo >= snap.goal_requirement and snap.level < 11:
        # Check for exact hit
        exact_hit = (new_evo == snap.goal_requirement)
        lvl_from = snap.level
        old_goal = snap.goal_requirement

        # Commit level-up
        snap.level = min(snap.level + 1, 11)

        # Carry over excess to next level
        excess = new_evo - old_goal
        snap.evo_acc = excess

        # Reset power to excess (same as evolution)
        snap.power_acc = excess

        # Add bonus for exact hit (only for last exact hit)
        if exact_hit:
            snap.power_acc += 100  # Add $1 bonus for exact hit
            # Store bonus event (will be returned for last exact hit only)
            bonus_event = Event(
                seq=0,
                ts=now_utc_iso(),
                type="ExactHitBonusGranted",
                mech_id=snap.mech_id,
                payload={
                    "power_units": 100,  # cents
                    "from_level": lvl_from,
                    "to_level": snap.level,
                    "reason": "exact_level_up"
                },
            )

        logger.info(f"Level up! Mech {snap.mech_id}: {lvl_from} -> {snap.level} (exact_hit={exact_hit})")

        # Create level-up event
        lvl_evt = Event(
            seq=0,
            ts=now_utc_iso(),
            type="LevelUpCommitted",
            mech_id=snap.mech_id,
            payload={
                "from_level": lvl_from,
                "to_level": snap.level,
                "old_goal_requirement": old_goal,
                "exact_hit": exact_hit,
            },
        )
        level_up_events.append(lvl_evt)

        # Calculate new goal for next level
        if snap.level < 11:
            # Get current STATUS CHANNEL member count for accurate dynamic cost calculation
            # IMPORTANT: We count ONLY members who can see status channels, NOT all server members
            # This data is updated by the bot at startup and stored in member_count.json
            import json

            member_count_file = MEMBER_COUNT_FILE
            if member_count_file.exists():
                try:
                    with open(member_count_file, 'r') as f:
                        data = json.load(f)
                        current_member_count = data.get("count", 50)
                        logger.info(f"Level-up: Loaded status channel member count from config: {current_member_count}")
                except (IOError, OSError) as e:
                    # File I/O errors (read errors, permissions)
                    logger.warning(f"File I/O error reading member_count.json: {e}, using default")
                    current_member_count = 50
                except json.JSONDecodeError as e:
                    # JSON parsing errors (corrupted file)
                    logger.warning(f"JSON parsing error reading member_count.json: {e}, using default")
                    current_member_count = 50
                except (KeyError, ValueError, TypeError) as e:
                    # Data access/structure errors (missing 'count' key, invalid values)
                    logger.warning(f"Data error reading member_count.json: {e}, using default")
                    current_member_count = 50
            else:
                # Use a reasonable default for testing (50 status channel members)
                current_member_count = 50
                logger.info(f"Level-up: member_count.json not found, using default: {current_member_count}")

            logger.info(f"Level-up: Using {current_member_count} status channel members for dynamic cost calculation")
            set_new_goal_for_next_level(snap, user_count=current_member_count)
        else:
            snap.goal_requirement = 0
            break  # Max level reached

        # Update new_evo for next iteration
        new_evo = excess

    # Return list of level-up events and optional bonus event (for last exact hit)
    return snap, level_up_events, bonus_event


# ---------------------
# Service Class
# ---------------------

class ProgressService:
    """Main service class for progress management"""

    def __init__(self, mech_id: str = "main"):
        self.mech_id = mech_id
        logger.info(f"Progress Service initialized for mech_id={mech_id}")

    def get_state(self) -> ProgressState:
        """Get current state with UI-ready fields"""
        with LOCK:
            snap = load_snapshot(self.mech_id)
            apply_decay_on_demand(snap)
            persist_snapshot(snap)
            return compute_ui_state(snap)

    def add_donation(self, amount_dollars: float, donor: Optional[str] = None,
                    channel_id: Optional[str] = None, idempotency_key: Optional[str] = None) -> ProgressState:
        """Add a donation and return updated state"""
        units_cents = int(amount_dollars * 100)
        if units_cents <= 0:
            raise ValueError("Donation amount must be positive")

        # Generate idempotency key if not provided
        if idempotency_key is None:
            idempotency_key = hashlib.sha256(
                f"{self.mech_id}|{donor}|{amount_dollars}|{datetime.utcnow().isoformat()}".encode()
            ).hexdigest()[:16]

        with LOCK:
            # Check idempotency
            existing = [e for e in read_events()
                       if e.mech_id == self.mech_id
                       and e.type == "DonationAdded"
                       and e.payload.get("idempotency_key") == idempotency_key]
            if existing:
                logger.info(f"Idempotent donation detected: {idempotency_key}")
                snap = load_snapshot(self.mech_id)
                apply_decay_on_demand(snap)
                return compute_ui_state(snap)

            donation_id = hashlib.sha256((self.mech_id + "|" + idempotency_key).encode()).hexdigest()[:16]

            # Create donation event
            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="DonationAdded",
                mech_id=self.mech_id,
                payload={
                    "donation_id": donation_id,
                    "idempotency_key": idempotency_key,
                    "units": units_cents,
                    "donor": donor,
                    "channel_id": channel_id,
                },
            )
            append_event(evt)

            # Apply to snapshot
            snap = load_snapshot(self.mech_id)
            apply_decay_on_demand(snap)
            snap, lvl_events, bonus_evt = apply_donation_units(snap, units_cents)

            # Append all level-up events (may be multiple for large donations)
            for lvl_evt in lvl_events:
                lvl_evt.seq = next_seq()
                append_event(lvl_evt)

            # Append exact-hit bonus event if triggered
            if bonus_evt is not None:
                bonus_evt.seq = next_seq()
                append_event(bonus_evt)

            snap.version += 1
            snap.last_event_seq = evt.seq
            persist_snapshot(snap)

            logger.info(f"Donation added: ${amount_dollars:.2f} from {donor} (id={donation_id})")
            return compute_ui_state(snap)

    def add_system_donation(self, amount_dollars: float, event_name: str,
                           description: Optional[str] = None,
                           idempotency_key: Optional[str] = None) -> ProgressState:
        """
        Add a SYSTEM DONATION (Power-Only, No Evolution Progress).

        System donations increase ONLY power (mech moves), NOT evolution progress.
        Use cases: Community events, achievements, milestones, automatic rewards.

        Args:
            amount_dollars: Amount in dollars (converted to power cents)
            event_name: Name of the event (e.g., "Server 100 Members", "Bot Birthday")
            description: Optional description
            idempotency_key: Optional key to prevent duplicates

        Returns:
            Updated ProgressState

        Example:
            # Community milestone
            state = progress_service.add_system_donation(
                amount_dollars=5.0,
                event_name="Server 100 Members",
                description="Milestone achievement!"
            )
            # Result: Power +$5, Evolution Bar unchanged
        """
        # =========================
        # INPUT VALIDATION
        # =========================

        # Validate amount
        if not isinstance(amount_dollars, (int, float)):
            raise TypeError(f"Amount must be numeric, got {type(amount_dollars)}")

        if amount_dollars <= 0:
            raise ValueError(f"Amount must be positive, got {amount_dollars}")

        MAX_SYSTEM_DONATION = 1000  # $1,000 max for system donations
        if amount_dollars > MAX_SYSTEM_DONATION:
            raise ValueError(f"System donation ${amount_dollars} exceeds maximum ${MAX_SYSTEM_DONATION}")

        # Validate event_name
        if not event_name or not isinstance(event_name, str):
            raise ValueError(f"Event name must be a non-empty string, got: {event_name}")

        if len(event_name) > 100:
            logger.warning(f"Event name exceeds 100 chars, truncating: {event_name[:100]}...")
            event_name = event_name[:100]

        # Validate description
        if description is not None:
            if not isinstance(description, str):
                logger.warning(f"Description is not a string, converting: {description}")
                description = str(description)[:500]
            elif len(description) > 500:
                logger.warning(f"Description exceeds 500 chars, truncating")
                description = description[:500]

        # Convert to cents with overflow protection
        try:
            # Round to nearest cent
            units_cents = int(round(amount_dollars * 100))

            # Allow amounts that round to zero (e.g., $0.001) but reject if original was <= 0
            if units_cents < 0:
                raise ValueError(f"Amount rounds to negative: {units_cents}")
            elif units_cents == 0 and amount_dollars > 0:
                # Very small positive amount rounds to zero - allow but warn
                logger.warning(f"Amount ${amount_dollars} rounds to $0.00 - donation will have no effect")
                units_cents = 0  # Allow it to proceed (will be a no-op)
            elif units_cents == 0:
                # Original amount was zero or negative
                raise ValueError(f"Amount must be positive, got {amount_dollars}")

            if units_cents > 2147483647:  # Max 32-bit int
                raise ValueError(f"Amount too large for system: {units_cents} cents")

        except (OverflowError, TypeError) as e:
            raise ValueError(f"Invalid amount conversion: {e}")

        # Generate idempotency key if not provided
        if idempotency_key is None:
            import os
            salt = os.urandom(8).hex()  # Add randomness to prevent collisions
            idempotency_key = hashlib.sha256(
                f"{self.mech_id}|system|{event_name}|{amount_dollars}|{salt}".encode()
            ).hexdigest()[:16]
        elif not isinstance(idempotency_key, str):
            idempotency_key = str(idempotency_key)[:32]

        with LOCK:
            # If amount rounds to zero, just return current state (no-op)
            if units_cents == 0:
                logger.info(f"System donation of ${amount_dollars} rounds to $0.00 - skipping (no effect)")
                snap = load_snapshot(self.mech_id)
                apply_decay_on_demand(snap)
                return compute_ui_state(snap)

            # Check idempotency
            existing = [e for e in read_events()
                       if e.mech_id == self.mech_id
                       and e.type == "SystemDonationAdded"
                       and e.payload.get("idempotency_key") == idempotency_key]
            if existing:
                logger.info(f"Idempotent system donation detected: {idempotency_key}")
                snap = load_snapshot(self.mech_id)
                apply_decay_on_demand(snap)
                return compute_ui_state(snap)

            # Create system donation event
            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="SystemDonationAdded",
                mech_id=self.mech_id,
                payload={
                    "idempotency_key": idempotency_key,
                    "power_units": units_cents,  # Only affects power!
                    "event_name": event_name,
                    "description": description,
                },
            )
            append_event(evt)

            # Apply to snapshot: ONLY power, NOT evolution!
            try:
                snap = load_snapshot(self.mech_id)
                apply_decay_on_demand(snap)

                # Validate current state before modifying
                if snap.power_acc < 0:
                    logger.error(f"Corrupted power_acc before donation: {snap.power_acc}. Resetting to 0.")
                    snap.power_acc = 0

                if snap.cumulative_donations_cents < 0:
                    logger.error(f"Corrupted cumulative_donations: {snap.cumulative_donations_cents}. Resetting to 0.")
                    snap.cumulative_donations_cents = 0

                # Check for potential overflow BEFORE adding
                MAX_POWER = 10000000  # $100,000 max power
                if snap.power_acc > MAX_POWER - units_cents:
                    logger.warning(f"Power would exceed ${MAX_POWER/100:.2f}. Capping at max.")
                    snap.power_acc = MAX_POWER
                else:
                    # Add to power ONLY (not evo_acc!)
                    snap.power_acc += units_cents

                # Update cumulative with overflow protection
                MAX_CUMULATIVE = 100000000  # $1,000,000 max cumulative
                if snap.cumulative_donations_cents > MAX_CUMULATIVE - units_cents:
                    logger.warning(f"Cumulative would exceed ${MAX_CUMULATIVE/100:.2f}. Capping.")
                    snap.cumulative_donations_cents = MAX_CUMULATIVE
                else:
                    snap.cumulative_donations_cents += units_cents

                # Update metadata
                snap.version += 1
                snap.last_event_seq = evt.seq

                # Final validation before persisting
                if snap.power_acc < 0 or snap.cumulative_donations_cents < 0:
                    raise ValueError(f"Negative values after update: power={snap.power_acc}, cumulative={snap.cumulative_donations_cents}")

                persist_snapshot(snap)

                logger.info(f"System donation added: ${amount_dollars:.2f} for '{event_name}' "
                           f"(Power +${amount_dollars:.2f}, Evolution unchanged)")
                return compute_ui_state(snap)

            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                # Snapshot operation errors (state updates, attribute access, calculations)
                logger.error(f"Failed to apply system donation to snapshot: {e}", exc_info=True)
                # Event was already written, so we need to mark it as failed somehow
                # For now, just re-raise to let caller handle
                raise

    def update_member_count(self, member_count: int) -> None:
        """Update member count for difficulty calculation"""
        with LOCK:
            # Create MemberCountUpdated event for replay capability
            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="MemberCountUpdated",
                mech_id=self.mech_id,
                payload={"member_count": max(0, member_count)}
            )
            append_event(evt)

            snap = load_snapshot(self.mech_id)
            snap.last_user_count_sample = max(0, member_count)
            snap.last_event_seq = evt.seq
            persist_snapshot(snap)
            logger.info(f"Updated member count to {member_count}")

    def tick_decay(self) -> ProgressState:
        """Manually trigger decay check (useful for testing/cron)"""
        with LOCK:
            snap = load_snapshot(self.mech_id)
            apply_decay_on_demand(snap)
            persist_snapshot(snap)
            return compute_ui_state(snap)

    def power_gift(self, campaign_id: str) -> Tuple[ProgressState, Optional[int]]:
        """Grant power gift if power is 0 AND campaign hasn't been used. Returns (state, gift_dollars or None)"""
        with LOCK:
            snap = load_snapshot(self.mech_id)
            apply_decay_on_demand(snap)

            if snap.power_acc > 0:
                logger.info(f"Power gift skipped: power > 0")
                persist_snapshot(snap)
                return compute_ui_state(snap), None

            # CHECK FOR DUPLICATE: Search event log for this campaign_id
            all_events = read_events()
            for evt in all_events:
                if evt.type == "PowerGiftGranted" and evt.mech_id == self.mech_id:
                    existing_campaign = evt.payload.get("campaign_id")
                    if existing_campaign == campaign_id:
                        logger.info(f"Power gift skipped: campaign_id '{campaign_id}' already used")
                        persist_snapshot(snap)
                        return compute_ui_state(snap), None

            gift_cents = deterministic_gift_1_3(self.mech_id, campaign_id)

            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="PowerGiftGranted",
                mech_id=self.mech_id,
                payload={"campaign_id": campaign_id, "power_units": gift_cents},
            )
            append_event(evt)

            snap.power_acc += gift_cents
            snap.version += 1
            snap.last_event_seq = evt.seq
            persist_snapshot(snap)

            gift_dollars = gift_cents / 100.0
            logger.info(f"Power gift granted: ${gift_dollars:.2f}")
            return compute_ui_state(snap), gift_dollars

    def rebuild_from_events(self) -> ProgressState:
        """
        Rebuild snapshot from scratch by replaying all events CHRONOLOGICALLY.

        SIMPLE TIME-AWARE APPROACH:
        1. Go through events chronologically (by timestamp, not seq!)
        2. Calculate decay since last event
        3. Apply event (Donation, PowerGift, etc.)
        4. apply_donation_units handles level-ups and power reset
        5. System donations ignored (except initial $3)

        This correctly handles decay over 3+ years by simulating time progression.
        """
        with LOCK:
            # Read all events for this mech
            all_events = [e for e in read_events() if e.mech_id == self.mech_id]

            # Calculate deleted_seqs (restoration support)
            deleted_seqs = set()
            for evt in all_events:
                if evt.type == "DonationDeleted":
                    payload = evt.payload or {}
                    deleted_seq = payload.get("deleted_seq")
                    if deleted_seq:
                        # Check if THIS deletion event is itself deleted (restoration!)
                        is_this_deletion_deleted = any(
                            e.type == "DonationDeleted" and
                            (e.payload or {}).get("deleted_seq") == evt.seq
                            for e in all_events
                        )
                        if not is_this_deletion_deleted:
                            deleted_seqs.add(deleted_seq)
                            logger.info(f"Marking event seq {deleted_seq} as deleted")
                        else:
                            logger.info(f"DonationDeleted seq {evt.seq} is itself deleted → Restoring seq {deleted_seq}")

            # Create fresh snapshot at Level 1
            snap = Snapshot(mech_id=self.mech_id)
            set_new_goal_for_next_level(snap, user_count=0)
            snap.last_decay_day = today_local_str()

            # Track last event timestamp for decay calculation
            last_timestamp = None
            dpp = decay_per_day(snap.mech_type)

            # Replay all events in CHRONOLOGICAL ORDER (by timestamp!)
            last_seq = 0
            for evt in sorted(all_events, key=lambda e: e.ts):
                last_seq = max(last_seq, evt.seq)

                # Skip deleted events
                if evt.seq in deleted_seqs:
                    continue

                # Skip DonationDeleted events (metadata, not actual events to replay)
                if evt.type == "DonationDeleted":
                    continue

                # STEP 1: Calculate decay since last event
                if last_timestamp and evt.ts:
                    try:
                        from datetime import datetime
                        from zoneinfo import ZoneInfo

                        # Parse timestamps
                        last_time = datetime.fromisoformat(last_timestamp.replace('Z', '+00:00'))
                        current_time = datetime.fromisoformat(evt.ts.replace('Z', '+00:00'))

                        # Calculate elapsed time
                        elapsed_seconds = (current_time - last_time).total_seconds()
                        elapsed_days = elapsed_seconds / 86400.0

                        # Calculate decay amount
                        decay_amount = int(elapsed_days * dpp)

                        # Apply decay to power
                        if decay_amount > 0:
                            snap.power_acc = max(0, snap.power_acc - decay_amount)
                            logger.debug(f"Applied decay: {elapsed_days:.2f} days = ${decay_amount/100:.2f} "
                                       f"(power: ${snap.power_acc/100:.2f})")
                    except (ValueError, AttributeError, ImportError) as e:
                        logger.warning(f"Could not calculate decay between events: {e}")

                # STEP 2: Apply event based on type
                payload = evt.payload or {}

                if evt.type == "DonationAdded":
                    # Apply user donation (affects both power and evolution)
                    units_cents = payload.get("units", 0)
                    snap, lvl_evt, bonus_evt = apply_donation_units(snap, units_cents)
                    logger.debug(f"Applied DonationAdded: ${units_cents/100:.2f} "
                               f"(power: ${snap.power_acc/100:.2f}, evo: ${snap.evo_acc/100:.2f}, level: {snap.level})")

                elif evt.type == "SystemDonationAdded":
                    # System donations: Ignore ALL except initial $3
                    is_initial = payload.get("is_initial", False)
                    if is_initial:
                        initial_power = payload.get("power_units", 300)  # $3 default
                        snap.power_acc += initial_power
                        logger.debug(f"Applied initial SystemDonation: ${initial_power/100:.2f}")
                    else:
                        logger.debug("Skipping non-initial SystemDonation")

                elif evt.type == "PowerGiftGranted":
                    # Power gift: Power ONLY, no evolution
                    gift_cents = payload.get("power_units", 0)
                    snap.power_acc += gift_cents
                    logger.debug(f"Applied PowerGift: ${gift_cents/100:.2f}")

                elif evt.type == "ExactHitBonusGranted":
                    # Exact hit bonus: Power + counts as donation
                    bonus_cents = payload.get("power_units", 0)
                    snap.power_acc += bonus_cents
                    snap.cumulative_donations_cents += bonus_cents
                    logger.debug(f"Applied ExactHitBonus: ${bonus_cents/100:.2f}")

                elif evt.type == "MemberCountUpdated":
                    # Update member count
                    new_count = payload.get("member_count", 0)
                    snap.last_user_count_sample = new_count

                elif evt.type == "LevelUpCommitted":
                    # Skip - these are generated during apply_donation_units
                    pass

                # Update last_timestamp for next iteration
                if evt.ts:
                    last_timestamp = evt.ts

            # Set goal_started_at to last event timestamp
            # This allows compute_ui_state to calculate decay from last event to NOW
            if last_timestamp:
                snap.goal_started_at = last_timestamp
                logger.info(f"Set goal_started_at to last event timestamp: {last_timestamp}")
            else:
                snap.goal_started_at = now_utc_iso()
                logger.info("No events with timestamp, using current time")

            # Update snapshot metadata
            snap.version += 1
            snap.last_event_seq = last_seq
            persist_snapshot(snap)

            logger.info(f"Rebuilt snapshot from {len(all_events)} events "
                       f"(skipped {len(deleted_seqs)} deleted, final: power=${snap.power_acc/100:.2f}, "
                       f"evo=${snap.evo_acc/100:.2f}, level={snap.level})")

            return compute_ui_state(snap)

    def delete_donation(self, donation_seq: int) -> ProgressState:
        """
        Delete a donation by adding a DonationDeleted compensation event.

        This is EVENT SOURCING COMPLIANT:
        - We don't modify past events (immutable log)
        - We add a new event marking the donation as deleted
        - We rebuild the snapshot from scratch, skipping deleted donations
        - All level-ups and costs are recalculated correctly

        Args:
            donation_seq: The sequence number of the donation event to delete
                         (supports DonationAdded, PowerGiftGranted, SystemDonationAdded, ExactHitBonusGranted)

        Returns:
            Updated ProgressState after rebuilding from events
        """
        with LOCK:
            # Verify the donation exists (support all donation types)
            all_events = [e for e in read_events() if e.mech_id == self.mech_id]
            donation_event = next((e for e in all_events
                                  if e.seq == donation_seq
                                  and e.type in ["DonationAdded", "PowerGiftGranted", "SystemDonationAdded", "ExactHitBonusGranted"]), None)

            if not donation_event:
                raise ValueError(f"Donation with seq {donation_seq} not found")

            # Check if already deleted
            already_deleted = any(e for e in all_events
                                 if e.type == "DonationDeleted"
                                 and e.payload.get("deleted_seq") == donation_seq)

            if already_deleted:
                raise ValueError(f"Donation seq {donation_seq} is already deleted")

            # Extract donor name and amount based on event type
            if donation_event.type == "DonationAdded":
                donor = donation_event.payload.get("donor", "Anonymous")
                units = donation_event.payload.get("units", 0)
            elif donation_event.type == "PowerGiftGranted":
                donor = "🎁 Power Gift"
                units = donation_event.payload.get("power_units", 0)
            elif donation_event.type == "SystemDonationAdded":
                donor = f"🤖 {donation_event.payload.get('event_name', 'System Event')}"
                units = donation_event.payload.get("power_units", 0)
            elif donation_event.type == "ExactHitBonusGranted":
                from_level = donation_event.payload.get('from_level', '?')
                to_level = donation_event.payload.get('to_level', '?')
                donor = f"🎯 Exact Hit Bonus (Level {from_level} → {to_level})"
                units = donation_event.payload.get("power_units", 0)
            else:
                donor = "Unknown"
                units = 0

            # Create DonationDeleted compensation event
            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="DonationDeleted",
                mech_id=self.mech_id,
                payload={
                    "deleted_seq": donation_seq,
                    "donor": donor,
                    "units": units,
                    "reason": "admin_deletion",
                    "original_type": donation_event.type  # Track original event type
                }
            )
            append_event(evt)

            logger.info(f"Donation deletion event added for seq {donation_seq} "
                       f"(${units/100:.2f} from {donor}, type: {donation_event.type})")

            # Rebuild snapshot from scratch
            return self.rebuild_from_events()


# ---------------------
# Global instance
# ---------------------
_progress_service: Optional[ProgressService] = None


def get_progress_service(mech_id: str = "main") -> ProgressService:
    """Get the global progress service instance"""
    global _progress_service
    if _progress_service is None:
        _progress_service = ProgressService(mech_id)
    return _progress_service
