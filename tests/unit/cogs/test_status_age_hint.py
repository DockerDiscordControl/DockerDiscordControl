# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for the age hint threshold in the status embeds.

Both display sites used to compare the age of a cached status against
``cache_ttl_seconds``, which is ``refresh interval * 2.5``. With the 120 s interval configured on
a real installation, a status of up to five minutes was shown with no hint that it was old, even
though a refresh runs every two minutes.

The threshold is now one and a half intervals, so the hint means "a refresh was missed" instead of
"we are somewhere inside the normal cycle".

Nothing pinned this behaviour before, in either direction.
"""

from types import SimpleNamespace

from cogs.status_handlers import StatusHandlersMixin, _age_hint_threshold_seconds


def _handler(interval=None, ttl=0):
    return SimpleNamespace(status_refresh_interval_seconds=interval, cache_ttl_seconds=ttl)


def test_threshold_is_one_and_a_half_intervals():
    """The live configuration: 120 s interval, TTL 300 s."""
    assert _age_hint_threshold_seconds(_handler(interval=120, ttl=300)) == 180


def test_threshold_follows_the_default_interval():
    """The shipped default: 30 s interval, TTL 75 s."""
    assert _age_hint_threshold_seconds(_handler(interval=30, ttl=75)) == 45


def test_normal_cycle_age_stays_silent():
    """An age inside the regular cycle must not be flagged - otherwise the hint would show up
    before nearly every refresh and mean nothing."""
    threshold = _age_hint_threshold_seconds(_handler(interval=120, ttl=300))
    assert 100 < threshold, "a status 100 s old is normal at a 120 s interval"


def test_missed_refresh_is_flagged():
    """The case this change is about: with the old TTL of 300 s, a status 250 s old looked
    perfectly fresh although two refreshes had been missed."""
    threshold = _age_hint_threshold_seconds(_handler(interval=120, ttl=300))
    assert 250 > threshold
    assert 200 > threshold


def test_bare_mixin_keeps_the_previous_behaviour():
    """The shape the existing tests build: a real mixin with only cache_ttl_seconds set.

    Without a published interval nothing may change - the fallback is the old comparison value.
    """
    mixin = StatusHandlersMixin()
    mixin.cache_ttl_seconds = 75
    assert _age_hint_threshold_seconds(mixin) == 75


def test_missing_attributes_do_not_raise():
    """A mixin without either attribute must not crash embed generation."""
    assert _age_hint_threshold_seconds(StatusHandlersMixin()) == 0


def test_unusable_interval_falls_back_to_the_ttl():
    """Zero, negative, None and a stray bool must not produce a nonsensical threshold."""
    for interval in (0, -5, None, "120", True, False):
        assert _age_hint_threshold_seconds(_handler(interval=interval, ttl=300)) == 300
