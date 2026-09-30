# -*- coding: utf-8 -*-
"""A stop that never reached Docker is not noted as DDC's own.

THE FINDING (stage 4 review before v3.1.0, section 14 pass 4 F6): before a
stop or restart DDC notes it as its own, so the watchdog does not alarm
about it; the note is taken back only when Docker refuses. When the request
never reached Docker - connection refused, a connect timeout (the socket
proxy restarting) - the note stayed for its whole window (5 minutes and
more), and a stop of that container by someone else in that window passed
as DDC's own: no alarm, no restart rule.

THE CONTRACT: an error that proves the request was not delivered takes the
note back; a read timeout (Docker may be carrying it out) keeps it.

HOW THIS TEST CAN FAIL: a refused connection leaves the note again, or a
read timeout drops it.

COUNTER-CHECK (2026-09-30): the not-delivered cases red before the change;
the read-timeout case green before and after.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import requests

from services.automation import own_actions
from services.docker_service.docker_action_service import DockerActionRequest, DockerActionService


def _stop_raising(monkeypatch, error):
    own_actions.reset()

    def _stop(**kwargs):
        raise error
    container = SimpleNamespace(name="nginx", attrs={"Config": {}}, stop=_stop)

    @asynccontextmanager
    async def _client(**kwargs):
        yield SimpleNamespace(containers=SimpleNamespace(get=lambda name: container))
    monkeypatch.setattr("services.docker_service.docker_client_pool.get_docker_client_async", _client)
    result = asyncio.run(DockerActionService().execute_docker_action(
        DockerActionRequest(container_name="nginx", action="stop")))
    return result, "nginx" in own_actions.expected_stops()


@pytest.mark.parametrize("error", [ConnectionRefusedError(111, "Connection refused"),
                                   requests.exceptions.ConnectTimeout("connect timed out")])
def test_an_undelivered_stop_is_taken_back(monkeypatch, error):
    result, noted = _stop_raising(monkeypatch, error)
    assert not result.success
    assert not noted, "a stop Docker never received is still counted as DDC's own"


def test_a_read_timeout_keeps_the_note(monkeypatch):
    _result, noted = _stop_raising(monkeypatch, requests.exceptions.ReadTimeout("read timed out"))
    assert noted, "Docker may still be stopping it - the note must stay"


def test_the_older_action_path_takes_it_back_too(monkeypatch):
    """docker_utils.docker_action notes the same way - and forgets the same way."""
    import services.docker_service.docker_utils as docker_utils
    own_actions.reset()

    def _stop(**kwargs):
        raise ConnectionRefusedError(111, "Connection refused")
    container = SimpleNamespace(name="nginx", attrs={"Config": {}}, stop=_stop)

    @asynccontextmanager
    async def _client(**kwargs):
        yield SimpleNamespace(containers=SimpleNamespace(get=lambda name: container))
    monkeypatch.setattr(docker_utils, "get_docker_client_async", _client)

    assert asyncio.run(docker_utils.docker_action("nginx", "stop")) is False
    assert "nginx" not in own_actions.expected_stops()
