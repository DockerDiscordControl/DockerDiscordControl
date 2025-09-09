from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Optional, Dict, Any
import json
import math

# =============================================================
#   DDC Mech Service (instance-wide)
#   - Single donation pool per DDC instance (no guild dimension)
#   - JSON persistence
#   - Level thresholds per spec
#   - Power rules per spec (fresh level = 1 + overshoot)
#   - Decay always second-accurate (rolling)
#   - Clean DTOs for UI (progress bars, glvl mapping)
# =============================================================

# ---------------------------
#   Domain: Levels & Names
# ---------------------------

@dataclass(frozen=True)
class MechLevel:
    level: int
    name: str
    threshold: int  # cumulative dollars required to START this level


MECH_LEVELS: List[MechLevel] = [
    MechLevel(1,  "SCRAP MECH",    0),
    MechLevel(2,  "REPAIRED MECH", 20),
    MechLevel(3,  "STANDARD MECH", 50),
    MechLevel(4,  "ENHANCED MECH", 100),
    MechLevel(5,  "ADVANCED MECH", 200),
    MechLevel(6,  "ELITE MECH",    400),
    MechLevel(7,  "CYBER MECH",    800),
    MechLevel(8,  "PLASMA MECH",   1500),
    MechLevel(9,  "QUANTUM MECH",  2500),
    MechLevel(10, "DIVINE MECH",   4000),
    MechLevel(11, "OMEGA MECH",    10000),
]


def _next_level(curr: MechLevel) -> Optional[MechLevel]:
    try:
        return MECH_LEVELS[curr.level]  # 1-based levels vs 0-based list
    except IndexError:
        return None


def _stage_delta(curr: MechLevel) -> Optional[int]:
    nxt = _next_level(curr)
    return None if not nxt else (nxt.threshold - curr.threshold)


# ---------------------------
#   Persistence
# ---------------------------

class _Store:
    """Tiny JSON store. Atomic writes; schema:
    {
      "donations": [
         {"username": "...", "amount": 25, "ts": "2025-08-24T18:00:00+02:00"}
      ]
    }
    """
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"donations": []}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return {"donations": []}
        if "donations" not in data or not isinstance(data["donations"], list):
            data["donations"] = []
        return data

    def save(self, data: Dict[str, Any]) -> None:
        try:
            # Try atomic write with temp file
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
        except PermissionError:
            # Fallback: direct write (less safe but works with restricted permissions)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------
#   Public State DTOs
# ---------------------------

@dataclass(frozen=True)
class MechBars:
    mech_progress_current: int
    mech_progress_max: int
    Power_current: int
    Power_max_for_level: int


@dataclass(frozen=True)
class MechState:
    total_donated: int
    level: int
    level_name: str
    next_level_threshold: Optional[int]  # None when at MAX
    Power: int
    glvl: int
    glvl_max: int
    bars: MechBars


# ---------------------------
#   Core Service
# ---------------------------

