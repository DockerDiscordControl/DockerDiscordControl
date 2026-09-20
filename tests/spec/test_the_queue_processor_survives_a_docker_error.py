# -*- coding: utf-8 -*-
"""
THE FINDING (review C33, section 15 F2): one Docker error kills the pool's
queue processor for the rest of the process's life, and nothing notices.

`_process_queue` guards the acquisition with

    except (RuntimeError, ValueError, AttributeError) as e:

and the whole loop with

    except (RuntimeError, ValueError, AttributeError, OSError) as e:

`_create_new_client_async` raises `DockerConnectionError` when Docker is
unreachable through both the configured socket and `docker.from_env()`. That
class derives from `DDCBaseException`, which derives from `Exception` - not
from RuntimeError - so it passes both clauses and leaves the coroutine. The
background task is then finished, and the late-initialisation guard asks

    if self._queue_processor_task is None:

which is False for a task that is merely dead. Nothing ever starts it again.
Every queued request from that moment on waits for its timeout and gets
nothing, for as long as the process runs.

The reviewer marked this "unsure" because they could not see whether the
exception really escapes. It does: `services/exceptions.py` has
`DDCBaseException(Exception)`, measured in review C6 for the same reason in the
scheduler.

Two things were needed, not one: the loop has to survive the error, and a task
that died has to be recognised as dead.

The counter-checks keep both ends: a cancelled processor still stops, and a
request that can be served is still served.
"""

import asyncio
import time

import pytest

from services.docker_service.docker_client_pool import (
    DockerClientService,
    QueueRequest,
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
    return instance


def _queued(timeout=5.0):
    return QueueRequest(request_id="r1", timestamp=time.time(), timeout=timeout,
                        future=asyncio.get_event_loop().create_future())


async def test_a_docker_error_does_not_kill_the_processor(service):
    """THE FINDING: the loop must outlive an unreachable Docker."""
    async def _unreachable():
        raise DockerConnectionError("docker socket unreachable")

    service._try_acquire_client_for_queue = _unreachable
    processor = asyncio.create_task(service._process_queue())

    first = _queued()
    await service._queue.put(first)
    with pytest.raises(DockerConnectionError):
        await asyncio.wait_for(first.future, timeout=2)

    assert not processor.done(), "the processor died on the first error"

    # And it is still able to serve the next request.
    service._try_acquire_client_for_queue = lambda: _served()
    second = _queued()
    await service._queue.put(second)
    assert await asyncio.wait_for(second.future, timeout=2) == "a client"

    processor.cancel()


async def _served():
    return "a client"


async def test_the_waiting_request_is_told(service):
    """A request that cannot be served gets the error - it does not hang until
    its timeout with nothing said."""
    async def _unreachable():
        raise DockerConnectionError("docker socket unreachable")

    service._try_acquire_client_for_queue = _unreachable
    processor = asyncio.create_task(service._process_queue())

    request = _queued()
    await service._queue.put(request)
    with pytest.raises(DockerConnectionError):
        await asyncio.wait_for(request.future, timeout=2)

    processor.cancel()


async def test_an_error_outside_the_acquisition_does_not_kill_it_either(service):
    """The loop's own guard, not the one around the acquisition: something that
    fails AFTER a client was obtained must not end the processor either."""
    def _boom(wait_time):
        raise DockerConnectionError("statistics blew up")

    service._try_acquire_client_for_queue = lambda: _served()
    service._update_queue_stats = _boom
    processor = asyncio.create_task(service._process_queue())

    await service._queue.put(_queued())
    await asyncio.sleep(0.05)
    assert not processor.done(), "the processor died outside the inner guard"

    processor.cancel()


async def test_a_processor_that_died_is_started_again(service):
    """The second half: a finished task is not a running one."""
    async def _already_over():
        return None

    dead = asyncio.create_task(_already_over())
    await dead
    service._queue_processor_task = dead

    service._ensure_queue_processor()

    assert service._queue_processor_task is not dead
    assert not service._queue_processor_task.done()
    service._queue_processor_task.cancel()


async def test_a_cancelled_processor_still_stops(service):
    """COUNTER-CHECK: surviving errors is not surviving cancellation.

    The loop catches CancelledError and breaks out on purpose, so the task
    finishes rather than raising - what matters is that it STOPS.
    """
    processor = asyncio.create_task(service._process_queue())
    await asyncio.sleep(0)
    processor.cancel()

    await asyncio.wait_for(asyncio.shield(asyncio.gather(processor,
                                                         return_exceptions=True)),
                           timeout=2)
    assert processor.done()


async def test_a_normal_request_is_still_served(service):
    """COUNTER-CHECK: the ordinary path is untouched."""
    service._try_acquire_client_for_queue = lambda: _served()
    processor = asyncio.create_task(service._process_queue())

    request = _queued()
    await service._queue.put(request)

    assert await asyncio.wait_for(request.future, timeout=2) == "a client"
    processor.cancel()
