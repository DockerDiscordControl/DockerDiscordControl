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
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import logging

logger = logging.getLogger('ddc.progress_service')

# ---------------------
# Config & Constants
# ---------------------
DATA_DIR = Path("config/progress")
EVENT_LOG = DATA_DIR / "events.jsonl"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
CONFIG_FILE = DATA_DIR / "config.json"
LOCK = threading.RLock()  # coarse-grained FS lock to avoid races

DEFAULT_CONFIG = {
    "timezone": "Europe/Zurich",
    # 21 bins (1..21). Values are inclusive lower bounds of concurrent users
    "difficulty_bins": [
        0, 25, 50, 100, 150, 200, 300, 400, 500, 750,
        1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 7500, 10000
    ],
    # requirement per bin index (1-based) in integer units
    "bin_to_requirement": {
        str(i): v for i, v in enumerate([
            None, 400, 900, 1800, 3100, 4900, 7200, 9900, 13000, 16600,
            20700, 25300, 30400, 36000, 42100, 48700, 55800, 63400, 71500, 80100, 89200, 99000
        ]) if i
    },
    # decay per day by mech_type (or default) - in cents
    "mech_power_decay_per_day": {
        "default": 100  # $1 per day
    },
}

# Ensure data paths
DATA_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
if not EVENT_LOG.exists():
    EVENT_LOG.touch()
if not CONFIG_FILE.exists():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)


def load_config() -> Dict[str, Any]:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()
TZ = ZoneInfo(CFG.get("timezone", "Europe/Zurich"))

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
    with open(EVENT_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            evts.append(Event(**raw))
    return evts


def append_event(evt: Event) -> None:
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt.to_json(), separators=(",", ":")) + "\n")


def next_seq() -> int:
    tail_file = DATA_DIR / "last_seq.txt"
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
        with open(p, "r", encoding="utf-8") as f:
            return Snapshot.from_json(json.load(f))
    # First-time snapshot → initialize goal for level 1
    snap = Snapshot(mech_id=mech_id)
    set_new_goal_for_next_level(snap, user_count=0)
    snap.last_decay_day = today_local_str()
    persist_snapshot(snap)
    return snap


def persist_snapshot(snap: Snapshot) -> None:
    p = snapshot_path(snap.mech_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snap.to_json(), f, indent=2)


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
    return int(CFG["bin_to_requirement"][str(b)])


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
    today_s = today_local_str()
    if not snap.last_decay_day:
        snap.last_decay_day = today_s
        return
    last = date.fromisoformat(snap.last_decay_day)
    today_d = date.fromisoformat(today_s)
    days = (today_d - last).days
    if days <= 0:
        return
    dpp = decay_per_day(snap.mech_type)
    total = days * dpp
    snap.power_acc = max(0, snap.power_acc - total)
    snap.last_decay_day = today_s
    logger.info(f"Applied {days} days decay ({total} cents) to mech {snap.mech_id}")


def set_new_goal_for_next_level(snap: Snapshot, user_count: int) -> None:
    b = current_bin(user_count)
    req = requirement_for_bin(b)
    snap.difficulty_bin = b
    snap.goal_requirement = req
    snap.goal_started_at = now_utc_iso()
    snap.power_decay_per_day = decay_per_day(snap.mech_type)
    snap.last_user_count_sample = user_count
    logger.info(f"Set new goal for mech {snap.mech_id}: Level {snap.level} -> {snap.level + 1}, requirement={req} cents (bin={b}, users={user_count})")


