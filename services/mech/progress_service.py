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
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import logging

from services.mech.progress import get_progress_runtime
from utils.atomic_io import atomic_write_text

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

# Snapshot key written by pre-release builds of this version; v2.3.1 loads snapshots with
# Snapshot(**d), so an extra key breaks every status/donation call after a downgrade
LEGACY_DECAY_ANCHOR_KEY = "power_decay_since"


@dataclass
class Snapshot:
    # Keep these fields identical to v2.3.1 (see LEGACY_DECAY_ANCHOR_KEY)
    mech_id: str
    level: int = 1
    evo_acc: int = 0  # Evolution accumulator (cents)
    power_acc: int = 0  # Power accumulator (cents)
    goal_requirement: int = 0  # Requirement for next level (cents)
    difficulty_bin: int = 1
    # Decay anchor (ISO, UTC): power_acc is the power as of this moment. Set at level-up and
    # on every power change (decay settled first); decay since then is applied continuously
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
        # Ignore unknown keys so snapshots written by other versions still load
        known = {f.name for f in fields(Snapshot)}
        snap = Snapshot(**{k: v for k, v in d.items() if k in known})
        # Pre-release builds kept the decay anchor in its own key; it is the moment
        # power_acc refers to, so it replaces goal_started_at (same displayed power)
        legacy_anchor = d.get(LEGACY_DECAY_ANCHOR_KEY)
        if _is_aware_iso(legacy_anchor):
            snap.goal_started_at = legacy_anchor
        return snap


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


