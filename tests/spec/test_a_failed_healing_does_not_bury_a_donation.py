# -*- coding: utf-8 -*-
"""A healing that did not heal must not let the next write bury the donation.

THE FINDING (review D1, pass 2, section 24 F1 - critical): every method that
moves ``last_event_seq`` forward calls ``_heal_if_lagging`` first, precisely
so a snapshot write that failed earlier cannot bury an already-logged
donation. That helper calls ``rebuild_from_events()`` - and throws its return
value away.

``rebuild_from_events`` can REFUSE. Its default is
``allow_damaged_log=False``, and the event log is shared by every mech, so a
single unreadable line anywhere in it - written by any process, for any mech
- makes the rebuild keep the old snapshot, log "Refusing to rebuild", and
return the stale state. ``_heal_if_lagging`` does not look, so the caller
carries on, appends its own event and persists ``last_event_seq`` PAST the
buried one. ``_snapshot_lags`` only ever looks at events ABOVE that number,
so the earlier donation is invisible from then on. Money, gone, silently -
which is the one thing this programme ranks above everything else.

The healing itself is the fix of pass 1's section 24 F1. This is the hole in
that repair.
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from services.exceptions import MechServiceError
from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache


@pytest.fixture
def progress(tmp_path, monkeypatch):
    """An isolated progress runtime with a cheap level-up."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()

    config = {"timezone": "UTC", "difficulty_bins": [0, 50],
              "level_base_costs": {str(level): 100000 for level in range(1, 12)},
              "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
              "mech_power_decay_per_day": {"default": 0}}
    module.runtime.configure_defaults(config)
    module.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    module.CFG = module.runtime.load_config(refresh=True)
    module.TZ = module.runtime.timezone(refresh=True)

    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(config_module, "get_config_service",
                        lambda: SimpleNamespace(
                            get_evolution_mode_service=lambda request:
                            config_module.GetEvolutionModeResult(
                                success=True, use_dynamic=True,
                                difficulty_multiplier=1.0)),
                        raising=False)
    module._decay_config_cache["data"] = None
    module._decay_config_cache["last_load"] = 0

    try:
        yield module
    finally:
        module.reset_progress_services()
        reset_progress_runtime()
        clear_progress_paths_cache()


def _bury_an_event(module, service):
    """The state a crash between append_event and persist_snapshot leaves:
    the donation is in the log, the snapshot does not carry it."""
    event = module.Event(
        seq=module.next_seq(), ts=module.now_utc_iso(), type="DonationAdded",
        mech_id=service.mech_id,
        payload={"donation_id": "buried", "idempotency_key": "buried",
                 "units": 5000, "donor": "max", "channel_id": None},
    )
    module.append_event(event)
    return event


def _damage_the_log(module):
    """One unreadable line anywhere in the shared log - any mech, any process."""
    with open(module.EVENT_LOG, "a", encoding="utf-8") as handle:
        handle.write("{this is not json\n")


def test_a_donation_is_not_booked_over_a_buried_one(progress):
    service = progress.get_progress_service()
    service.add_donation(10.0, donor="max", idempotency_key="first")
    buried = _bury_an_event(progress, service)
    _damage_the_log(progress)

    with pytest.raises(MechServiceError):
        service.add_donation(20.0, donor="max", idempotency_key="second")

    snapshot = progress.load_snapshot(service.mech_id)
    assert snapshot.last_event_seq < buried.seq, (
        "the snapshot was written past the buried donation - it can never be seen again"
    )


def test_the_buried_donation_is_still_findable_afterwards(progress):
    """The whole point: the lag must still be detectable, so a repaired log
    can still recover the money."""
    service = progress.get_progress_service()
    service.add_donation(10.0, donor="max", idempotency_key="first")
    _bury_an_event(progress, service)
    _damage_the_log(progress)

    with pytest.raises(MechServiceError):
        service.add_donation(20.0, donor="max", idempotency_key="second")

    events, _damaged = progress.read_events(count_damaged=True)
    assert progress._snapshot_lags(progress.load_snapshot(service.mech_id), events), (
        "the lag is gone, so nothing will ever try to heal it again"
    )


def test_a_clean_log_still_heals_and_books(progress):
    """Counter-check: the healing of pass 1 must keep working."""
    service = progress.get_progress_service()
    service.add_donation(10.0, donor="max", idempotency_key="first")
    _bury_an_event(progress, service)

    state = service.add_donation(20.0, donor="max", idempotency_key="second")

    assert state.total_donated == pytest.approx(80.0), (
        "10 + the buried 50 + 20 - the healing should have replayed all three"
    )


def test_an_old_damaged_line_alone_blocks_nothing(progress):
    """Counter-check, and the important one: a damaged line somewhere in the
    shared log must not stop everyday donations. Only a damaged line AND a
    lagging snapshot is the dangerous pair."""
    service = progress.get_progress_service()
    service.add_donation(10.0, donor="max", idempotency_key="first")
    _damage_the_log(progress)

    state = service.add_donation(20.0, donor="max", idempotency_key="second")

    assert state.total_donated == pytest.approx(30.0)
