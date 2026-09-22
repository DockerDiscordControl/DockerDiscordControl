# -*- coding: utf-8 -*-
"""Every DDC release gives an empty mech three days of energy.

WHAT THE OPERATOR ASKED FOR (2026-09-23): the decay is the mech's energy
consumption. When a new DDC version starts and the mech has run dry, it gets
three days of energy - exactly three times what its level consumes per day, so
a level 1 mech ($1.00/day) gets $3.00. A mech that still has energy gets
nothing. The gift goes to the ENERGY account only, never to the evolution
account - PowerGiftGranted is the event that does exactly that.

Once per version: the campaign id carries the version, and a campaign already
in the event log is refused, so a restart of the same version gives nothing.

COUNTER-CHECK (2026-09-23): red before - power_gift had no way to say how big
the gift is and handed out the deterministic $1-$3 of the startup campaign.
The counter-checks hold the three promises: nothing for a mech with energy,
nothing twice for one version, and not a cent on the evolution account.
"""

import importlib
import json
from datetime import timedelta

import pytest


@pytest.fixture
def module(tmp_path, monkeypatch):
    """progress_service on a throwaway directory (the paths bind at import)."""
    from services.mech.progress import reset_progress_runtime
    from services.mech.progress_paths import clear_progress_paths_cache

    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    progress_service = importlib.reload(
        importlib.import_module("services.mech.progress_service"))
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
    monkeypatch.setattr(progress_service, "get_decay_config_data", lambda: {"default": 100})
    yield progress_service
    reset_progress_runtime()
    clear_progress_paths_cache()
    importlib.reload(importlib.import_module("services.mech.progress_service"))


@pytest.fixture
def mech(module):
    """A level 1 mech with no energy left."""
    return module.ProgressService(mech_id="main")


def _power(module, service):
    return module.current_power_cents(module.load_snapshot(service.mech_id))


def test_an_empty_mech_gets_three_days(module, mech):
    state, gift = mech.release_gift("3.0.0")

    assert gift == 3.0, f"a level 1 mech consumes $1.00 a day, so three days are $3.00: {gift}"
    assert _power(module, mech) == 300


def test_the_same_version_does_not_give_twice(module, mech):
    """A restart of the same version is not a second gift - not even weeks later.

    Written after a sabotage run: with the campaign check removed the file was
    still green, because the mech had energy from the first gift and the first
    check refused the second. The case that actually needs the campaign is a
    mech that has run dry AGAIN under the same version.
    """
    mech.release_gift("3.0.0")

    # Ten days on, the mech has consumed its three days and stands at zero
    snap = module.load_snapshot("main")
    snap.goal_started_at = (
        module._parse_utc(snap.goal_started_at) - timedelta(days=10)).isoformat()
    module.persist_snapshot(snap)
    assert _power(module, mech) == 0

    _state, second = mech.release_gift("3.0.0")

    assert second is None, "the same release gave a second gift"
    assert _power(module, mech) == 0


def test_a_mech_with_energy_gets_nothing(module, mech):
    """Counter-check: the gift is for an empty mech, not a top-up."""
    mech.release_gift("3.0.0")

    _state, later = mech.release_gift("3.0.1")

    assert later is None
    assert _power(module, mech) == 300


def test_the_gift_never_touches_the_evolution_account(module, mech):
    """Counter-check: energy only - the level must not be bought by a release."""
    before = module.load_snapshot("main").evo_acc

    mech.release_gift("3.0.0")

    assert module.load_snapshot("main").evo_acc == before


def test_three_days_follows_the_level(module, monkeypatch):
    """A higher level consumes more, so its three days are worth more."""
    from services.mech import gifts

    monkeypatch.setattr(gifts, "decay_per_day",
                        lambda level: 250 if level == 5 else 100)

    from services.mech import gifts

    assert gifts.three_days_of_energy(5) == 750
    assert gifts.three_days_of_energy(1) == 300
