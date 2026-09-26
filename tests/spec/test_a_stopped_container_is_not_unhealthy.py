# -*- coding: utf-8 -*-
"""A stopped container is stopped, not unhealthy.

THE FINDING, measured live on the operator's server on 2026-09-26: DDC's own
scheduler stopped a container that has a HEALTHCHECK. The watchdog correctly
kept quiet about "stopped" (DDC did it) - and two minutes later reported

    SUCCESS  unhealthy

because Docker sets State.Health.Status to "unhealthy" when it stops the
health monitor of a container that goes down (checked on the host: exited,
running=false, health=unhealthy). A rule "RESTART on unhealthy" would have
started again the container DDC had just stopped on schedule. A stop by hand
produced two alarms for one event. A paused container reads unhealthy too.

OPERATOR DECISION (2026-09-26): ignore "unhealthy" while the container is not
running. Its health says something only about a running container; a stop is
the "stopped" state's business, with its own rules about who stopped it.

HOW THIS TEST CAN FAIL: an unhealthy event for a container that is not
running, or none for one that is.

COUNTER-CHECK (2026-09-26): red before the fix - the stopped container gave
an UNHEALTHY event beside the STOPPED one, and DDC's own stop gave it alone.
"""

from services.automation.container_watch import STOPPED, UNHEALTHY, ContainerState, ContainerWatcher


def _kinds(events):
    return sorted(event.kind for event in events)


def test_a_stop_by_hand_is_one_alarm_not_two():
    watcher = ContainerWatcher()
    watcher.observe({"web": ContainerState(True, "healthy")}, 0.0)

    events = watcher.observe({"web": ContainerState(False, "unhealthy")}, 30.0)

    assert _kinds(events) == [STOPPED]


def test_a_stop_ddc_ordered_raises_nothing():
    watcher = ContainerWatcher()
    watcher.observe({"web": ContainerState(True, "healthy")}, 0.0)

    events = watcher.observe({"web": ContainerState(False, "unhealthy")}, 30.0, expected={"web"})

    assert events == []


def test_a_running_container_that_turns_unhealthy_is_reported():
    """Counter-case: the check this is about must keep working."""
    watcher = ContainerWatcher()
    watcher.observe({"web": ContainerState(True, "healthy")}, 0.0)

    events = watcher.observe({"web": ContainerState(True, "unhealthy")}, 30.0)

    assert _kinds(events) == [UNHEALTHY]


def test_coming_back_up_unhealthy_is_reported_once():
    """Stopped (health reads unhealthy), started, still failing its check: the
    running container is unhealthy, and that is news."""
    watcher = ContainerWatcher()
    watcher.observe({"web": ContainerState(False, "unhealthy")}, 0.0)

    events = watcher.observe({"web": ContainerState(True, "unhealthy")}, 30.0)

    assert _kinds(events) == [UNHEALTHY]
