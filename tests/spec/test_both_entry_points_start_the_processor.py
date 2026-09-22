# -*- coding: utf-8 -*-
"""
THE FINDING (review C33b, section 15 F1): the pool has two public entry points
and only one of them makes sure anyone is draining the queue.

`DockerClientService` starts its queue processor in the constructor. When the
singleton is built at a moment with no running event loop - which is what the
synchronous module-level factory does during startup - that attempt catches the
RuntimeError and leaves `_queue_processor_task` at None.

`get_client_async()` notices and starts the processor on first async use.
`get_docker_client_service()` does not. A caller that only ever uses the second
one, and hits the pool-full case, falls through to `await self._queue.put(...)`
with nobody draining that queue: the request sits there until the ~90 second
queue timeout expires and is then reported as `error_type="timeout"` - although
no Docker call was ever attempted and no timeout ever happened.

The reviewer marked this "unsure" because they could not see when the singleton
is first built. That does not change the asymmetry: two entry points to the
same queue, one of which quietly relies on the other having been used first.

Review C33 already made `_ensure_queue_processor()` the one place that decides
whether a processor is running. This is the second entry point asking it.

The counter-check (test_an_already_running_processor_is_not_replaced) keeps the
call from restarting a healthy processor on every request.
"""

import asyncio
import time

import pytest

from services.docker_service.docker_client_pool import (
    DockerClientRequest,
    DockerClientService,
)


@pytest.fixture
def service():
    instance = DockerClientService.__new__(DockerClientService)
    instance._pool = []
    instance._in_use = ["busy"] * 3          # pool is full -> the queue path
    instance._max_connections = 3
    instance._queue = asyncio.Queue()
    instance._queue_processor_task = None    # built without a running loop
    instance._client_available_event = None
    instance._async_lock = asyncio.Lock()
    instance._queue_stats = {
        'total_requests': 0, 'queued_requests': 0, 'max_queue_size': 0,
        'average_wait_time': 0.0, 'timeouts': 0, 'failures': 0,
    }
    return instance


async def test_the_sync_entry_point_starts_the_processor(service):
    """THE FINDING: a queued request needs someone to take it off the queue."""
    async def _immediately(): 
        return None

    service._try_immediate_acquire = _immediately
    service._try_acquire_client_for_queue = _a_client

    result = await asyncio.wait_for(
        service.get_docker_client_service(DockerClientRequest(timeout_seconds=2)),
        timeout=5)

    assert result.success is True, result.error_message
    if service._queue_processor_task:
        service._queue_processor_task.cancel()


async def test_a_queued_request_is_not_reported_as_a_timeout(service):
    """What the caller was told: a timeout that never happened."""
    async def _immediately():
        return None

    service._try_immediate_acquire = _immediately
    service._try_acquire_client_for_queue = _a_client

    result = await asyncio.wait_for(
        service.get_docker_client_service(DockerClientRequest(timeout_seconds=2)),
        timeout=5)

    assert result.error_type != "timeout"
    if service._queue_processor_task:
        service._queue_processor_task.cancel()


async def test_an_already_running_processor_is_not_replaced(service):
    """COUNTER-CHECK: a healthy processor must not be restarted per request."""
    async def _forever():
        await asyncio.sleep(60)

    running = asyncio.create_task(_forever())
    service._queue_processor_task = running

    service._ensure_queue_processor()

    assert service._queue_processor_task is running
    running.cancel()


async def _a_client():
    return "a client"
