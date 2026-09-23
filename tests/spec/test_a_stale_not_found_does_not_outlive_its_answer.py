# -*- coding: utf-8 -*-
""""Not found" means the LAST query said so, not that one once did.

THE FINDING (independent review of the Docker layer, 2026-09-23):
_not_found_logged is a process-lifetime set. A container is added to it on
docker.errors.NotFound, and removed again ONLY by a later SUCCESSFUL query.
Every other failure - a timeout, an unreachable daemon - leaves it in place.

is_container_not_found's own docstring says the flag means "the LAST Docker
query for this container answered NotFound". With that clearing rule it does
not.

    1. the container is removed        -> one poll marks it
    2. it is RECREATED                 -> an Unraid auto-update does exactly this
    3. the next queries time out       -> never succeed, never clear the flag
    4. bulk_fetch_container_status sees info is None AND the stale flag, and
       builds not_found_result(...) - which carries success=True, i.e. a
       DETERMINED state. It is cached, rendered as "❓ … not found", and
       counted as neither online nor offline.

The operator is shown "not found" as a fact, about a container that exists and
is probably running, on the strength of a question DDC could not get an answer
to. Three lines below, the same function refuses to call an unanswered query
"offline" for exactly this reason (Z3) - the not-found branch runs first and
walks past it.

WHAT CHANGES: a query that fails for any other reason clears the flag too. The
flag then means what its docstring says - the last query answered NotFound -
and an unanswerable query falls through to the "could not be asked" branch that
already exists and is already honest.

HOW THIS TEST CAN FAIL: it marks a container as not found, then lets the next
query fail with a timeout, and asks. A "yes, not found" is red.

COUNTER-CHECK (2026-09-23): red before - the flag survived the timeout and the
container would have been rendered as not found. The other tests keep the flag
useful: a real NotFound still sets it, and a success still clears it.
"""

import asyncio
from unittest.mock import MagicMock

import docker
import pytest

from services.exceptions import DockerServiceError
from services.infrastructure.container_status_service import (
    ContainerStatusRequest, ContainerStatusService)

NAME = "minecraft"


@pytest.fixture
def service(monkeypatch):
    return ContainerStatusService()


def _answer_with(service, monkeypatch, behaviour):
    """Make the next query behave like `behaviour` (raise, or return a result)."""
    class _Client:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args):
            return False

    # Imported INSIDE _fetch_container_status from docker_client_pool, so that
    # is the module to replace it in.
    import services.docker_service.docker_client_pool as pool

    monkeypatch.setattr(pool, "get_docker_client_async", lambda **kwargs: _Client())
    monkeypatch.setattr(service, "_query_container_sync",
                        lambda client, request, start: behaviour())


def _ask(service):
    return asyncio.run(service._fetch_container_status(
        ContainerStatusRequest(container_name=NAME)))


def _raise(error):
    def behaviour():
        raise error

    return behaviour


def _succeed():
    from services.infrastructure.container_status_service import ContainerStatusResult

    return lambda: ContainerStatusResult(success=True, container_name=NAME)


def test_a_real_not_found_still_sets_the_flag(service, monkeypatch):
    """Counter-check: the flag has to work at all."""
    _answer_with(service, monkeypatch, _raise(docker.errors.NotFound("no such container")))
    _ask(service)

    assert service.is_container_not_found(NAME) is True


def test_a_success_still_clears_it(service, monkeypatch):
    """Counter-check: a recreated container must stop being 'not found'."""
    _answer_with(service, monkeypatch, _raise(docker.errors.NotFound("gone")))
    _ask(service)

    _answer_with(service, monkeypatch, _succeed())
    _ask(service)

    assert service.is_container_not_found(NAME) is False


@pytest.mark.parametrize("error", [
    pytest.param(DockerServiceError("the proxy is not answering"), id="proxy-down"),
    pytest.param(OSError("socket gone"), id="socket-gone"),
    pytest.param(RuntimeError("read timed out"), id="timeout"),
])
def test_a_query_that_could_not_be_answered_clears_it(service, monkeypatch, error):
    """THE FINDING: the old verdict outlived the answer that produced it."""
    _answer_with(service, monkeypatch, _raise(docker.errors.NotFound("gone")))
    _ask(service)
    assert service.is_container_not_found(NAME) is True

    _answer_with(service, monkeypatch, _raise(error))
    _ask(service)

    assert service.is_container_not_found(NAME) is False, (
        "a container DDC could not reach is still reported as 'not found' on "
        "the strength of an older answer - and that verdict is shown as a fact")


def test_a_container_never_seen_is_not_not_found(service):
    """Counter-check: the flag says nothing about an unknown name."""
    assert service.is_container_not_found("never-asked-about") is False
