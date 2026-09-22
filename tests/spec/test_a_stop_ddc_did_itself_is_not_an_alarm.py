# -*- coding: utf-8 -*-
"""A stop DDC itself carried out is no alarm - whichever way it was ordered.

THE FINDING: the watchdog treats a stop as "expected" only while the
container sits in cog.pending_actions. That dict is written in ONE place (the
single-container button in control_ui) and the entry is deleted the moment
the Docker call returns - a second or two later, while the status loop polls
every 30 seconds or more. So even the button's own stop was usually reported
as an alarm by the next poll. "Stop All", the stack restart and the
auto-action system's own stop/restart never wrote it at all, so a rule that
stops a container could trigger a second rule that restarts it.

Both ways into Docker - DockerActionService.execute_docker_action (buttons,
bulk actions, scheduler, stack restart) and docker_action (the auto-action
system) - now record the container in one place, for a few minutes, and the
watchdog reads it alongside pending_actions.

* a stop DDC carried out is not reported, whichever entry point did it;
* the note is used up by the poll that sees the container stopped, so a stop
  by hand right afterwards is reported again;
* a stop nobody ordered still is;
* after the window the same container is watched again;
* only stop and restart are remembered, and the memory does not grow:
  entries older than the window are dropped.

COUNTER-CHECK (2026-09-22): red before - the stop performed through the
service was reported as "stopped"; and with the window ignored the "watched
again" case goes red.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.automation.container_watch import ContainerState, ContainerWatcher
from services.automation.own_actions import WINDOW_SECONDS, expected_stops, note_own_action, reset


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


def test_the_service_path_records_the_stop():
    from services.docker_service.docker_action_service import DockerActionRequest, DockerActionService

    service = DockerActionService()
    client = MagicMock()
    client.containers.get.return_value = MagicMock()
    with patch("services.docker_service.docker_client_pool.get_docker_client_async") as pool:
        pool.return_value.__aenter__ = AsyncMock(return_value=client)
        pool.return_value.__aexit__ = AsyncMock(return_value=False)
        result = _run(service.execute_docker_action(DockerActionRequest(container_name="web", action="stop")))

    assert result.success
    assert expected_stops(now=0.0) == {"web"}


def test_the_automation_path_records_the_restart():
    from services.docker_service import docker_utils

    client = MagicMock()
    client.containers.get.return_value = MagicMock()
    with patch.object(docker_utils, "get_docker_client_async") as pool:
        pool.return_value.__aenter__ = AsyncMock(return_value=client)
        pool.return_value.__aexit__ = AsyncMock(return_value=False)
        assert _run(docker_utils.docker_action("web", "restart")) is True

    assert expected_stops(now=0.0) == {"web"}


def test_a_start_is_not_remembered():
    note_own_action("web", "start", now=0.0)
    assert expected_stops(now=0.0) == set()


def test_the_memory_is_only_as_long_as_the_window():
    note_own_action("web", "stop", now=0.0)
    assert expected_stops(now=WINDOW_SECONDS - 1) == {"web"}
    assert expected_stops(now=WINDOW_SECONDS + 1) == set()
    # and it is forgotten, not merely hidden
    from services.automation import own_actions
    assert own_actions._recent == {}


def _poll(watcher, running, now):
    """What _feed_container_watchdog does: observe, then forget the note of a
    container this poll has seen stopped."""
    from services.automation.own_actions import forget

    states = {"web": ContainerState(running, None, 0)}
    expected = expected_stops(now)
    events = watcher.observe(states, now, expected)
    for name, state in states.items():
        if not state.running and name in expected:
            forget(name)
    return events


def test_a_stop_ddc_ordered_is_not_reported_but_a_foreign_one_is():
    watcher = ContainerWatcher()
    _poll(watcher, True, 0.0)
    note_own_action("web", "stop", now=1.0)
    assert _poll(watcher, False, 30.0) == []

    _poll(watcher, True, 60.0)
    events = _poll(watcher, False, 90.0)
    assert [(e.container, e.kind) for e in events] == [("web", "stopped")]


def test_after_the_window_the_container_is_watched_again():
    watcher = ContainerWatcher()
    note_own_action("web", "stop", now=0.0)
    _poll(watcher, True, WINDOW_SECONDS + 10)
    events = _poll(watcher, False, WINDOW_SECONDS + 40)
    assert [(e.container, e.kind) for e in events] == [("web", "stopped")]


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)
