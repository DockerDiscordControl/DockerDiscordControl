# -*- coding: utf-8 -*-
"""
THE FINDING (review C19, section 23 F2): `_fetch_fresh_status` asks
`get_combined_mech_status` for the mech's speed, takes the DESCRIPTION and the
COLOUR out of the answer -

    speed_description = combined_status['speed']['description']
    speed_color = combined_status['speed']['color']

- and then fills the number beside them with a constant:

    speed=50.0,  # Default speed

`combined_status['speed']['level']`, the value the description and the colour
were themselves derived from, sits right there unused. Every consumer of
`.speed` - `cogs/docker_control.py` builds `{'level': result.speed, ...}` from
it - is handed 50 whether the mech is at zero power or at full, while the words
and the colour next to that number are right. Two halves of one statement, one
of them made up.

The counter-check (test_the_description_and_colour_still_match) keeps the
sibling fields on the same source, so the fix cannot fix the number by breaking
the text.
"""

import pytest

from services.mech import mech_status_cache_service as module
from services.mech.mech_status_cache_service import MechStatusCacheService


class _Bars:
    Power_max_for_level = 100.0


class _DataResult:
    success = True
    current_level = 4
    current_power = 25.0
    total_donated = 400.0
    level_name = "ARMORED MECH"
    next_level_threshold = 800
    bars = _Bars()


@pytest.fixture
def service(monkeypatch):
    instance = MechStatusCacheService.__new__(MechStatusCacheService)
    instance.logger = module.logger
    instance._cache = {}

    class _Store:
        @staticmethod
        def get_comprehensive_data(request):
            return _DataResult()

    monkeypatch.setattr("services.mech.mech_data_store.get_mech_data_store",
                        lambda: _Store())
    return instance


def _speed_of(level, description="FAST", color="#00FF00"):
    def _combined(**kwargs):
        return {'speed': {'level': level, 'description': description,
                          'color': color}}
    return _combined


def test_the_number_comes_from_the_same_answer_as_the_words(service, monkeypatch):
    """THE FINDING: the speed number must not be a constant."""
    monkeypatch.setattr("services.mech.speed_levels.get_combined_mech_status",
                        _speed_of(7))

    result = service._fetch_fresh_status(include_decimals=False)

    assert result.success is True
    assert result.speed == 7


def test_a_different_speed_gives_a_different_number(service, monkeypatch):
    """Stated as the operator would notice it: the value must move."""
    monkeypatch.setattr("services.mech.speed_levels.get_combined_mech_status",
                        _speed_of(0, "OFFLINE", "#888888"))
    stopped = service._fetch_fresh_status(include_decimals=False)

    monkeypatch.setattr("services.mech.speed_levels.get_combined_mech_status",
                        _speed_of(10, "BLAZING", "#FF0000"))
    running = service._fetch_fresh_status(include_decimals=False)

    assert stopped.speed != running.speed


def test_the_description_and_colour_still_match(service, monkeypatch):
    """COUNTER-CHECK: the text and the colour keep coming from that same
    answer - the number joins them, it does not replace them."""
    monkeypatch.setattr("services.mech.speed_levels.get_combined_mech_status",
                        _speed_of(3, "STEADY", "#FFAA00"))

    result = service._fetch_fresh_status(include_decimals=False)

    assert result.speed_description == "STEADY"
    assert result.speed_color == "#FFAA00"
    assert result.level == 4
    assert result.power == 25.0
