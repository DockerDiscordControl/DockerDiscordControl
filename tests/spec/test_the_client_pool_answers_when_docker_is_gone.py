# -*- coding: utf-8 -*-
"""
THE FINDING (review E48): `get_docker_client_service` is declared

    async def get_docker_client_service(self, request) -> DockerClientResult

and `DockerClientResult` carries `success`, `error_message` and `error_type`
for precisely one purpose: to hand a failure back as a value. When Docker is
unreachable it raises instead, on BOTH of its paths.

`_create_new_client_async` raises `DockerConnectionError`, which derives from
`DDCBaseException` -> `Exception`, not from `RuntimeError`. C33 measured that
and wrote it down in this same file. Neither handler here was told:

    fast path   except (RuntimeError, ValueError, AttributeError)
    the method  except (RuntimeError, ValueError, AttributeError, OSError)

So the fast path's `DockerConnectionError` passes the inner clause, passes the
outer clause, and leaves the method. The request is never queued, the failure
is never counted in `_queue_stats['failures']`, and the caller gets an
exception where its own code is reading `result.success`.

The queue path is the same sentence one step later. C33 taught the processor
to hand the error to the waiting request - `request.future.set_exception(e)` -
so `await asyncio.wait_for(future, ...)` re-raises the `DockerConnectionError`
right here, into the same outer clause that does not catch it. C33 made the
waiting request be told, and the telling then walked out of the building.

One clause on the method covers both, because both land in it.

The counter-checks keep what was already right: a timeout is still a timeout
result, and a request that can be served is still served.
"""

import asyncio
import time

import pytest

from services.docker_service.docker_client_pool import (
    DockerClientRequest,
    DockerClientService,
)
from services.exceptions import DockerConnectionError


@pytest.fixture
def service():
    instance = DockerClientService.__new__(DockerClientService)
    instance._pool = []
    instance._in_use = []
    instance._max_connections = 3
    instance._queue = asyncio.Queue()
    instance._queue_processor_task = None
    instance._client_available_event = asyncio.Event()
    instance._async_lock = asyncio.Lock()
    instance._queue_stats = {
        'total_requests': 0, 'queued_requests': 0, 'max_queue_size': 0,
        'average_wait_time': 0.0, 'timeouts': 0, 'failures': 0,
    }
    instance._start_queue_processor = lambda: None
    instance._ensure_queue_processor = lambda: None
    return instance


async def test_the_fast_path_answers_instead_of_raising(service):
    """THE FINDING: Docker is unreachable, and the method that promises a
    result has to produce one."""
    async def _unreachable():
        raise DockerConnectionError("docker socket unreachable")

    service._try_immediate_acquire = _unreachable

    result = await service.get_docker_client_service(
        DockerClientRequest(operation="stats", timeout_seconds=0.5)
    )

    assert result.success is False
    assert result.client is None
    assert result.error_message, "the failure has to carry a sentence"
    assert "unreachable" in result.error_message.lower()


async def test_the_failure_is_counted(service):
    """A failure the pool never counts is a failure its own statistics deny."""
    async def _unreachable():
        raise DockerConnectionError("docker socket unreachable")

    service._try_immediate_acquire = _unreachable

    await service.get_docker_client_service(
        DockerClientRequest(operation="stats", timeout_seconds=0.5)
    )

    assert service._queue_stats['failures'] == 1


async def test_the_queue_path_answers_instead_of_raising(service):
    """C33 taught the processor to tell the waiting request what happened.
    The telling must not then walk out of the method."""
    async def _no_fast_path():
        return None

    service._try_immediate_acquire = _no_fast_path

    async def _fail_whatever_is_queued():
        queued = await service._queue.get()
        queued.future.set_exception(DockerConnectionError("docker socket unreachable"))
        service._queue.task_done()

    processor = asyncio.create_task(_fail_whatever_is_queued())
    try:
        result = await service.get_docker_client_service(
            DockerClientRequest(operation="stats", timeout_seconds=0.5)
        )
    finally:
        processor.cancel()

    assert result.success is False
    assert result.client is None
    assert "unreachable" in (result.error_message or "").lower()


async def test_a_timeout_is_still_a_timeout(service, monkeypatch):
    """COUNTER-CHECK: the failure that already answered correctly keeps its
    own name.

    The queue timeout is `max(90.0, ...)`, so waiting it out is not something a
    test suite can do. The wait is made to time out at once instead."""
    import services.docker_service.docker_client_pool as pool_module

    async def _no_fast_path():
        return None

    async def _times_out(awaitable, timeout=None):
        if asyncio.isfuture(awaitable):
            awaitable.cancel()
        raise asyncio.TimeoutError()

    service._try_immediate_acquire = _no_fast_path
    monkeypatch.setattr(pool_module.asyncio, "wait_for", _times_out)

    result = await service.get_docker_client_service(
        DockerClientRequest(operation="stats", timeout_seconds=0.5)
    )

    assert result.success is False
    assert result.error_type == "timeout"


async def test_a_request_that_can_be_served_is_still_served(service):
    """COUNTER-CHECK: the happy path is untouched."""
    async def _fast():
        return "a client"

    service._try_immediate_acquire = _fast

    result = await service.get_docker_client_service(
        DockerClientRequest(operation="stats", timeout_seconds=0.5)
    )

    assert result.success is True
    assert result.client == "a client"
