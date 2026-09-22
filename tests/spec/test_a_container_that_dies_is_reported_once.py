# -*- coding: utf-8 -*-
"""A container that stops, turns unhealthy or restart-loops is reported - once (Phase 4a).

DDC controls containers but, until now, never said when one died: nothing read
Docker's State.Health, RestartCount was only read in dead code, and state
changes in the status cache were not noticed. A container that dies at night
stays dead until somebody opens the panel.

ContainerWatcher is the decision part of the container watchdog: fed one
snapshot per poll, it returns what changed in a way worth a message. The
rules, each checked below:

* a container that WAS running and now is not -> "stopped", exactly once;
* one DDC stopped itself (a pending action) -> nothing, the user asked for it;
* the first time a container is seen -> nothing (DDC starting up is no event);
* health turning "unhealthy" -> once, again only after it recovered;
* RestartCount rising by the threshold within the window -> "restart_loop" once
  per window;
* a container missing from a snapshot -> nothing (not_found is reported
  elsewhere), its last state kept.

Every event names the container and the reason in words.

COUNTER-CHECK (2026-09-22): written before the watcher existed; then the
"remember the last state" line was removed: four tests went red - every
poll then looked like a first sight, and nothing was reported at all.
"""

import pytest

from services.automation.container_watch import ContainerState, ContainerWatcher

RUNNING = ContainerState(running=True, health=None, restart_count=0)
EXITED = ContainerState(running=False, health=None, restart_count=0)


def _kinds(events):
    return [(e.container, e.kind) for e in events]


@pytest.fixture
def watcher():
    return ContainerWatcher(restart_threshold=3, restart_window_seconds=600)


def test_a_running_container_that_stops_is_reported_exactly_once(watcher):
    assert watcher.observe({"web": RUNNING}, now=0) == []
    events = watcher.observe({"web": EXITED}, now=60)
    assert _kinds(events) == [("web", "stopped")]
    assert "web" in events[0].reason and "stopped" in events[0].reason.lower()
    assert watcher.observe({"web": EXITED}, now=120) == []


def test_an_unchanged_state_says_nothing(watcher):
    watcher.observe({"web": RUNNING, "db": EXITED}, now=0)
    assert watcher.observe({"web": RUNNING, "db": EXITED}, now=60) == []


def test_the_first_sight_is_no_event(watcher):
    assert watcher.observe({"web": EXITED}, now=0) == []


def test_a_stop_ddc_was_asked_for_is_not_an_alarm(watcher):
    watcher.observe({"web": RUNNING}, now=0)
    assert watcher.observe({"web": EXITED}, now=60, expected={"web"}) == []


def test_unhealthy_is_reported_on_the_turn_and_again_after_recovery(watcher):
    healthy = ContainerState(running=True, health="healthy", restart_count=0)
    sick = ContainerState(running=True, health="unhealthy", restart_count=0)
    watcher.observe({"web": healthy}, now=0)
    first = watcher.observe({"web": sick}, now=30)
    assert _kinds(first) == [("web", "unhealthy")] and "unhealthy" in first[0].reason
    assert watcher.observe({"web": sick}, now=60) == []
    watcher.observe({"web": healthy}, now=90)
    assert _kinds(watcher.observe({"web": sick}, now=120)) == [("web", "unhealthy")]


def test_a_restart_loop_is_reported_once_per_window(watcher):
    watcher.observe({"web": ContainerState(True, None, 0)}, now=0)
    assert watcher.observe({"web": ContainerState(True, None, 1)}, now=60) == []
    assert watcher.observe({"web": ContainerState(True, None, 2)}, now=120) == []
    loop = watcher.observe({"web": ContainerState(True, None, 3)}, now=180)
    assert _kinds(loop) == [("web", "restart_loop")]
    assert "3" in loop[0].reason and "10 min" in loop[0].reason
    assert watcher.observe({"web": ContainerState(True, None, 4)}, now=240) == []
    # a full window later, three more restarts are a new loop
    for step, count in enumerate((5, 6, 7), start=1):
        events = watcher.observe({"web": ContainerState(True, None, count)}, now=900 + 60 * step)
    assert _kinds(events) == [("web", "restart_loop")]


def test_slow_restarts_are_not_a_loop(watcher):
    watcher.observe({"web": ContainerState(True, None, 0)}, now=0)
    for step, count in enumerate((1, 2, 3, 4), start=1):
        assert watcher.observe({"web": ContainerState(True, None, count)}, now=step * 700) == []


def test_a_missing_container_is_no_event_and_keeps_its_state(watcher):
    watcher.observe({"web": RUNNING}, now=0)
    assert watcher.observe({}, now=60) == []
    assert _kinds(watcher.observe({"web": EXITED}, now=120)) == [("web", "stopped")]
