# -*- coding: utf-8 -*-
"""A donation never takes energy off the mech.

THE FINDING (independent review, 2026-09-23): the battery lid cuts power down
to the level's goal on every power event. Power can legitimately sit ABOVE
that goal - the goal is re-priced when the member count changes
(app/bot/startup_steps/member_count.py writes the new goal and does not touch
power), so a mech charged at $59 can find itself with a $25 battery.

The next donation then does this: add $1, then cut to $25. The donor gave a
dollar and the mech lost $35, with nothing said to anyone.

The lid is a lid, not a drain: a donation fills up to the capacity and stops.
It never lowers what is already there.

COUNTER-CHECK (2026-09-23): red before - $59 plus a $1 donation came out as
$25. The second test keeps the lid itself: a donation into a battery with room
still stops at the top.
"""

import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def module(tmp_path, monkeypatch):
    from services.mech.progress import reset_progress_runtime
    from services.mech.progress_paths import clear_progress_paths_cache

    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    progress_service = importlib.reload(
        importlib.import_module("services.mech.progress_service"))
    importlib.reload(importlib.import_module("services.mech.gifts"))
    progress_service.reset_progress_services()
    config = {
        "timezone": "UTC",
        "difficulty_bins": [0, 50],
        "level_base_costs": {str(level): 100000 for level in range(1, 12)},
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }
    progress_service.runtime.configure_defaults(config)
    progress_service.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    progress_service.CFG = progress_service.runtime.load_config(refresh=True)
    progress_service.TZ = progress_service.runtime.timezone(refresh=True)
    monkeypatch.setattr(progress_service, "get_decay_config_data", lambda: {"default": 0})
    yield progress_service
    reset_progress_runtime()
    clear_progress_paths_cache()
    importlib.reload(importlib.import_module("services.mech.progress_service"))
    importlib.reload(importlib.import_module("services.mech.gifts"))


def _donate(module, snap, dollars):
    event = module.Event(seq=1, ts=module.now_utc_iso(), type="DonationAdded",
                         mech_id="main", payload={"units": int(dollars * 100)})
    module.apply_power_event(snap, event)
    return snap


def test_a_dollar_does_not_cost_the_mech_thirty_five(module):
    """The goal was re-priced downward while the battery was full."""
    snap = module.Snapshot(mech_id="main", level=3, evo_acc=0, power_acc=5900,
                           goal_requirement=2500, difficulty_bin=1,
                           goal_started_at=module.now_utc_iso(), power_decay_per_day=0)

    _donate(module, snap, 1.0)

    assert snap.power_acc == 5900, (
        f"a $1 donation left the mech with {snap.power_acc} cents where it had 5900")


def test_the_lid_still_stops_an_overfill(module):
    """Counter-check: with room in the battery, the donation fills it and stops."""
    snap = module.Snapshot(mech_id="main", level=3, evo_acc=0, power_acc=2000,
                           goal_requirement=2500, difficulty_bin=1,
                           goal_started_at=module.now_utc_iso(), power_decay_per_day=0)

    _donate(module, snap, 10.0)

    assert snap.power_acc == 2500, f"the battery holds 2500 and took {snap.power_acc}"


def test_the_evolution_account_is_untouched_by_the_lid(module):
    """Counter-check: what does not fit in the battery still counts for the climb."""
    snap = module.Snapshot(mech_id="main", level=3, evo_acc=0, power_acc=5900,
                           goal_requirement=2500, difficulty_bin=1,
                           goal_started_at=module.now_utc_iso(), power_decay_per_day=0)

    _donate(module, snap, 1.0)

    assert snap.evo_acc == 100
    assert snap.cumulative_donations_cents == 100


def test_the_decay_is_not_refilled_by_the_lid(module, monkeypatch):
    """The comparison is what the mech has NOW, not what it had before the decay.

    COUNTER-CHECK: taken against the pre-decay value, a donation into an
    over-full battery would hand back the energy the decay had just taken.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(module, "get_decay_config_data", lambda: {"default": 1000})
    two_days_ago = (datetime.now(ZoneInfo("UTC")) - timedelta(days=2)).isoformat()
    snap = module.Snapshot(mech_id="main", level=3, evo_acc=0, power_acc=5900,
                           goal_requirement=2500, difficulty_bin=1,
                           goal_started_at=two_days_ago, power_decay_per_day=1000)

    _donate(module, snap, 1.0)

    # 5900 - 2000 decay = 3900, still above the 2500 capacity: the dollar does
    # not fit, and the decay stays taken.
    assert snap.power_acc == 3900, snap.power_acc
