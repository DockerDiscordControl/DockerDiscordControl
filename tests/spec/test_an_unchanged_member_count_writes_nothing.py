# -*- coding: utf-8 -*-
"""A member count that did not change is not news.

THE FINDING (review D26, pass 2, section 24 F2): `update_member_count`
appended a `MemberCountUpdated` event and rewrote the snapshot on every call,
with no comparison against the count already on record. `power_gift` did the
same on both of its early-return branches, where nothing had changed either.

The caller that matters is the donation path: `resolve_member_context`
publishes the member count on EVERY donation, and the startup path is the
only other one - and that one already compares before it publishes
(`member_count.py:63`). So every donation added one more identical line to
`config/progress/events.jsonl`, which is the mech's ledger and is read from
end to end (`read_events()`) at the start of every booking.

This is the same conditional-write rule `get_state` was given earlier, with
its measured evidence: "3 writes in 70 seconds ... for 385 bytes of identical
content". It was not carried to the two methods next to it.

WHY IT IS SAFE TO DROP THE EVENT, which is the part that is not obvious:
`member_count_for_goal` prices the next level from the NEWEST sample - the
latest `MemberCountUpdated` event or `member_count.json`, whichever carries
the later timestamp. Suppressing an event makes the newest event older, so
the file could in principle start winning. It cannot carry a different answer:
the file is written in exactly one place, and there it is written together
with an event of the same value. The last test below pins that, because it is
the property a future change could break without anyone noticing.
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache


@pytest.fixture
def progress(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()
    config = {"timezone": "UTC", "difficulty_bins": [0, 50],
              "level_base_costs": {str(level): 1000 for level in range(1, 12)},
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


def _member_events(module):
    return [e for e in module.read_events() if e.type == "MemberCountUpdated"]


def _count_writes(module, monkeypatch):
    """Count snapshot writes without stopping them."""
    written = []
    original = module.persist_snapshot

    def _counting(snap, *args, **kwargs):
        written.append(snap.mech_id)
        return original(snap, *args, **kwargs)

    monkeypatch.setattr(module, "persist_snapshot", _counting)
    return written


def test_the_same_count_twice_is_one_entry_in_the_ledger(progress):
    service = progress.get_progress_service("main")

    service.update_member_count(42)
    service.update_member_count(42)

    events = _member_events(progress)
    assert len(events) == 1, (
        f"{len(events)} MemberCountUpdated entries for one unchanged count - the "
        f"ledger grows by one line per donation and is read from end to end "
        f"before every booking"
    )


def test_the_same_count_twice_writes_the_snapshot_once(progress, monkeypatch):
    service = progress.get_progress_service("main")
    service.update_member_count(42)

    written = _count_writes(progress, monkeypatch)
    service.update_member_count(42)

    assert written == [], (
        f"{len(written)} snapshot write(s) for a count that did not change - "
        f"a temp file, an fsync and a rename on the array for identical content"
    )


def test_a_changed_count_is_still_recorded(progress):
    """The counter-case: without it, doing nothing at all would pass."""
    service = progress.get_progress_service("main")

    service.update_member_count(42)
    service.update_member_count(43)

    events = _member_events(progress)
    assert [e.payload["member_count"] for e in events] == [42, 43], events
    with progress.LOCK:
        assert progress.load_snapshot("main").last_user_count_sample == 43


def test_a_gift_that_is_refused_writes_nothing(progress, monkeypatch):
    """power_gift's early return: power is already there, so nothing changed."""
    service = progress.get_progress_service("main")
    service.add_donation(5.0, "someone", 1234)
    service.get_state()          # settles last_decay_day, so it is not news either

    written = _count_writes(progress, monkeypatch)
    _, gift = service.power_gift("campaign-a")

    assert gift is None, "the mech had power and was given a gift anyway"
    assert written == [], (
        f"{len(written)} snapshot write(s) for a gift that was refused"
    )


def test_the_price_of_the_next_level_does_not_move(progress):
    """The reason the suppression is safe, pinned.

    `member_count_for_goal` takes the NEWEST sample. Dropping a repeated event
    makes the newest event older, so this must still answer with the count
    that is actually on record - not with a fallback or a default.
    """
    service = progress.get_progress_service("main")
    service.update_member_count(42)
    service.update_member_count(42)

    with progress.LOCK:
        snap = progress.load_snapshot("main")
    assert progress.member_count_for_goal(snap) == 42
