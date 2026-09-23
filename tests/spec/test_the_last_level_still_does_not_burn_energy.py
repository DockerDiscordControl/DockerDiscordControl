# -*- coding: utf-8 -*-
"""The final level consumes what its table says - nothing.

THE FINDING (independent review of today's energy rework, 2026-09-23): a
REGRESSION introduced by freezing the decay rate in the snapshot.

decay.json gives level 11 a rate of 0 - the OMEGA MECH does not burn energy;
that is what the last level is. The frozen rate is refreshed in two places:
settle_power_decay (which runs BEFORE the donation is applied, so it writes
level 10's rate) and set_new_goal_for_next_level (which the 10 -> 11 climb
never reaches - that branch sets goal_requirement = 0 and breaks).

So a mech that reaches level 11 keeps level 10's 200 cents a day for ever:
$40 of energy, offline after twenty days, animation "rest", speed 0 - until
someone donates again and the settle finally writes the 0.

Before today current_power_cents asked decay_per_day(11) every time and the
mech never decayed.

COUNTER-CHECK (2026-09-23): red before - the snapshot carried 200 after the
climb and the mech lost $2.00 a day.
"""

import importlib
import json
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture
def module(tmp_path, monkeypatch):
    """progress_service with the SHIPPED decay table and cheap levels."""
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
        "level_base_costs": {str(level): 100 for level in range(1, 12)},
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }
    progress_service.runtime.configure_defaults(config)
    progress_service.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    progress_service.CFG = progress_service.runtime.load_config(refresh=True)
    progress_service.TZ = progress_service.runtime.timezone(refresh=True)

    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module, "get_config_service",
        lambda: SimpleNamespace(
            get_evolution_mode_service=lambda request: config_module.GetEvolutionModeResult(
                success=True, use_dynamic=True, difficulty_multiplier=1.0)),
        raising=False)
    # The shipped table: level 10 burns 200 cents a day, level 11 burns nothing
    monkeypatch.setattr(progress_service, "get_decay_config_data",
                        lambda: {"default": 100, "levels": {"10": 200, "11": 0}})
    yield progress_service
    reset_progress_runtime()
    clear_progress_paths_cache()
    importlib.reload(importlib.import_module("services.mech.progress_service"))
    importlib.reload(importlib.import_module("services.mech.gifts"))


def _climb_to_eleven(module):
    """A mech one donation away from the final level."""
    snap = module.Snapshot(mech_id="main", level=10, evo_acc=0, power_acc=4000,
                           goal_requirement=100, difficulty_bin=1,
                           goal_started_at=module.now_utc_iso(),
                           power_decay_per_day=200)
    event = module.Event(seq=1, ts=module.now_utc_iso(), type="DonationAdded",
                         mech_id="main", payload={"units": 100})
    module.apply_power_event(snap, event)
    return snap


def test_the_final_level_keeps_its_rate_of_nothing(module):
    snap = _climb_to_eleven(module)

    assert snap.level == 11
    assert snap.power_decay_per_day == 0, (
        f"the OMEGA MECH burns {snap.power_decay_per_day} cents a day; its table says 0")


def test_and_therefore_does_not_run_dry(module):
    from datetime import datetime

    snap = _climb_to_eleven(module)
    charged = module.current_power_cents(snap)

    a_month_on = datetime.now(ZoneInfo("UTC")) + timedelta(days=30)

    assert module.current_power_cents(snap, a_month_on) == charged, (
        "the final level ran out of energy, which is what makes it the final level")


def test_a_level_that_does_burn_still_burns(module):
    """Counter-check: the refresh must not switch the decay off everywhere."""
    snap = module.Snapshot(mech_id="main", level=9, evo_acc=0, power_acc=4000,
                           goal_requirement=100000, difficulty_bin=1,
                           goal_started_at=module.now_utc_iso(),
                           power_decay_per_day=100)
    event = module.Event(seq=1, ts=module.now_utc_iso(), type="DonationAdded",
                         mech_id="main", payload={"units": 100})
    module.apply_power_event(snap, event)

    assert snap.power_decay_per_day == 100, "level 9 stopped consuming energy"
