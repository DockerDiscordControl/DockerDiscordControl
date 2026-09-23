# -*- coding: utf-8 -*-
"""A container DDC could not ask about is not announced as "not found".

THE FINDING (independent review of the Docker layer, 2026-09-23):
is_container_exists has three states to report and only two return values:

    except docker.errors.NotFound:
        return False                    # it really is not there
    except (DockerServiceError, DockerException, OSError, RuntimeError):
        logger.error(...)
        return False                    # DDC could not ask

An auto-action rule fires while Docker is unreachable - the proxy is down, the
daemon is restarting. The second branch answers False, and automation_service
then records the trigger as FAILED / "Container not found", posts

    ⚠️ Container `X` not found — *rule name*

into Discord, and skips the START/STOP/RESTART entirely. The container is fine.
The automation the operator was relying on did not run, and they were told
something about their setup that is not true.

The author already knows the shape: three lines below, _honours_only_if_running
keeps "unknown" as its own state and lets an unknown fall THROUGH to the action
(review E25), and _get_running_state returns None for it. This one function
conflates.

WHAT AN UNKNOWN DOES NOW: it falls through to the action, exactly as an unknown
running-state does. If the container really is gone, the Docker call fails and
is reported with the reason Docker gave - which is more honest than DDC
inventing "not found" on a question it never got to ask.

HOW THIS TEST CAN FAIL: it makes the existence check fail with a connection
error and reads what the rule did. A "not found" verdict, or a skipped action,
is red.

COUNTER-CHECK (2026-09-23): red before - FAILED / "Container not found" and no
action. The other tests keep the real cases: a container that genuinely does
not exist is still reported as missing, and an existing one still acts.
"""

import asyncio

import docker
import pytest

from services.docker_service import docker_utils
from services.exceptions import DockerServiceError


class _Containers:
    def __init__(self, behaviour):
        self._behaviour = behaviour

    def get(self, name):
        return self._behaviour(name)


class _Client:
    def __init__(self, behaviour):
        self.containers = _Containers(behaviour)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _with(behaviour, monkeypatch):
    monkeypatch.setattr(docker_utils, "get_docker_client_async",
                        lambda **kwargs: _Client(behaviour))


def _ask(name="nginx"):
    return asyncio.run(docker_utils.is_container_exists(name))


def test_a_container_that_is_there_is_true(monkeypatch):
    """Counter-check: the everyday answer."""
    _with(lambda name: object(), monkeypatch)

    assert _ask() is True


def test_a_container_that_is_gone_is_false(monkeypatch):
    """Counter-check: the other real answer, and it must stay False."""
    def gone(name):
        raise docker.errors.NotFound("no such container")

    _with(gone, monkeypatch)

    assert _ask() is False


@pytest.mark.parametrize("error", [
    pytest.param(docker.errors.DockerException("connection refused"), id="daemon-unreachable"),
    pytest.param(DockerServiceError("the proxy is not answering"), id="proxy-down"),
    pytest.param(OSError("socket gone"), id="socket-gone"),
])
def test_a_question_we_could_not_ask_is_not_a_no(monkeypatch, error):
    """THE FINDING: this answered False, and the rule announced 'not found'."""
    def unreachable(name):
        raise error

    _with(unreachable, monkeypatch)

    answer = _ask()

    assert answer is not False, (
        "DDC could not reach Docker and answered that the container does not "
        "exist - the rule then told the operator so and skipped the action")
    assert answer is None, f"unknown must be its own state, not {answer!r}"


def test_an_invalid_name_is_still_a_definite_no(monkeypatch):
    """Counter-check: a name DDC refuses is a real answer, not an unknown."""
    assert asyncio.run(docker_utils.is_container_exists("../etc/passwd")) is False
    assert asyncio.run(docker_utils.is_container_exists("")) is False
