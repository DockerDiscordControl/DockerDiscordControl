# -*- coding: utf-8 -*-
"""A stop DDC ordered is its own even when the client stopped waiting for it.

THE FINDING (audit 2026-09-26). Both ways into Docker told the watchdog "DDC
did this" (note_own_action) only AFTER the Docker call returned successfully.
A stop or restart that outlasts the client's read timeout raises here - and
Docker carries it out anyway. Nothing was noted, so the next poll reported
"stopped (it was running)" as an alarm, and a watchdog rule that restarts
stopped containers undid a stop the operator had ordered on purpose.

THE CONTRACT: the note is written before the call. It is taken back only when
Docker itself refused (an APIError answer: nothing happened). A timeout or a
broken connection leaves it, because the outcome is unknown and Docker may
well be doing what it was asked.

HOW THIS TEST CAN FAIL: a timed-out stop is not noted, or a refused one is.

COUNTER-CHECK (2026-09-26): red before the fix - both timeout cases left
expected_stops empty.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import docker
import pytest

from services.automation.own_actions import expected_stops, reset


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


def _client(error):
    client = MagicMock()
    container = MagicMock()
    container.attrs = {"Config": {}}
    container.stop.side_effect = error
    container.restart.side_effect = error
    client.containers.get.return_value = container
    return client


def _through_the_service(error, action="stop"):
    from services.docker_service.docker_action_service import DockerActionRequest, DockerActionService

    with patch("services.docker_service.docker_client_pool.get_docker_client_async") as pool:
        pool.return_value.__aenter__ = AsyncMock(return_value=_client(error))
        pool.return_value.__aexit__ = AsyncMock(return_value=False)
        return asyncio.run(DockerActionService().execute_docker_action(
            DockerActionRequest(container_name="web", action=action)))


def _through_the_automation(error, action="restart"):
    from services.docker_service import docker_utils

    with patch.object(docker_utils, "get_docker_client_async") as pool:
        pool.return_value.__aenter__ = AsyncMock(return_value=_client(error))
        pool.return_value.__aexit__ = AsyncMock(return_value=False)
        return asyncio.run(docker_utils.docker_action("web", action))


def test_a_timed_out_stop_through_the_service_is_noted():
    result = _through_the_service(OSError("Read timed out"))

    assert not result.success
    assert expected_stops(now=0.0) == {"web"}


def test_a_timed_out_restart_through_the_automation_is_noted():
    assert _through_the_automation(OSError("Read timed out")) is False
    assert expected_stops(now=0.0) == {"web"}


def test_a_refused_stop_is_not_noted():
    """Counter-case: Docker answered no - nothing happened, so a stop seen in
    the next poll is somebody else's and must be reported."""
    refused = docker.errors.APIError("409 Conflict")

    _through_the_service(refused)
    assert expected_stops(now=0.0) == set()

    _through_the_automation(refused)
    assert expected_stops(now=0.0) == set()