def compute_ui_state(snap: Snapshot) -> ProgressState:
    power_max_cents = snap.goal_requirement + 100 if snap.goal_requirement > 0 else 100  # +$1
    power_percent = int((snap.power_acc * 100) // power_max_cents)
    power_percent = min(power_percent, 99 if snap.level < 11 else 100)

    evo_percent = 100 if snap.goal_requirement == 0 else int((snap.evo_acc * 100) // snap.goal_requirement)
    evo_percent = min(evo_percent, 100)

    # Use cumulative donations for total
    total_cents = snap.cumulative_donations_cents

    return ProgressState(
        level=snap.level,
        power_current=snap.power_acc / 100.0,
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

def apply_donation_units(snap: Snapshot, units_cents: int) -> Tuple[Snapshot, Optional[Event]]:
    """Apply donation units to evo & power; may trigger a LevelUpCommitted event."""
    # Track cumulative donations
    snap.cumulative_donations_cents += units_cents

    if snap.level >= 11:
        snap.power_acc += units_cents
        return snap, None

    new_evo = snap.evo_acc + units_cents
    snap.power_acc += units_cents

    if new_evo < snap.goal_requirement:
        snap.evo_acc = new_evo
        return snap, None

    # Commit level-up
    exact_hit = (new_evo == snap.goal_requirement)
    lvl_from = snap.level
    snap.level = min(snap.level + 1, 11)
    snap.evo_acc = 0
    snap.power_acc = 100 if exact_hit else 0  # $1 if exact hit

    logger.info(f"Level up! Mech {snap.mech_id}: {lvl_from} -> {snap.level} (exact_hit={exact_hit})")

    lvl_evt = Event(
        seq=0,
        ts=now_utc_iso(),
        type="LevelUpCommitted",
        mech_id=snap.mech_id,
        payload={
            "from_level": lvl_from,
            "to_level": snap.level,
            "old_goal_requirement": snap.goal_requirement,
            "exact_hit": exact_hit,
        },
    )

    if snap.level < 11:
        set_new_goal_for_next_level(snap, user_count=snap.last_user_count_sample)
    else:
        snap.goal_requirement = 0

    return snap, lvl_evt


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
            snap, lvl_evt = apply_donation_units(snap, units_cents)

            # Append level-up event if triggered
            if lvl_evt is not None:
                lvl_evt.seq = next_seq()
                append_event(lvl_evt)

            snap.version += 1
            snap.last_event_seq = evt.seq
            persist_snapshot(snap)

            logger.info(f"Donation added: ${amount_dollars:.2f} from {donor} (id={donation_id})")
            return compute_ui_state(snap)

    def update_member_count(self, member_count: int) -> None:
        """Update member count for difficulty calculation"""
        with LOCK:
            snap = load_snapshot(self.mech_id)
            snap.last_user_count_sample = max(0, member_count)
            persist_snapshot(snap)
            logger.info(f"Updated member count to {member_count}")

    def tick_decay(self) -> ProgressState:
        """Manually trigger decay check (useful for testing/cron)"""
        with LOCK:
            snap = load_snapshot(self.mech_id)
            apply_decay_on_demand(snap)
            persist_snapshot(snap)
            return compute_ui_state(snap)

    def monthly_gift(self, campaign_id: str) -> Tuple[ProgressState, Optional[int]]:
        """Grant monthly gift if power is 0. Returns (state, gift_dollars or None)"""
        with LOCK:
            snap = load_snapshot(self.mech_id)
            apply_decay_on_demand(snap)

            if snap.power_acc > 0:
                logger.info(f"Monthly gift skipped: power > 0")
                persist_snapshot(snap)
                return compute_ui_state(snap), None

            gift_cents = deterministic_gift_1_3(self.mech_id, campaign_id)

            evt = Event(
                seq=next_seq(),
                ts=now_utc_iso(),
                type="MonthlyGiftGranted",
                mech_id=self.mech_id,
                payload={"campaign_id": campaign_id, "power_units": gift_cents},
            )
            append_event(evt)

            snap.power_acc += gift_cents
            snap.version += 1
            snap.last_event_seq = evt.seq
            persist_snapshot(snap)

            gift_dollars = gift_cents / 100.0
            logger.info(f"Monthly gift granted: ${gift_dollars:.2f}")
            return compute_ui_state(snap), gift_dollars


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