class MechService:
    """Instance-wide black-box for DDC.

    Rules:
    - Donations persist in JSON (username, amount, timestamp).
    - Mech level from cumulative donations.
    - Power increases by donation dollars.
    - On level-up, Power resets to 1 plus overshoot beyond the new level threshold.
    - Power decays continuously: 1 Power per 86400 seconds (second-accurate).
    - Bars:
        * Mech progress: 0..Δ (Δ = distance to next level)
        * Power bar: 0..(Δ + 1) (fresh level = 1); at MAX level 0..100
    - glvl mapping:
        * If Δ ≤ 100: glvl = Power, capped at (Δ - 1)
        * If Δ > 100: linear mapping Power → 0..100 over (Δ + 1)
    """

    def __init__(self, json_path: str | Path, tz: str = "Europe/Zurich") -> None:
        self.store = _Store(Path(json_path))
        self.tz = ZoneInfo(tz)

    # -------- Public API --------

    def add_donation(self, username: str, amount: int, ts_iso: Optional[str] = None) -> MechState:
        """Persist a donation and return the fresh state."""
        if amount <= 0:
            raise ValueError("amount must be a positive integer number of dollars")

        ts = self._now() if ts_iso is None else self._parse_iso(ts_iso)
        data = self.store.load()
        data.setdefault("donations", [])
        data["donations"].append({
            "username": username,
            "amount": int(amount),
            "ts": ts.isoformat(),
        })
        self.store.save(data)
        return self.get_state(now_iso=ts.isoformat())

    def get_state(self, now_iso: Optional[str] = None) -> MechState:
        """Compute the live state from persisted donations."""
        now = self._now() if now_iso is None else self._parse_iso(now_iso)
        donations = list(self.store.load().get("donations", []))
        donations.sort(key=lambda d: d["ts"])  # chronological

        total: int = 0
        Power: float = 0.0  # internal float to support fractional decay
        lvl: MechLevel = MECH_LEVELS[0]
        last_ts: Optional[datetime] = None
        last_evolution_ts: Optional[datetime] = None

        for d in donations:
            ts = self._parse_iso(d["ts"])
            if last_ts is not None:
                Power = max(0.0, Power - self._decay_amount(last_ts, ts))
            last_ts = ts

            amount = int(d["amount"])
            total += amount
            Power += amount

            # Handle (possibly multi-step) level-ups in one donation
            while True:
                nxt = _next_level(lvl)
                if not nxt:
                    break
                if total >= nxt.threshold:
                    lvl = nxt
                    # fresh level starts with 1 + overshoot beyond this level's threshold
                    Power = 1.0 + max(0, total - lvl.threshold)
                    last_evolution_ts = ts  # Track when evolution occurred
                    continue
                break

        # decay from last donation to "now" - but only if enough time passed since evolution
        if last_ts is not None:
            # If evolution just happened, don't apply immediate decay
            if last_evolution_ts == last_ts:
                # Evolution just occurred - no decay yet, mech has fresh Power
                pass
            else:
                # Normal decay from last donation
                Power = max(0.0, Power - self._decay_amount(last_ts, now))

        # Compose bars & glvl
        nxt = _next_level(lvl)
        delta = _stage_delta(lvl)  # may be None at MAX
        progress_current = 0 if delta is None else max(0, total - lvl.threshold)
        progress_max = 0 if delta is None else delta

        # Power bar max - Level 1 starts at 0, Level 2+ starts at 1 + overshoot
        if delta is None:
            Power_max = 100
        elif lvl.level == 1:
            Power_max = delta  # Level 1 starts at 0, so max = delta
        else:
            Power_max = delta + 1  # Level 2+ starts at 1 + overshoot, so max = delta + 1

        # glvl mapping - consistent with Power_max calculation
        if delta is None:
            glvl_max = 100
            glvl = min(glvl_max, int(math.floor(Power)))
        elif delta <= 100:
            if lvl.level == 1:
                glvl_max = delta  # Level 1: full delta range
                glvl = min(glvl_max, int(math.floor(Power)))
            else:
                glvl_max = max(0, delta - 1)  # Level 2+: delta-1 to account for +1 start
                glvl = min(glvl_max, int(math.floor(Power)))
        else:
            glvl_max = 100
            if lvl.level == 1:
                glvl = int(math.floor((Power * 100) / delta))  # Level 1: simple mapping
            else:
                glvl = int(math.floor((Power * 100) / (delta + 1)))  # Level 2+: account for +1
            if glvl > glvl_max:
                glvl = glvl_max

        bars = MechBars(
            mech_progress_current=int(progress_current),
            mech_progress_max=int(progress_max),
            Power_current=int(max(0, math.floor(Power))),
            Power_max_for_level=int(Power_max),
        )

        return MechState(
            total_donated=int(total),
            level=lvl.level,
            level_name=lvl.name,
            next_level_threshold=None if not nxt else nxt.threshold,
            Power=int(max(0, math.floor(Power))),
            glvl=int(glvl),
            glvl_max=int(glvl_max),
            bars=bars,
        )

    def get_power_with_decimals(self) -> float:
        """Get raw Power value with decimal places for Web UI display"""
        data = self.store.load()
        donations = data["donations"]
        
        total = 0.0
        Power = 0.0
        lvl = MECH_LEVELS[0]  # Start at level 1
        now = self._now()
        last_ts = None
        last_evolution_ts = None

        for d in donations:
            ts = self._parse_iso(d["ts"])
            
            # Apply decay from last donation to current donation
            if last_ts is not None:
                Power = max(0.0, Power - self._decay_amount(last_ts, ts))
            last_ts = ts

            amount = int(d["amount"])
            total += amount
            Power += amount

            # Handle level-ups
            while True:
                nxt = _next_level(lvl)
                if not nxt:
                    break
                if total >= nxt.threshold:
                    lvl = nxt
                    Power = 1.0 + max(0, total - lvl.threshold)
                    last_evolution_ts = ts
                    continue
                break

        # Final decay from last donation to now
        if last_ts is not None:
            if last_evolution_ts == last_ts:
                pass  # No decay if evolution just occurred
            else:
                Power = max(0.0, Power - self._decay_amount(last_ts, now))

        return Power  # Return raw float with decimals

    # -------- Helpers --------

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _parse_iso(self, s: str) -> datetime:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=self.tz)

    def _decay_amount(self, a: datetime, b: datetime) -> float:
        """Power consumption between a→b, always rolling (second-accurate)."""
        sec = (b.astimezone(self.tz) - a.astimezone(self.tz)).total_seconds()
        return max(0.0, sec / 86400.0)


# ---------------------------
#   Singleton Factory
# ---------------------------

_mech_service_instance: Optional[MechService] = None

def get_mech_service() -> MechService:
    """Get or create the singleton MechService instance."""
    global _mech_service_instance
    if _mech_service_instance is None:
        _mech_service_instance = MechService("config/mech_donations.json")
    return _mech_service_instance


__all__ = [
    "MechService", 
    "MechState",
    "MechBars", 
    "MechLevel",
    "MECH_LEVELS",
    "get_mech_service",
]