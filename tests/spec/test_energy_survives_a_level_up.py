# -*- coding: utf-8 -*-
"""Energy survives a level-up, and the battery does not overflow.

WHAT THE OPERATOR DECIDED (2026-09-23): the energy account is the mech's
battery, not a second progress bar. Until now a level-up reset it to the
surplus, exactly like the evolution account ("Reset power to excess (same as
evolution)"), so a mech stood almost empty the moment it climbed - and
consumed MORE per day from then on. Energy now stays across a level-up.

A battery has a size: the level's goal, which is what the bar shows as its
maximum. (It was the goal plus $1 until the exact-hit bonus was dropped on the
same day - that dollar was the bonus's place in the bar.) What does not fit is
lost - the donation still counts in full towards evolution, so nobody loses
progress, and the bar can no longer be fuller than full. The last level has no
goal and therefore no limit, as before.

The capacity that counts is the one AFTER the climb: a donation that lifts the
mech two levels fills the bigger battery it ends up with.

COUNTER-CHECK (2026-09-23): red before - a level-up left $1 of energy where
$11 had been donated, and a donation into a nearly full battery pushed it past
its maximum. The counter-checks keep the evolution account whole and the decay
running.
"""

import importlib
import json

import pytest


@pytest.fixture
def module(tmp_path, monkeypatch):
    """progress_service on a throwaway directory, $10 per level, $1/day decay."""
    from services.mech.progress import reset_progress_runtime
    from services.mech.progress_paths import clear_progress_paths_cache

    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    progress_service = importlib.reload(
        importlib.import_module("services.mech.progress_service"))
    # gifts.py imports names FROM progress_service, so a reload leaves it
    # pointing at the old module - and with it at the old decay config.
    importlib.reload(importlib.import_module("services.mech.gifts"))
    progress_service.reset_progress_services()
    config = {
        "timezone": "UTC",
        "difficulty_bins": [0, 50],
        "level_base_costs": {str(level): 1000 for level in range(1, 12)},
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }
    progress_service.runtime.configure_defaults(config)
    progress_service.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    progress_service.CFG = progress_service.runtime.load_config(refresh=True)
    progress_service.TZ = progress_service.runtime.timezone(refresh=True)
    # The difficulty multiplier comes from the config service, and in a group
    # run that is the real one - a level cost ten times what this test set up.
    # Same stub as tests/unit/services/mech/test_progress_service.py.
    from types import SimpleNamespace

    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module, "get_config_service",
        lambda: SimpleNamespace(
            get_evolution_mode_service=lambda request: config_module.GetEvolutionModeResult(
                success=True, use_dynamic=True, difficulty_multiplier=1.0)),
        raising=False)
    progress_service._decay_config_cache["data"] = None
    progress_service._decay_config_cache["last_load"] = 0

    yield progress_service
    reset_progress_runtime()
    clear_progress_paths_cache()
    importlib.reload(importlib.import_module("services.mech.progress_service"))
    importlib.reload(importlib.import_module("services.mech.gifts"))


@pytest.fixture
def mech(module):
    return module.ProgressService(mech_id="main")


def _snap(module):
    return module.load_snapshot("main")


def test_energy_is_not_reset_by_a_level_up(module, mech):
    mech.add_donation(5.0, donor="a", idempotency_key="k1")
    mech.add_donation(6.0, donor="b", idempotency_key="k2")      # $11 of $10: climbs

    snap = _snap(module)
    assert snap.level == 2
    assert snap.evo_acc == 100, "the evolution account keeps only the surplus"
    assert snap.power_acc == 1100, (
        f"the battery must keep what was donated into it, not {snap.power_acc}")


def test_the_battery_does_not_take_more_than_it_holds(module, mech):
    mech.add_donation(9.0, donor="a", idempotency_key="k1")      # battery $10, in it $9
    mech.add_donation(0.5, donor="b", idempotency_key="k2")      # $9.50, still room

    assert _snap(module).power_acc == 950

    mech.add_donation(0.4, donor="c", idempotency_key="k3")      # $9.90 of $10

    snap = _snap(module)
    assert snap.power_acc == 990
    assert snap.evo_acc == 990, "the evolution account takes every cent"


def test_what_does_not_fit_is_lost_but_evolution_keeps_it(module, mech):
    """A donation into a nearly full battery: the bar stops at full."""
    mech.add_donation(9.9, donor="a", idempotency_key="k1")      # $9.90 of $10, no climb
    mech.add_donation(0.5, donor="b", idempotency_key="k2")      # $10.40 -> climbs

    snap = _snap(module)
    assert snap.level == 2
    assert snap.evo_acc == 40, "evolution keeps the surplus of the climb"
    # After the climb the goal is bigger, so the battery is too - $10.40 fits in it
    assert snap.power_acc == 1040


def test_a_gift_into_a_full_battery_stops_at_the_top(module, mech):
    """Full is full - the case only a gift can reach.

    A donation cannot overfill the battery on its own: it feeds the evolution
    account at the same time, so it climbs before it overflows. A gift and a
    system donation pay into the energy account ALONE, and that is where the
    lid matters.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    mech.add_donation(9.0, donor="a", idempotency_key="k1")      # $9 of $10
    snap = _snap(module)
    capacity = module.battery_capacity_cents(snap)
    assert capacity == snap.goal_requirement

    gift = module.Event(seq=module.next_seq(), ts=datetime.now(ZoneInfo("UTC")).isoformat(),
                        type="PowerGiftGranted", mech_id="main",
                        payload={"campaign_id": "probe", "power_units": 1000})
    module.apply_power_event(snap, gift)

    assert snap.power_acc == capacity, (
        f"the battery holds {snap.power_acc} where it fits {capacity}")
    assert snap.evo_acc == 900, "a gift never touches the evolution account"


def test_the_decay_still_empties_it(module, mech):
    """Counter-check: a battery that fills is still a battery that drains."""
    from datetime import timedelta

    mech.add_donation(5.0, donor="a", idempotency_key="k1")
    snap = _snap(module)
    snap.goal_started_at = (
        module._parse_utc(snap.goal_started_at) - timedelta(days=2)).isoformat()
    module.persist_snapshot(snap)

    assert module.current_power_cents(_snap(module)) == 300      # $5 minus two days
