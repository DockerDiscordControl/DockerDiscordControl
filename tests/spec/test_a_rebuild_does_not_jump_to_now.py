# -*- coding: utf-8 -*-
"""A replay stays in the past, even when one timestamp is unreadable.

THE FINDING (independent review, 2026-09-23): settling at "now" for an event
whose timestamp cannot be read is right on the LIVE path - that fix stopped a
donation from being eaten by consumption already shown as zero. Inside
rebuild_from_events it is wrong: the events are replayed in historical order,
so settling one of them at "now" charges the whole span from the previous
anchor up to today in one go, clamps the power to zero, and then moves the
anchor BACKWARDS when the next (older, valid) event is settled at its own
time. The rebuilt power ends far below the live value - and a rebuild is what
runs when a snapshot is repaired.

A replay settles an unreadable timestamp at the last time it knows, not at
"now".

COUNTER-CHECK (2026-09-23): red before - the rebuilt mech held 0 where the
live path had left it charged. The live case keeps its own spec
(test_a_donation_is_never_eaten_by_old_decay.py).
"""

import importlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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
    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module, "get_config_service",
        lambda: SimpleNamespace(
            get_evolution_mode_service=lambda request: config_module.GetEvolutionModeResult(
                success=True, use_dynamic=True, difficulty_multiplier=1.0)),
        raising=False)
    monkeypatch.setattr(progress_service, "get_decay_config_data", lambda: {"default": 100})
    yield progress_service
    reset_progress_runtime()
    clear_progress_paths_cache()
    importlib.reload(importlib.import_module("services.mech.progress_service"))
    importlib.reload(importlib.import_module("services.mech.gifts"))


def _ago(days):
    return (datetime.now(ZoneInfo("UTC")) - timedelta(days=days)).isoformat()


def test_one_unreadable_timestamp_does_not_drain_the_mech(module):
    """Two donations 60 days ago; the first has a hand-edited timestamp."""
    service = module.ProgressService("main")
    module.append_event(module.Event(seq=module.next_seq(), ts="not a timestamp",
                                     type="DonationAdded", mech_id="main",
                                     payload={"units": 5000, "donor": "a"}))
    module.append_event(module.Event(seq=module.next_seq(), ts=_ago(60),
                                     type="DonationAdded", mech_id="main",
                                     payload={"units": 5000, "donor": "b"}))

    state = service.rebuild_from_events()

    # 60 days at $1.00 a day against $100 donated: the mech still holds $40.
    assert state.power_current == pytest.approx(40.0, abs=0.05), (
        f"the rebuild left {state.power_current} - one bad timestamp charged the "
        f"whole span at once")


def test_the_anchor_does_not_travel_backwards(module):
    """An anchor set to "now" mid-replay makes every later event decay twice."""
    service = module.ProgressService("main")
    module.append_event(module.Event(seq=module.next_seq(), ts=_ago(40),
                                     type="DonationAdded", mech_id="main",
                                     payload={"units": 5000, "donor": "a"}))
    module.append_event(module.Event(seq=module.next_seq(), ts="broken",
                                     type="DonationAdded", mech_id="main",
                                     payload={"units": 5000, "donor": "b"}))
    module.append_event(module.Event(seq=module.next_seq(), ts=_ago(10),
                                     type="DonationAdded", mech_id="main",
                                     payload={"units": 5000, "donor": "c"}))

    service.rebuild_from_events()
    snap = module.load_snapshot("main")

    anchor = module._parse_utc(snap.goal_started_at)
    assert anchor <= datetime.now(ZoneInfo("UTC")), "the anchor is in the future"
    assert anchor >= datetime.now(ZoneInfo("UTC")) - timedelta(days=11), (
        f"the anchor went back to {anchor}; the last event was ten days ago")


def test_a_log_of_good_timestamps_is_unchanged(module):
    """Counter-check: the ordinary replay must not move."""
    service = module.ProgressService("main")
    module.append_event(module.Event(seq=module.next_seq(), ts=_ago(30),
                                     type="DonationAdded", mech_id="main",
                                     payload={"units": 5000, "donor": "a"}))

    state = service.rebuild_from_events()

    assert state.power_current == pytest.approx(20.0, abs=0.05)
