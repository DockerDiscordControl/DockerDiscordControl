# -*- coding: utf-8 -*-
"""
THE FINDING (review C11, section 22 F2): `get_comprehensive_data` caches whole
`MechDataResult` objects for ten seconds under

    cache_key = f"comprehensive_{request.include_decimals}_{request.language}"

The request has two more fields that change the answer: `include_projections`
and `projection_hours`. Neither is in the key. Two consequences, both silent:

* `get_level_info()` and `get_power_info()` build a request with
  include_projections=False and store a result whose `projections` is None.
  A `get_projections(hours_ahead=24)` in the next ten seconds hits that entry,
  finds projections=None, and returns `projected_power=current_power`,
  `hours_until_zero=None`, `survival_category='unknown'` - with success=True.
  It reads as "there is nothing to project", not as "nothing was computed".
* `get_projections(48)` followed by `get_projections(1)` returns the 48-hour
  figures for the 1-hour question, because the hours are not in the key either.

The counter-check (test_the_cache_still_spares_the_same_question) keeps the fix
from being "never cache again": the identical request twice in a row must still
be answered from the cache.
"""

import pytest

from services.mech.mech_data_store import (
    MechDataRequest,
    MechDataStore,
    ProjectionDataRequest,
    LevelDataRequest,
)


@pytest.fixture
def store(monkeypatch):
    """A store whose pipeline is fixed, so only the caching is under test."""
    instance = MechDataStore()
    calls = []

    monkeypatch.setattr(instance, "_get_core_mech_data", lambda: {
        'success': True, 'level': 3, 'power': 100.0, 'total_donated': 500.0})
    monkeypatch.setattr(instance, "_calculate_evolution_data", lambda core: {
        'level_name': 'Mk III', 'next_level': 4, 'next_level_name': 'Mk IV',
        'next_threshold': 1000.0, 'amount_needed': 500.0, 'power_max': 200.0})
    monkeypatch.setattr(instance, "_calculate_speed_data", lambda core, lang, power_max=None: {
        'speed_level': 2, 'speed_description': 'steady', 'speed_color': 0x00FF00})
    monkeypatch.setattr(instance, "_calculate_decay_data", lambda core: {
        'decay_rate': 1.0, 'decay_per_hour': 0.5, 'is_immortal': False})
    monkeypatch.setattr(instance, "_calculate_progress_data", lambda core, evo: {
        'progress_current': 50, 'progress_max': 100, 'progress_percentage': 50.0})
    monkeypatch.setattr(instance, "_get_technical_data", lambda: {
        'evolution_mode': 'open', 'difficulty_multiplier': 1.0})
    monkeypatch.setattr(instance, "_calculate_power_bars", lambda core, evo, prog: None)

    def _projections(core, decay, hours):
        calls.append(hours)
        return {'projected_power': 100.0 - hours, 'hours_until_zero': hours * 2,
                'survival_category': f'{hours}h'}

    monkeypatch.setattr(instance, "_calculate_projections", _projections)
    instance.calls = calls
    return instance


def test_a_projection_is_computed_even_after_a_plain_request(store):
    """THE FINDING: the cached answer to a different question must not be
    handed back as the answer to this one."""
    store.get_level_info(LevelDataRequest())  # fills the cache, no projections

    # Deliberately the DEFAULT horizon (24.0, as both request dataclasses
    # declare it). An earlier version of this test passed the int 24, and the
    # keys then differed by "24" vs "24.0" alone - the test would have passed
    # for a reason that has nothing to do with the finding.
    result = store.get_projections(ProjectionDataRequest(hours_ahead=24.0))

    assert store.calls == [24.0], "no projection was computed at all"
    assert result.survival_category == "24.0h"
    assert result.hours_until_zero == 48.0


def test_a_different_horizon_is_a_different_question(store):
    """48 hours and 1 hour are not the same answer."""
    first = store.get_projections(ProjectionDataRequest(hours_ahead=48))
    second = store.get_projections(ProjectionDataRequest(hours_ahead=1))

    assert first.survival_category == "48h"
    assert second.survival_category == "1h"


def test_the_cache_still_spares_the_same_question(store):
    """COUNTER-CHECK: the fix must not turn the cache off. The identical
    request twice in a row is computed once."""
    store.get_comprehensive_data(MechDataRequest(include_projections=True,
                                                 projection_hours=12))
    store.get_comprehensive_data(MechDataRequest(include_projections=True,
                                                 projection_hours=12))

    assert store.calls == [12]
