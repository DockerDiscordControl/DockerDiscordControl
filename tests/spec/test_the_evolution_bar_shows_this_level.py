# -*- coding: utf-8 -*-
"""The evolution bar and the amount still needed tell the same story.

THE FINDING (review C68, section 22 F4): ``_calculate_progress_data``
computed the evolution bar as

    progress_current = min(total_donated - 0, next_threshold)

``total_donated`` is the LIFETIME figure (``cumulative_donations_cents`` in
progress_service), while ``next_threshold`` is ``prog_state.evo_max``, the
goal of the CURRENT level - and ``evo_acc`` behind it is reset to the excess
at every level-up, so both are per-level quantities.

For any mech past level 1 the lifetime total therefore swamps the per-level
goal and the bar is pinned at 100 %, while ``amount_needed``
(``evo_max - evo_current``) and the ``bars`` field of the very same result -
which reads ``evo_current``/``evo_max`` - show the true, much smaller
progress. One answer, two contradicting numbers in it.
"""

import pytest

from services.mech.mech_data_store import MechDataStore


@pytest.fixture
def store():
    return MechDataStore()


def _core(total_donated, level=4):
    return {'level': level, 'power': 5.0, 'total_donated': total_donated}


def _evolution(next_threshold, amount_needed, current_progress=None):
    data = {'next_threshold': next_threshold, 'amount_needed': amount_needed}
    if current_progress is not None:
        data['current_progress'] = current_progress
    return data


def test_a_long_standing_mech_does_not_show_a_full_bar(store):
    """$500 given over a year, $30 into this level's $50 goal."""
    progress = store._calculate_progress_data(
        _core(total_donated=500.0),
        _evolution(next_threshold=50.0, amount_needed=20.0, current_progress=30.0))

    assert progress['progress_percentage'] < 100.0, (
        "a mech that still needs $20 is shown as fully evolved"
    )
    assert progress['progress_current'] == 30


def test_the_bar_agrees_with_the_amount_still_needed(store):
    evolution = _evolution(next_threshold=50.0, amount_needed=20.0, current_progress=30.0)

    progress = store._calculate_progress_data(_core(total_donated=500.0), evolution)

    assert progress['progress_max'] - progress['progress_current'] == evolution['amount_needed']


def test_a_fresh_level_starts_near_zero(store):
    """Right after a level-up the bar must start over, not stay where the
    lifetime total left it."""
    progress = store._calculate_progress_data(
        _core(total_donated=500.0),
        _evolution(next_threshold=60.0, amount_needed=58.0, current_progress=2.0))

    assert progress['progress_percentage'] < 10.0


def test_a_finished_level_still_shows_a_full_bar(store):
    """Counter-check: the goal reached is 100 %, and must stay so."""
    progress = store._calculate_progress_data(
        _core(total_donated=500.0),
        _evolution(next_threshold=50.0, amount_needed=0.0, current_progress=50.0))

    assert progress['progress_percentage'] == 100.0


def test_a_failed_lookup_is_still_not_a_number(store):
    """Counter-check: review C24 must keep holding."""
    progress = store._calculate_progress_data(
        _core(total_donated=500.0),
        _evolution(next_threshold=None, amount_needed=None))

    assert progress['progress_current'] is None
    assert progress['progress_percentage'] is None


def test_the_producer_really_supplies_the_per_level_figure(store, monkeypatch):
    """The two halves have to meet.

    The tests above hand `current_progress` to the consumer directly, so
    nothing noticed when the producer stopped putting it there - and without
    it the bar reads 0 % for everyone, always (found by mutation M2 of review
    C68).
    """
    class _State:
        level = 4
        evo_current = 30.0
        evo_max = 50.0
        power_max = 12.0

    monkeypatch.setattr("services.mech.progress_service.get_progress_service",
                        lambda: type("S", (), {"get_state": staticmethod(lambda: _State())})())

    evolution = store._calculate_evolution_data(_core(total_donated=500.0))
    progress = store._calculate_progress_data(_core(total_donated=500.0), evolution)

    assert evolution['current_progress'] == 30.0
    assert progress['progress_current'] == 30
    assert progress['progress_max'] - progress['progress_current'] == evolution['amount_needed']