def read_events(count_damaged: bool = False):
    """Read the event log, skipping damaged lines.

    With ``count_damaged=True`` returns ``(events, damaged_lines)``. Callers that REPLACE
    state from the log (rebuild_from_events) must use it: replaying an incomplete log over
    the snapshot would silently drop donations, levels and power.
    """
    evts: List[Event] = []
    damaged = 0
    if not EVENT_LOG.exists():
        return (evts, damaged) if count_damaged else evts
    with open(EVENT_LOG, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            # Skip damaged lines (e.g. truncated by a crash during append) instead of
            # failing every donation until the log is repaired by hand
            try:
                raw = json.loads(line)
                evts.append(Event(**raw))
            except (json.JSONDecodeError, TypeError) as e:
                damaged += 1
                logger.error(f"Skipping corrupt line {line_no} in {EVENT_LOG.name}: {e}")
    return (evts, damaged) if count_damaged else evts


def append_event(evt: Event) -> None:
    # Ensure directory exists
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    # If the last line was truncated (no trailing newline), start a new line so the
    # new event is not glued onto the damaged one
    prefix = ""
    if EVENT_LOG.exists() and EVENT_LOG.stat().st_size > 0:
        with open(EVENT_LOG, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                prefix = "\n"
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(prefix + json.dumps(evt.to_json(), separators=(",", ":")) + "\n")


def next_seq() -> int:
    tail_file = SEQ_FILE
    if tail_file.exists():
        with open(tail_file, "r", encoding="utf-8") as f:
            s = int(f.read().strip() or 0)
    else:
        s = 0
    s += 1
    # Previously a plain open(..., "w"), which truncates the counter the moment it
    # is opened: a crash before the write left the file EMPTY, not stale. next_seq()
    # then read int("" or 0) and restarted at 1 - handing out sequence numbers that
    # already exist in the event log this counter numbers. The lock around the
    # callers guards against interleaving, not against a crash. See SPEC.md Z7/Z1.
    atomic_write_text(tail_file, str(s))
    return s


def snapshot_path(mech_id: str) -> Path:
    safe = mech_id.replace("/", "_").replace("..", "_")
    return SNAPSHOT_DIR / f"{safe}.json"


def load_snapshot(mech_id: str) -> Snapshot:
    p = snapshot_path(mech_id)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            snap = Snapshot.from_json(raw)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError) as e:
            return _recover_corrupt_snapshot(mech_id, p, e)
        anchor_before = snap.goal_started_at
        _ensure_decay_anchor(snap)
        if LEGACY_DECAY_ANCHOR_KEY in raw:
            # Rewrite without the pre-release key so a downgrade to v2.3.1 can still load it
            with LOCK:
                persist_snapshot(snap)
            logger.info(f"Migrated snapshot {p.name}: decay anchor moved into goal_started_at")
        elif snap.goal_started_at != anchor_before:
            # _ensure_decay_anchor() repaired a missing or naive anchor (the v2.3.1 admin reset
            # wrote naive timestamps) - but only in memory. This used to reach disk because
            # get_state() persisted after every read; once that write became conditional the
            # repair stopped being permanent and the old timestamp stayed in the file forever.
            # The migration belongs here, next to the other two, so it holds for EVERY caller
            # and not just the one that happens to write afterwards. An already valid anchor is
            # left untouched, so this does not reintroduce the write-on-every-read.
            with LOCK:
                persist_snapshot(snap)
            logger.info(f"Migrated snapshot {p.name}: decay anchor is now timezone-aware")
        return snap

    # First-time snapshot → initialize goal for level 1
    snap = Snapshot(mech_id=mech_id)
    set_new_goal_for_next_level(snap, user_count=0)
    snap.last_decay_day = today_local_str()
    persist_snapshot(snap)
    return snap


def _recover_corrupt_snapshot(mech_id: str, p: Path, error: Exception) -> Snapshot:
    """Keep a copy of a corrupt snapshot and rebuild the state from the event log."""
    backup = p.with_name(f"{p.name}.corrupt-{int(time.time())}")
    try:
        os.replace(p, backup)
        logger.warning(f"Corrupted snapshot file detected ({error}); saved as {backup.name}, "
                       f"rebuilding from events...")
    except OSError as move_error:
        logger.warning(f"Corrupted snapshot file detected ({error}); backup failed ({move_error}), "
                       f"rebuilding from events...")
    # rebuild_from_events persists a fresh snapshot (replacing the corrupt file)
    ProgressService(mech_id).rebuild_from_events()
    try:
        with open(p, "r", encoding="utf-8") as f:
            return Snapshot.from_json(json.load(f))
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as read_error:
        # The rebuild could not write the snapshot (read-only dir, disk full). Don't raise out
        # of load_snapshot - callers only expect snapshot-decode errors - keep the mech usable.
        logger.error(f"Rebuilt snapshot for {mech_id} could not be read back ({read_error}); "
                     f"continuing with a fresh in-memory snapshot", exc_info=True)
        snap = Snapshot(mech_id=mech_id)
        _ensure_decay_anchor(snap)
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


# Cache for decay config to prevent disk I/O spam during event replay
_decay_config_cache = {"data": None, "last_load": 0}

def get_decay_config_data() -> dict:
    """Load decay config with simple caching (10s TTL)."""
    # Note: No global needed - we only modify dict contents, not reassign
    now = time.time()
    
    if _decay_config_cache["data"] and (now - _decay_config_cache["last_load"] < 10):
        return _decay_config_cache["data"]
        
    try:
        # The operator's <config dir>/mech/decay.json, else the shipped default
        # (services/mech/mech_defaults.py). Without the shipped file, a fresh
        # installation decayed EVERY level at 100 cents - the immortal level 11
        # included.
        from services.mech.mech_defaults import resolve_mech_file
        config_path = resolve_mech_file("decay.json")
        if config_path.exists():
            with open(config_path, "r") as f:
                data = json.load(f)
                _decay_config_cache["data"] = data
                _decay_config_cache["last_load"] = now
                return data
    except Exception as e:
        logger.error(f"Error loading decay config: {e}")
    
    return {"default": 100}


def decay_per_day(level: int) -> int:
    """Load decay per day from JSON config based on level (cached)."""
    decay_cfg = get_decay_config_data()
    val = decay_cfg.get("levels", {}).get(str(level))
    if val is not None:
        return int(val)
    return int(decay_cfg.get("default", 100))


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
    snap.power_decay_per_day = decay_per_day(snap.level)
    snap.last_user_count_sample = user_count

    # Get base and dynamic costs for logging
    base_cost = int(CFG.get("level_base_costs", {}).get(str(snap.level), 0))
    dynamic_cost = int(CFG.get("bin_to_dynamic_cost", {}).get(str(b), 0))

    logger.info(f"Set new goal for mech {snap.mech_id}: Level {snap.level} -> {snap.level + 1}, "
                f"requirement=${req/100:.2f} (${base_cost/100:.2f} base + ${dynamic_cost/100:.2f} dynamic, "
                f"bin={b}, users={user_count})")


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _member_count_file_sample() -> Optional[Tuple[Optional[datetime], int]]:
    """(last_updated or None, count) from member_count.json, None if missing or unusable."""
    member_count_file = MEMBER_COUNT_FILE
    if not member_count_file.exists():
        return None
    try:
        with open(member_count_file, 'r') as f:
            data = json.load(f)
        count = _positive_int(data.get("count"))
        if count is None:
            return None
        return _event_time(data.get("last_updated")), count
    except (IOError, OSError) as e:
        # File I/O errors (read errors, permissions)
        logger.warning(f"File I/O error reading member_count.json: {e}")
    except json.JSONDecodeError as e:
        # JSON parsing errors (corrupted file)
        logger.warning(f"JSON parsing error reading member_count.json: {e}")
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        # Data access/structure errors (missing 'count' key, invalid values)
        logger.warning(f"Data error reading member_count.json: {e}")
    return None


def member_count_for_goal(snap: Snapshot, *, events: Optional[List[Event]] = None,
                          at: Optional[datetime] = None, default: int = 50) -> int:
    """Status channel member count used to price the next level goal.

    Uses the most recent sample: the latest MemberCountUpdated event (published whenever
    the bot counts the status channel members) or member_count.json (written at bot
    startup), whichever is newer; a file without timestamp is older than any event.
    Samples taken after ``at`` are ignored (rebuild prices a level as of its donation).
    Falls back to the snapshot's sample, then to ``default``.
    """
    if events is None:
        events = read_events()
    latest: Optional[Tuple[datetime, int]] = None
    for evt in events:
        if evt.mech_id != snap.mech_id or evt.type != "MemberCountUpdated":
            continue
        ts = _event_time(evt.ts)
        count = _positive_int((evt.payload or {}).get("member_count"))
        if ts is None or count is None or (at is not None and ts > at):
            continue
        if latest is None or ts >= latest[0]:
            latest = (ts, count)

    file_sample = _member_count_file_sample()
    if file_sample is not None and at is not None and file_sample[0] is not None and file_sample[0] > at:
        file_sample = None
    if file_sample is not None and (latest is None or (file_sample[0] is not None and file_sample[0] > latest[0])):
        logger.info(f"Level-up: Using status channel member count from member_count.json: {file_sample[1]}")
        return file_sample[1]
    if latest is not None:
        logger.info(f"Level-up: Using latest published status channel member count: {latest[1]}")
        return latest[1]
    if snap.last_user_count_sample and snap.last_user_count_sample > 0:
        logger.info(f"Level-up: Using snapshot member count sample: {snap.last_user_count_sample}")
        return int(snap.last_user_count_sample)
    logger.info(f"Level-up: No status channel member count known, using default: {default}")
    return default


def _parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def _is_aware_iso(ts: Any) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    try:
        return _parse_utc(ts).tzinfo is not None
    except ValueError:
        return False


def _event_time(ts: Any) -> Optional[datetime]:
    """Aware datetime for an event timestamp (naive = UTC), None if missing or unparseable."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        parsed = _parse_utc(ts)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=ZoneInfo("UTC"))


def _ensure_decay_anchor(snap: Snapshot) -> None:
    """Make sure goal_started_at (the decay anchor) is a timezone-aware timestamp.

    A missing, naive or unparseable goal_started_at (the old admin reset wrote a naive
    one) meant "no decay" in the old code (the error was swallowed), so the decay clock
    starts now instead of making the displayed power jump.
    """
    if not _is_aware_iso(snap.goal_started_at):
        snap.goal_started_at = now_utc_iso()


def current_power_cents(snap: Snapshot, now: Optional[datetime] = None) -> int:
    """Current power in cents: power_acc minus the decay accrued since the anchor, clamped at 0.

    Formula: power = max(0, power_acc - (elapsed_seconds / 86400) * decay_per_day)
    """
    anchor = snap.goal_started_at
    if not anchor:
        return max(0, snap.power_acc)
    try:
        now = now or datetime.now(ZoneInfo("UTC"))
        elapsed_seconds = max(0.0, (now - _parse_utc(anchor)).total_seconds())
        decay_amount = (elapsed_seconds / 86400.0) * decay_per_day(snap.level)
        return max(0, snap.power_acc - int(decay_amount))
    except (ValueError, TypeError, KeyError) as e:
        # Data processing errors (datetime parsing, naive timestamps, calculations)
        logger.warning(f"Data error calculating continuous decay: {e}")
        return max(0, snap.power_acc)


def settle_power_decay(snap: Snapshot, now: Optional[datetime] = None) -> None:
    """Fold the decay accrued until ``now`` into power_acc (clamped at 0) and restart the decay clock.

    Called before every power change, so a donation adds to the power the user currently
    sees instead of first paying off decay that kept accruing while power was at $0.
    """
    now = now or datetime.now(ZoneInfo("UTC"))
    snap.power_acc = current_power_cents(snap, now)
    snap.goal_started_at = now.isoformat()


def compute_ui_state(snap: Snapshot) -> ProgressState:
    # CONTINUOUS power decay since the decay anchor (clamped at 0)
    power_acc_with_decay = current_power_cents(snap)

    power_max_cents = snap.goal_requirement + 100 if snap.goal_requirement > 0 else 100  # +$1
    power_percent = int((power_acc_with_decay * 100) // power_max_cents)
    # Clamp to 100. The old special case capped levels below 11 at 99 %, so a fully charged mech
    # could never show a full bar - but nothing ever read this value: Discord computes its own
    # percentage (docker_control.py) and the web panel does too (config.html). The cap was dead
    # code with a visible-sounding purpose. The 100 % bound stays: a percentage must not exceed it
    # (power can be larger than the bar maximum after a big donation carries surplus over).
    power_percent = min(power_percent, 100)

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
        is_offline=power_acc_with_decay <= 0,  # same decayed value as power_current
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

def apply_donation_units(snap: Snapshot, units_cents: int, *, events: Optional[List[Event]] = None,
                         at: Optional[datetime] = None,
                         goals: Optional[Dict[int, int]] = None) -> Tuple[Snapshot, List[Event], Optional[Event]]:
    """Apply donation units to evo & power; may trigger multiple LevelUpCommitted and ExactHitBonusGranted events.

    ``events``/``at`` select the member count that prices a new level (see
    member_count_for_goal); ``goals`` (rebuild only) reuses the goal the live path fixed
    for a level instead of pricing it again.
    """
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
            current_member_count = member_count_for_goal(snap, events=events, at=at)

            logger.info(f"Level-up: Using {current_member_count} status channel members for dynamic cost calculation")
            set_new_goal_for_next_level(snap, user_count=current_member_count)
            if goals and snap.level in goals:
                snap.goal_requirement = goals[snap.level]
            # Recorded so a rebuild can keep this goal (difficulty is fixed at level start)
            lvl_evt.payload["new_goal_requirement"] = snap.goal_requirement
        else:
            snap.goal_requirement = 0
            break  # Max level reached

        # Update new_evo for next iteration
        new_evo = excess

    # Return list of level-up events and optional bonus event (for last exact hit)
    return snap, level_up_events, bonus_event


MAX_POWER = 10000000  # $100,000 max power
MAX_CUMULATIVE = 100000000  # $1,000,000 max cumulative

# Events that change power; replayed by rebuild_from_events exactly like the live path
POWER_EVENT_TYPES = ("DonationAdded", "SystemDonationAdded", "PowerGiftGranted")


def add_system_power(snap: Snapshot, units_cents: int) -> None:
    """System donation: adds power and counts in the total, never evolution progress."""
    # Validate current state before modifying
    if snap.power_acc < 0:
        logger.error(f"Corrupted power_acc before donation: {snap.power_acc}. Resetting to 0.")
        snap.power_acc = 0

    if snap.cumulative_donations_cents < 0:
        logger.error(f"Corrupted cumulative_donations: {snap.cumulative_donations_cents}. Resetting to 0.")
        snap.cumulative_donations_cents = 0

    # Check for potential overflow BEFORE adding
    if snap.power_acc > MAX_POWER - units_cents:
        logger.warning(f"Power would exceed ${MAX_POWER/100:.2f}. Capping at max.")
        snap.power_acc = MAX_POWER
    else:
        # Add to power ONLY (not evo_acc!)
        snap.power_acc += units_cents

    # Update cumulative with overflow protection
    if snap.cumulative_donations_cents > MAX_CUMULATIVE - units_cents:
        logger.warning(f"Cumulative would exceed ${MAX_CUMULATIVE/100:.2f}. Capping.")
        snap.cumulative_donations_cents = MAX_CUMULATIVE
    else:
        snap.cumulative_donations_cents += units_cents


def apply_power_event(snap: Snapshot, evt: Event, *, events: Optional[List[Event]] = None,
                      goals: Optional[Dict[int, int]] = None) -> Tuple[List[Event], Optional[Event]]:
    """Apply one power-changing event; used by the live path AND rebuild_from_events.

    Decay is settled up to the event time first (the event adds to the power shown at that
    moment), and afterwards power_acc is the power as of the event, also after a level-up.
    Sharing this function keeps a rebuild identical to the live state.
    Returns the LevelUpCommitted events and the ExactHitBonusGranted event (or None).
    """
    at = _event_time(evt.ts)
    if at is not None:
        settle_power_decay(snap, at)
    payload = evt.payload or {}
    lvl_events: List[Event] = []
    bonus_evt: Optional[Event] = None
    if evt.type == "DonationAdded":
        units = int(payload.get("units", 0) or 0)
        snap, lvl_events, bonus_evt = apply_donation_units(snap, units, events=events, at=at, goals=goals)
    elif evt.type == "SystemDonationAdded":
        add_system_power(snap, int(payload.get("power_units", 0) or 0))
    elif evt.type == "PowerGiftGranted":
        snap.power_acc += int(payload.get("power_units", 0) or 0)
    if at is not None:
        # A level-up restarted the clock at "now"; the new power_acc is as of the event
        snap.goal_started_at = at.isoformat()
    return lvl_events, bonus_evt


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
            # Only write when something actually changed. apply_decay_on_demand() is a documented
            # no-op apart from backfilling last_decay_day once - the decay itself is computed in
            # compute_ui_state() from elapsed time. Persisting unconditionally rewrote the
            # snapshot on every READ: measured on the live installation, 3 writes in 70 seconds
            # (two 30 s refresh loops plus every web and Discord access), each a temp file, fsync
            # and rename on the array, for 385 bytes of identical content. A read also had no
            # business failing on a PermissionError. The 30 s decay worker in web_helpers calls
            # exactly this method, so that loop stops rewriting too. tick_decay() below is left
            # unchanged on purpose: it has no caller in production (only tests and the unused
            # adapter wrapper), so its write costs the running system nothing.
            decay_day_before = snap.last_decay_day
            apply_decay_on_demand(snap)
            if snap.last_decay_day != decay_day_before:
                persist_snapshot(snap)
            return compute_ui_state(snap)

    def add_donation(self, amount_dollars: float, donor: Optional[str] = None,
                    channel_id: Optional[str] = None, idempotency_key: Optional[str] = None) -> ProgressState:
        """Add a donation and return updated state"""
        # round(): int() truncated binary floats ($19.99 -> 1998 cents)
        units_cents = int(round(amount_dollars * 100))
        if units_cents <= 0:
            raise ValueError("Donation amount must be positive")

        # Generate idempotency key if not provided
        if idempotency_key is None:
            idempotency_key = hashlib.sha256(
                f"{self.mech_id}|{donor}|{amount_dollars}|{datetime.utcnow().isoformat()}".encode()
            ).hexdigest()[:16]

        with LOCK:
            # Check idempotency
            all_events = read_events()
            existing = [e for e in all_events
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
            # Settles decay first: the donation adds to the CURRENT (decayed, clamped) power
            lvl_events, bonus_evt = apply_power_event(snap, evt, events=all_events)

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
                # Settles decay first, then adds to power ONLY (not evolution), capped
                apply_power_event(snap, evt)

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

            # Use the CURRENT (decayed) power: raw power_acc stays > 0 while decay runs
            if current_power_cents(snap) > 0:
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

            # Power is 0 here: fold any decay debt and restart the decay clock before adding
            apply_power_event(snap, evt)
            snap.version += 1
            snap.last_event_seq = evt.seq
            persist_snapshot(snap)

            gift_dollars = gift_cents / 100.0
            logger.info(f"Power gift granted: ${gift_dollars:.2f}")
            return compute_ui_state(snap), gift_dollars

    def rebuild_from_events(self) -> ProgressState:
        """
        Rebuild snapshot from scratch by replaying all events CHRONOLOGICALLY.

        The replay gives the same state as the live path (an admin delete/restore must not
        shift the displayed power):
        1. Events in timestamp order; deleted events (DonationDeleted toggles) are skipped
        2. Power events go through apply_power_event, like the live path: decay is settled
           up to the event time, then the donation / system donation / gift is applied
           (level-ups and the exact-hit bonus happen inside the donation)
        3. ExactHitBonusGranted / LevelUpCommitted only record what a donation did; a
           deleted bonus event removes the bonus from its donation
        4. Level goals are reused from the events and the current snapshot instead of
           being priced again with today's member count and difficulty
        """
        with LOCK:
            # Read all events for this mech
            events, damaged_lines = read_events(count_damaged=True)
            all_events = [e for e in events if e.mech_id == self.mech_id]

            if damaged_lines:
                # A rebuild REPLACES the snapshot. With lines missing from the log the replay
                # is incomplete (level, power and totals would silently drop), so keep the
                # existing snapshot and let the caller work with it.
                logger.error(
                    f"Refusing to rebuild {self.mech_id} from a damaged event log: "
                    f"{damaged_lines} unreadable line(s) in {EVENT_LOG.name}. Keeping the "
                    f"current snapshot; repair or restore {EVENT_LOG.name} first."
                )
                # Read the snapshot file directly: load_snapshot() would pull in the whole
                # config/recovery path, and the caller only needs the current state.
                path = snapshot_path(self.mech_id)
                snap = Snapshot(mech_id=self.mech_id)
                if path.exists():
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            snap = Snapshot.from_json(json.load(f))
                    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                        logger.error(f"Snapshot for {self.mech_id} is unreadable as well ({e})")
                _ensure_decay_anchor(snap)
                return compute_ui_state(snap)

            # Calculate deleted_seqs using toggle pattern:
            # Each DonationDeleted with the same deleted_seq toggles the state.
            # Odd count = deleted, even count = active/restored.
            deletion_counts: dict[int, int] = {}
            for evt in all_events:
                if evt.type == "DonationDeleted":
                    payload = evt.payload or {}
                    deleted_seq = payload.get("deleted_seq")
                    if deleted_seq:
                        deletion_counts[deleted_seq] = deletion_counts.get(deleted_seq, 0) + 1

            deleted_seqs = set()
            for seq, count in deletion_counts.items():
                if count % 2 == 1:  # odd = currently deleted
                    deleted_seqs.add(seq)
                    logger.info(f"Marking event seq {seq} as deleted (toggle count: {count})")
                else:
                    logger.info(f"Event seq {seq} restored (toggle count: {count})")

            ordered = sorted(all_events, key=lambda e: e.ts)
            goals, previous = self._recorded_goals(ordered)

            # Create fresh snapshot at Level 1
            snap = Snapshot(mech_id=self.mech_id)
            set_new_goal_for_next_level(snap, user_count=0)
            if 1 in goals:
                snap.goal_requirement = goals[1]
            snap.last_decay_day = today_local_str()

            last_time: Optional[datetime] = None  # last event time (anchor if power never changed)
            anchored = False  # a power event set the decay anchor
            last_bonus = 0  # exact-hit bonus granted by the last replayed power event
            member_events: List[Event] = []  # member count samples replayed so far
            last_seq = 0
            for evt in ordered:
                last_seq = max(last_seq, evt.seq)
                payload = evt.payload or {}

                if evt.seq in deleted_seqs:
                    if evt.type == "ExactHitBonusGranted" and last_bonus:
                        # Deleted bonus: its donation is replayed without the bonus
                        snap.power_acc = max(0, snap.power_acc - last_bonus)
                    if evt.type in POWER_EVENT_TYPES or evt.type == "ExactHitBonusGranted":
                        # The bonus only ever belongs to the power event right before it. A
                        # skipped power event leaves no bonus to remove - keeping the previous
                        # value would subtract an unrelated, earlier bonus when a donation and
                        # its bonus are both deleted (V2 review B3).
                        last_bonus = 0
                    continue

                last_time = _event_time(evt.ts) or last_time

                if evt.type == "MemberCountUpdated":
                    snap.last_user_count_sample = max(0, int(payload.get("member_count", 0) or 0))
                    member_events.append(evt)
                elif evt.type in POWER_EVENT_TYPES:
                    _, bonus_evt = apply_power_event(snap, evt, events=member_events, goals=goals)
                    last_bonus = int(bonus_evt.payload.get("power_units", 0)) if bonus_evt else 0
                    anchored = anchored or _event_time(evt.ts) is not None
                    logger.debug(f"Applied {evt.type} seq {evt.seq} (power: ${snap.power_acc/100:.2f}, "
                                 f"evo: ${snap.evo_acc/100:.2f}, level: {snap.level})")
                # DonationDeleted, LevelUpCommitted, ExactHitBonusGranted: nothing to replay

            if not anchored:
                # Power never changed (it is 0): start the decay clock at the last event
                snap.goal_started_at = last_time.isoformat() if last_time else now_utc_iso()
            if previous is not None and previous.level == snap.level:
                # Same level as before: keep its difficulty (may have been re-priced at startup)
                snap.difficulty_bin = previous.difficulty_bin

            # Update snapshot metadata
            snap.version += 1
            snap.last_event_seq = last_seq
            persist_snapshot(snap)

            logger.info(f"Rebuilt snapshot from {len(all_events)} events "
                       f"(skipped {len(deleted_seqs)} deleted, final: power=${snap.power_acc/100:.2f}, "
                       f"evo=${snap.evo_acc/100:.2f}, level={snap.level})")

            return compute_ui_state(snap)

    def _recorded_goals(self, ordered_events: List[Event]) -> Tuple[Dict[int, int], Optional[Snapshot]]:
        """Goals the live path fixed per level, plus the current snapshot (None if unreadable).

        Difficulty is fixed when a level starts (member count, difficulty mode), so a replay
        must not price past levels again with today's values. LevelUpCommitted records the
        goal it completed (and the next goal since this release); the current snapshot holds
        the goal of the level in progress, including a re-price by the startup step.
        """
        goals: Dict[int, int] = {}
        for evt in ordered_events:
            if evt.type != "LevelUpCommitted":
                continue
            payload = evt.payload or {}
            for level_key, goal_key in (("from_level", "old_goal_requirement"),
                                        ("to_level", "new_goal_requirement")):
                level, goal = payload.get(level_key), _positive_int(payload.get(goal_key))
                if isinstance(level, int) and 1 <= level <= 10 and goal is not None:
                    goals[level] = goal

        previous: Optional[Snapshot] = None
        try:
            with open(snapshot_path(self.mech_id), "r", encoding="utf-8") as f:
                previous = Snapshot.from_json(json.load(f))
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
            previous = None
        if previous is not None and isinstance(previous.level, int) and 1 <= previous.level <= 10:
            goal = _positive_int(previous.goal_requirement)
            if goal is not None:
                goals[previous.level] = goal
        return goals, previous

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

            # Check current deletion state (toggle pattern: odd count = deleted, even = active)
            deletion_count = sum(1 for e in all_events
                                if e.type == "DonationDeleted"
                                and e.payload.get("deleted_seq") == donation_seq)
            currently_deleted = deletion_count % 2 == 1

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

            # Create DonationDeleted compensation event (toggle: delete or restore)
            reason = "admin_restore" if currently_deleted else "admin_deletion"
            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="DonationDeleted",
                mech_id=self.mech_id,
                payload={
                    "deleted_seq": donation_seq,
                    "donor": donor,
                    "units": units,
                    "reason": reason,
                    "original_type": donation_event.type  # Track original event type
                }
            )
            append_event(evt)

            action = "restored" if currently_deleted else "deleted"
            logger.info(f"Donation {action} event added for seq {donation_seq} "
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
