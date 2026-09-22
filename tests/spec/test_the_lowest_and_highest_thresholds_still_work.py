# -*- coding: utf-8 -*-
"""The thresholds at both ends of the panel's range still work (Phase 4b).

Two findings in ResourceWatcher, both reachable with settings the web panel
offers (10 to 100 percent):

* the re-arm needs `value < threshold - hysteresis`, and the status loop
  always builds the watcher with the default hysteresis of 10. At a threshold
  of 10 that asks for a value below zero, so the container is reported ONCE
  and then never again - the watcher is latched for the life of the process.
  The margin is now at most half the threshold;
* the alarm needs `value > threshold`, so a container pinned at exactly the
  threshold never reports at all - with the highest setting the panel offers
  (100 percent) that is a container sitting at 100 percent CPU, which is
  precisely what such a rule is for. The comparison now reads "at or above",
  and so does the message.

COUNTER-CHECK (2026-09-22): red before - the 10-percent watcher reported
once and stayed silent through an hour at 99 percent, and the 100-percent
watcher reported nothing at all.
"""

from services.automation.container_watch import ResourceWatcher

MINUTE = 60.0


def _watcher(threshold, minutes=1):
    return ResourceWatcher(metric="cpu", threshold_percent=threshold, minutes=minutes)


def test_the_lowest_threshold_re_arms_again():
    watcher = _watcher(10)
    watcher.observe({"web": 50.0}, 0.0)
    assert len(watcher.observe({"web": 50.0}, MINUTE + 1)) == 1

    watcher.observe({"web": 2.0}, 2 * MINUTE)          # calm again: below half the threshold
    watcher.observe({"web": 99.0}, 3 * MINUTE)
    assert len(watcher.observe({"web": 99.0}, 4 * MINUTE + 1)) == 1, (
        "the watcher stayed latched - at a threshold of 10 the old margin asked for a "
        "value below zero")


def test_the_lowest_threshold_still_does_not_report_every_poll():
    """Counter-check: a value hovering just under the line must stay quiet."""
    watcher = _watcher(10)
    watcher.observe({"web": 12.0}, 0.0)
    assert len(watcher.observe({"web": 12.0}, MINUTE + 1)) == 1
    watcher.observe({"web": 9.0}, 2 * MINUTE)          # below the threshold, inside the margin
    watcher.observe({"web": 12.0}, 3 * MINUTE)
    assert watcher.observe({"web": 12.0}, 4 * MINUTE + 1) == []


def test_a_container_pinned_at_the_threshold_is_reported():
    watcher = _watcher(100)
    watcher.observe({"web": 100.0}, 0.0)
    events = watcher.observe({"web": 100.0}, MINUTE + 1)
    assert [e.kind for e in events] == ["high_cpu"], (
        "a container at 100 percent CPU with the panel's highest threshold reports nothing")
    assert "100" in events[0].reason


def test_below_the_threshold_is_still_quiet():
    """Counter-check, the other side."""
    watcher = _watcher(80)
    watcher.observe({"web": 79.9}, 0.0)
    assert watcher.observe({"web": 79.9}, MINUTE + 1) == []
