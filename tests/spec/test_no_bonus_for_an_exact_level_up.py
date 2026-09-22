# -*- coding: utf-8 -*-
"""A level-up no longer pays a bonus, because energy survives it.

WHAT THE OPERATOR DECIDED (2026-09-23): the $1 bonus for hitting a level's
goal exactly was a plaster over a wound that is now healed. It existed because
a level-up reset the energy account to the surplus - and an exact hit leaves a
surplus of zero, so a mech that climbed perfectly stood at zero energy. Since
energy survives a level-up (test_energy_survives_a_level_up.py) there is
nothing to make up for, and the bonus is gone.

Nothing is lost by it: the event log of the running installation holds zero
ExactHitBonusGranted events (checked 2026-09-23 in the container), so no mech
loses a cent when a rebuild replays its history without the bonus. Old events
still READ correctly in the donation history, which is why the type stays
known there.

COUNTER-CHECK (2026-09-23): red before - an exact hit added 100 cents and
wrote an ExactHitBonusGranted event. The counter-checks keep the climb itself
and the energy that now carries over.
"""

import importlib
import json

import pytest


@pytest.fixture
def module(tmp_path, monkeypatch):
    """progress_service on a throwaway directory, $10 per level."""
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


def test_an_exact_hit_gets_no_extra_dollar(module, mech):
    mech.add_donation(10.0, donor="exact", idempotency_key="k1")   # the goal, to the cent

    snap = module.load_snapshot("main")
    assert snap.level == 2
    assert snap.evo_acc == 0, "an exact hit leaves no surplus"
    assert snap.power_acc == 1000, (
        f"the donation is the energy, with nothing added: {snap.power_acc}")


def test_no_bonus_event_is_written(module, mech):
    mech.add_donation(10.0, donor="exact", idempotency_key="k1")

    assert [e for e in module.read_events() if e.type == "ExactHitBonusGranted"] == []


def test_the_climb_itself_still_happens(module, mech):
    """Counter-check: removing the bonus must not remove the level-up."""
    mech.add_donation(10.0, donor="exact", idempotency_key="k1")

    climbs = [e for e in module.read_events() if e.type == "LevelUpCommitted"]
    assert len(climbs) == 1
    assert climbs[0].payload["from_level"] == 1 and climbs[0].payload["to_level"] == 2


def test_a_rebuild_gives_the_same_state(module, mech):
    """Counter-check: the replay agrees with the live path, as it must."""
    mech.add_donation(10.0, donor="exact", idempotency_key="k1")
    live = module.load_snapshot("main")

    mech.rebuild_from_events()
    rebuilt = module.load_snapshot("main")

    assert (rebuilt.level, rebuilt.evo_acc, rebuilt.power_acc) == (
        live.level, live.evo_acc, live.power_acc)
