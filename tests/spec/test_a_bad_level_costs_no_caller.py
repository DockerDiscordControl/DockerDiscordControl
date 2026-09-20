# -*- coding: utf-8 -*-
"""A level nobody knows costs a speed, not the caller.

THE FINDING (review C75, section 25 F5): ``get_speed_level_for_state`` calls
``_get_level_power_range(evolution_level)`` whenever ``power_max`` is missing
or the level is 11, and that helper raises ``ValueError`` for a level the
evolution config does not know. ``get_combined_mech_status`` in the same file
wraps the equivalent call and falls back to ``min(int(power), 100)``;
``get_speed_level_for_state`` had no guard of its own, so the guarantee held
for the entry point inside this file and not for the one other callers use.

``services/web/donation_status_service`` calls it directly and catches
ValueError itself - which is the point: the promise should not depend on each
caller remembering it.
"""

import logging

import pytest

from services.mech import speed_levels


def test_an_unknown_level_still_gives_a_speed():
    speed = speed_levels.get_speed_level_for_state(99, power_amount=7.0)

    assert isinstance(speed, int), "a level the config does not know took the caller down"
    assert 0 <= speed <= 101


def test_an_unknown_level_with_no_power_is_offline():
    assert speed_levels.get_speed_level_for_state(99, power_amount=0.0) == 0


def test_a_negative_power_is_not_a_negative_speed(caplog):
    """The speed scale is 0-101. Power after decay can go below zero before it
    is clamped, and `min(int(power), 100)` would hand that straight through
    (found by mutation M2 of review C75)."""
    speed = speed_levels.get_speed_level_for_state(99, power_amount=-5.0)

    assert speed == 0, f"a negative power came back as speed {speed}"


def test_the_unknown_level_is_named_in_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        speed_levels.get_speed_level_for_state(99, power_amount=7.0)

    assert any("99" in record.getMessage() for record in caplog.records
               if record.levelno >= logging.WARNING), (
        "the speed was guessed and nothing says the level was unknown"
    )


def test_a_known_level_is_unaffected():
    """Counter-check: falling back always would pass the tests above."""
    with_bar = speed_levels.get_speed_level_for_state(2, power_amount=15.0, power_max=16.0)
    without_bar = speed_levels.get_speed_level_for_state(2, power_amount=15.0)

    assert with_bar == 93
    assert isinstance(without_bar, int)


def test_the_top_level_keeps_its_own_scale():
    """Counter-check: level 11 deliberately takes the config route, and it
    must keep taking it."""
    speed = speed_levels.get_speed_level_for_state(11, power_amount=50.0, power_max=60.0)

    assert isinstance(speed, int)
    assert 0 <= speed <= 101
