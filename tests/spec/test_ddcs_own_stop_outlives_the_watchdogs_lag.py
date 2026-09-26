# -*- coding: utf-8 -*-
"""The note of DDC's own stop lasts longer than the watchdog can lag behind.

THE FINDING, measured live on the operator's server on 2026-09-26. His
container sets DDC_DOCKER_CACHE_DURATION=120: the status loop polls every two
minutes and serves answers cached for 2.5 intervals (five minutes). A stop by
hand reached the watchdog 300 s after it happened, a pause 359 s after. The
note that says "DDC did this" lived a fixed 300 s - so a stop DDC ordered just
after a poll could outlive its note, be reported as an alarm, and be undone by
a restart rule.

OPERATOR DECISION (2026-09-26): tie the window to the poll interval.

THE CONTRACT: the window is at least the cache's 2.5 intervals plus one poll
plus a minute, and never shorter than the 300 s it always was.

HOW THIS TEST CAN FAIL: a note gone before the watchdog can see the stop.

COUNTER-CHECK (2026-09-26): red before the fix - with a 120 s interval a note
359 s old (the measured pause) was already dropped.
"""

import pytest

from services.automation.own_actions import (WINDOW_SECONDS, expected_stops, note_own_action,
                                             reset, window_seconds)


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


def test_the_measured_lag_is_covered_at_his_interval():
    note_own_action("web", "stop", now=0.0)

    assert expected_stops(now=359.0, poll_seconds=120) == {"web"}


@pytest.mark.parametrize("poll", [10, 30, 60, 120, 300])
def test_the_window_covers_cache_plus_one_poll(poll):
    assert window_seconds(poll) >= poll * 2.5 + poll


def test_it_is_never_shorter_than_before():
    """Counter-case: a short interval must not shrink the old 300 s."""
    assert window_seconds(10) == WINDOW_SECONDS


def test_the_setting_is_what_it_reads(monkeypatch):
    """Without an explicit interval it asks the same setting the status loop does."""
    monkeypatch.setenv("DDC_DOCKER_CACHE_DURATION", "120")

    assert window_seconds() == window_seconds(120)
