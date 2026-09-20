# -*- coding: utf-8 -*-
"""
THE FINDING (review C24, section 22 F1): one failed dependency call makes
`get_comprehensive_data` return a result that contradicts itself and says
success=True about it.

`_calculate_evolution_data` falls back to `'next_threshold': 0` when the
progress service cannot be reached. `_calculate_progress_data` reads that 0 and
takes the branch labelled "Max level reached":

    else:
        progress_max = 100
        progress_current = 100
        progress_percentage = 100.0

So a lookup that failed is displayed as a fully evolved mech. In the SAME
result, `_calculate_power_bars` asks the same service again and, failing the
same way, falls back to `mech_progress_current=0, mech_progress_max=100` -
0 %. One object claims 100 % evolved in one field and just-started in another,
with success=True and no error text anywhere. A caller - a Discord /mech embed,
the web panel - has no way to learn the numbers are meaningless.

The failure sentinel shared a code path with a real, legitimate state. It gets
its own marker now: None, which the result carries through as "not known",
exactly as the container stats do since review C1.

The counter-check (test_the_real_max_level_is_still_a_hundred_percent) keeps
the state the 100 % branch was actually written for.
"""

import pytest

from services.mech.mech_data_store import MechDataRequest, MechDataStore


@pytest.fixture
def store(monkeypatch):
    instance = MechDataStore()
    monkeypatch.setattr(instance, "_get_core_mech_data", lambda: {
        'success': True, 'level': 3, 'power': 40.0, 'total_donated': 300.0})
    monkeypatch.setattr(instance, "_calculate_speed_data",
                        lambda core, lang, power_max=None: {
                            'speed_level': 2, 'speed_description': 'steady',
                            'speed_color': 0x00FF00})
    monkeypatch.setattr(instance, "_calculate_decay_data", lambda core: {
        'decay_rate': 1.0, 'decay_per_hour': 0.5, 'is_immortal': False})
    monkeypatch.setattr(instance, "_get_technical_data", lambda: {
        'evolution_mode': 'open', 'difficulty_multiplier': 1.0})
    return instance


def _progress_service_is_broken(monkeypatch):
    """The one dependency both fallbacks hang on."""
    def _boom():
        raise AttributeError("progress service unavailable")
    monkeypatch.setattr("services.mech.progress_service.get_progress_service", _boom)


def test_a_failed_lookup_is_not_reported_as_fully_evolved(store, monkeypatch):
    """THE FINDING: 'the call failed' must not be shown as '100 % complete'."""
    _progress_service_is_broken(monkeypatch)

    result = store.get_comprehensive_data(MechDataRequest(force_refresh=True))

    assert result.progress_percentage != 100.0


def test_the_two_halves_of_the_result_do_not_contradict_each_other(store, monkeypatch):
    """The same result claimed 100 % in one field and 0 % in another.

    Noted honestly: this one only bites while BOTH halves are in their old
    shape - repair either and the contradiction is gone, so it cannot guard
    either half on its own. test_the_bars_do_not_invent_numbers_either does
    that for the second half.
    """
    _progress_service_is_broken(monkeypatch)

    result = store.get_comprehensive_data(MechDataRequest(force_refresh=True))

    bars = result.bars
    assert not (result.progress_percentage == 100.0
                and getattr(bars, 'mech_progress_current', None) == 0), (
        f"progress_percentage={result.progress_percentage}, "
        f"bars.mech_progress_current={getattr(bars, 'mech_progress_current', None)}")


def test_the_result_says_the_numbers_are_unknown(store, monkeypatch):
    """Not measured is None, as the container stats have said since C1."""
    _progress_service_is_broken(monkeypatch)

    result = store.get_comprehensive_data(MechDataRequest(force_refresh=True))

    assert result.progress_percentage is None
    assert result.progress_current is None
    assert result.progress_max is None


def test_the_bars_do_not_invent_numbers_either(store, monkeypatch):
    """The second half on its own: 50 and 0/100 were numbers nobody measured."""
    _progress_service_is_broken(monkeypatch)

    bars = store.get_comprehensive_data(MechDataRequest(force_refresh=True)).bars

    assert bars.mech_progress_current is None
    assert bars.mech_progress_max is None
    assert bars.Power_max_for_level is None


def test_the_real_max_level_is_still_a_hundred_percent(store, monkeypatch):
    """COUNTER-CHECK: a mech that genuinely has no next level is still 100 %."""
    monkeypatch.setattr(store, "_calculate_evolution_data", lambda core: {
        'level_name': 'INFINITY', 'next_level': 12, 'next_level_name': '-',
        'next_threshold': 0, 'amount_needed': 0, 'power_max': 200.0})
    monkeypatch.setattr(store, "_calculate_power_bars",
                        lambda core, evo, prog: None)

    result = store.get_comprehensive_data(MechDataRequest(force_refresh=True))

    assert result.progress_percentage == 100.0
    assert result.progress_current == 100
