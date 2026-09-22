# -*- coding: utf-8 -*-
"""The connectivity check must ANSWER that Docker is gone, not raise about it.

THE FINDING (review E15, from a DDC-exception scan hit in ``status_handlers.py``
and ``docker_control.py``): ``DockerConnectivityService.check_connectivity``
exists for exactly one purpose - to say whether the Docker daemon is
reachable - and it returns a ``DockerConnectivityResult`` carrying an
``error_type`` (``socket_error``, ``daemon_error``, ``permission_error`` ...)
so the caller can show the right message.

It handles ``asyncio.TimeoutError``, ``(OSError, IOError)`` and
``(ImportError, AttributeError, RuntimeError)``. What it does not handle is
``DockerConnectionError``, which is what ``get_docker_client_async`` raises
(``docker_client_pool.py:731``) when every way of building a client has
failed - *the* case of "Docker is not reachable", the socket unmounted or the
daemon stopped.

Measured in the running container, with the pool forced to fail:

    RAISED: DockerConnectionError Docker socket not reachable

So the function raised instead of answering, and everything downstream went
with it: ``bulk_fetch_container_status`` calls it with nothing around it, and
the callers of THAT in ``docker_control.py`` and ``status_handlers.py`` list
narrow tuples of their own.

**What was lost is not an abstraction.** DDC has a finished, deliberate answer
for this exact situation - ``create_error_embed_data`` builds the
"🚨 Container Monitoring Unavailable" embed, whose text is translated into all
40 languages and tells the operator to check whether the Docker socket is
mounted. That embed is reached from ``connectivity_result.is_connected``
being False. When the daemon is really gone, that flag was never set, because
the check raised before returning it.
"""

import asyncio
import contextlib

import pytest

from services.exceptions import DockerConnectionError


@pytest.fixture
def pool_that_cannot_connect(monkeypatch):
    """get_docker_client_async as it behaves when every method has failed."""
    import services.docker_service.docker_client_pool as pool

    @contextlib.asynccontextmanager
    async def broken(*_a, **_kw):
        raise DockerConnectionError(
            "Failed to create Docker client: no such file or directory")
        yield  # pragma: no cover

    monkeypatch.setattr(pool, "get_docker_client_async", broken)


def _service():
    from services.infrastructure.docker_connectivity_service import (
        get_docker_connectivity_service)
    return get_docker_connectivity_service()


def _request(**kw):
    from services.infrastructure.docker_connectivity_service import (
        DockerConnectivityRequest)
    return DockerConnectivityRequest(timeout_seconds=3.0, **kw)


@pytest.mark.asyncio
async def test_it_answers_instead_of_raising(pool_that_cannot_connect):
    result = await _service().check_connectivity(_request())

    assert result.is_connected is False, (
        "the daemon is unreachable and the check said it was connected"
    )


@pytest.mark.asyncio
async def test_the_answer_names_a_kind_of_failure(pool_that_cannot_connect):
    """The embed picks its wording from error_type, so it must be set."""
    result = await _service().check_connectivity(_request())

    assert result.error_type, "no error_type - the caller cannot pick a message"
    assert result.error_message, "no error_message - nothing to show the operator"


@pytest.mark.asyncio
async def test_a_missing_socket_is_named_as_a_missing_socket(pool_that_cannot_connect):
    """'no such file or directory' is the unmounted socket, and it has its own text."""
    result = await _service().check_connectivity(_request())

    assert result.error_type == "socket_error", (
        f"the unmounted socket was classified as {result.error_type!r}; the "
        f"operator gets the wrong advice"
    )


@pytest.mark.asyncio
async def test_the_bulk_fetch_above_it_survives(pool_that_cannot_connect, monkeypatch):
    """The real caller: every container comes back as an error, nothing raises."""
    from cogs.status_handlers import StatusHandlersMixin

    handlers = StatusHandlersMixin.__new__(StatusHandlersMixin)
    results = await StatusHandlersMixin.bulk_fetch_container_status(
        handlers, ["alpha", "beta"])

    assert set(results) == {"alpha", "beta"}, (
        "the bulk fetch raised instead of reporting each container as failed"
    )
