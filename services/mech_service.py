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
#   - Fuel rules per spec (fresh level = 1 + overshoot)
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
            # Try to migrate from old donation.json format
            old_donation_file = self.path.parent / "donation.json"
            if old_donation_file.exists():
                return self._migrate_from_old_format(old_donation_file)
            return {"donations": []}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return {"donations": []}
        if "donations" not in data or not isinstance(data["donations"], list):
            data["donations"] = []
        return data
    
    def _migrate_from_old_format(self, old_file: Path) -> Dict[str, Any]:
        """Migrate from old donation.json format to new format"""
        try:
            with old_file.open("r", encoding="utf-8") as f:
                old_data = json.load(f)
            
            # Extract total donations from old format
            fuel_data = old_data.get('fuel_data', {})
            total_donations = fuel_data.get('total_received_permanent', 0.0)
            
            if total_donations > 0:
                # Create migration entry with current timestamp
                migration_donation = {
                    "username": "MIGRATION_FROM_OLD_SYSTEM", 
                    "amount": int(total_donations),
                    "ts": datetime.now().isoformat()
                }
                
                # Save to new format (this will create the file)
                new_data = {"donations": [migration_donation]}
                try:
                    self.save(new_data)
                    print(f"✅ AUTO-MIGRATED: ${total_donations} from old donation system")
                except:
                    print(f"⚠️ Could not save migration, using in-memory data")
                
                return new_data
            else:
                return {"donations": []}
                
        except Exception as e:
            print(f"⚠️ Migration failed: {e}")
            return {"donations": []}

    def save(self, data: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)


# ---------------------------
#   Public State DTOs
# ---------------------------

@dataclass(frozen=True)
class MechBars:
    mech_progress_current: int
    mech_progress_max: int
    fuel_current: int
    fuel_max_for_level: int


@dataclass(frozen=True)
class MechState:
    total_donated: int
    level: int
    level_name: str
    next_level_threshold: Optional[int]  # None when at MAX
    fuel: int
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
    - Fuel increases by donation dollars.
    - On level-up, Fuel resets to 1 plus overshoot beyond the new level threshold.
    - Fuel decays continuously: 1 fuel per 86400 seconds (second-accurate).
    - Bars:
        * Mech progress: 0..Δ (Δ = distance to next level)
        * Fuel bar: 0..(Δ + 1) (fresh level = 1); at MAX level 0..100
    - glvl mapping:
        * If Δ ≤ 100: glvl = fuel, capped at (Δ - 1)
        * If Δ > 100: linear mapping fuel → 0..100 over (Δ + 1)
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
        fuel: float = 0.0  # internal float to support fractional decay
        lvl: MechLevel = MECH_LEVELS[0]
        last_ts: Optional[datetime] = None
        last_evolution_ts: Optional[datetime] = None

        for d in donations:
            ts = self._parse_iso(d["ts"])
            if last_ts is not None:
                fuel = max(0.0, fuel - self._decay_amount(last_ts, ts))
            last_ts = ts

            amount = int(d["amount"])
            total += amount
            fuel += amount

            # Handle (possibly multi-step) level-ups in one donation
            while True:
                nxt = _next_level(lvl)
                if not nxt:
                    break
                if total >= nxt.threshold:
                    lvl = nxt
                    # fresh level starts with 1 + overshoot beyond this level's threshold
                    fuel = 1.0 + max(0, total - lvl.threshold)
                    last_evolution_ts = ts  # Track when evolution occurred
                    continue
                break

        # decay from last donation to "now" - but only if enough time passed since evolution
        if last_ts is not None:
            # If evolution just happened, don't apply immediate decay
            if last_evolution_ts == last_ts:
                # Evolution just occurred - no decay yet, mech has fresh fuel
                pass
            else:
                # Normal decay from last donation
                fuel = max(0.0, fuel - self._decay_amount(last_ts, now))

        # Compose bars & glvl
        nxt = _next_level(lvl)
        delta = _stage_delta(lvl)  # may be None at MAX
        progress_current = 0 if delta is None else max(0, total - lvl.threshold)
        progress_max = 0 if delta is None else delta

        # Fuel bar max
        if delta is None:
            fuel_max = 100
        else:
            fuel_max = delta + 1  # "+1" rule

        # glvl mapping
        if delta is None:
            glvl_max = 100
            glvl = min(glvl_max, int(math.floor(fuel)))
        elif delta <= 100:
            glvl_max = max(0, delta - 1)
            glvl = min(glvl_max, int(math.floor(fuel)))
        else:
            glvl_max = 100
            glvl = int(math.floor((fuel * 100) / (delta + 1)))
            if glvl > glvl_max:
                glvl = glvl_max

        bars = MechBars(
            mech_progress_current=int(progress_current),
            mech_progress_max=int(progress_max),
            fuel_current=int(max(0, math.floor(fuel))),
            fuel_max_for_level=int(fuel_max),
        )

        return MechState(
            total_donated=int(total),
            level=lvl.level,
            level_name=lvl.name,
            next_level_threshold=None if not nxt else nxt.threshold,
            fuel=int(max(0, math.floor(fuel))),
            glvl=int(glvl),
            glvl_max=int(glvl_max),
            bars=bars,
        )

    # -------- Helpers --------

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _parse_iso(self, s: str) -> datetime:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=self.tz)

    def _decay_amount(self, a: datetime, b: datetime) -> float:
        """Fuel consumption between a→b, always rolling (second-accurate)."""
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