# -*- coding: utf-8 -*-
"""
THE FINDING (review C32, section 15 F3): the pool statistics count a request
that failed as one that succeeded.

`get_pool_stats_service` computes

    successful_requests = stats['total_requests'] - stats['timeouts']
    failed_requests     = stats['timeouts']

so "successful" is really "everything that was not a timeout". But a request
can fail for other reasons: `get_docker_client_service` catches
`(RuntimeError, ValueError, AttributeError, OSError)` and returns
`success=False, error_type="service_error"` - and nothing on that path
increments any counter. The request was already counted in `total_requests`,
so it lands in `successful_requests` by subtraction. The number an operator
reads to judge whether the Docker connection is healthy is wrong in the one
direction that matters: it looks better than it is.

Failures are counted where they happen now, and `successful_requests` is
`total - timeouts - other failures`.

The counter-checks keep the arithmetic honest from both sides: the three
numbers must always add up to the total, and a run in which nothing fails must
still report everything as successful.
"""

import pytest

from services.docker_service.docker_client_pool import (
    DockerClientService,
    DockerClientRequest,
    DockerPoolStatsRequest,
)


@pytest.fixture
def service():
    """A pool that is not attached to a running loop or a real Docker."""
    instance = DockerClientService.__new__(DockerClientService)
    instance._pool = []
    instance._in_use = []
    instance._max_connections = 3
    instance._queue_processor_task = None
    instance._client_available_event = None
    instance._queue_stats = {
        'total_requests': 0,
        'queued_requests': 0,
        'max_queue_size': 0,
        'average_wait_time': 0.0,
        'timeouts': 0,
        'failures': 0,
    }

    class _Queue:
        @staticmethod
        def qsize():
            return 0

    instance._queue = _Queue()
    return instance


async def _stats(service):
    return await service.get_pool_stats_service(DockerPoolStatsRequest())


async def test_a_service_error_is_not_a_success(service):
    """THE FINDING: one request, it failed, so zero succeeded."""
    service._queue_stats['total_requests'] = 1
    service._queue_stats['failures'] = 1

    result = await _stats(service)

    assert result.successful_requests == 0
    assert result.failed_requests == 1


async def test_the_numbers_add_up(service):
    """Whatever the mix, the three always come to the total."""
    service._queue_stats['total_requests'] = 10
    service._queue_stats['timeouts'] = 2
    service._queue_stats['failures'] = 3

    result = await _stats(service)

    assert result.successful_requests == 5
    assert result.timeout_requests == 2
    assert result.failed_requests == 5   # timeouts and other failures together
    assert result.successful_requests + result.failed_requests == result.total_requests


async def test_a_clean_run_still_reports_everything_as_successful(service):
    """COUNTER-CHECK: nothing failed, so nothing is subtracted."""
    service._queue_stats['total_requests'] = 7

    result = await _stats(service)

    assert result.successful_requests == 7
    assert result.failed_requests == 0
    assert result.timeout_requests == 0


async def test_a_failure_is_counted_where_it_happens(service):
    """The counter has to be reached by the REAL failure path, not just set by
    a test. A service error inside get_docker_client_service lands in its outer
    handler, and that is where the count has to happen."""
    async def _boom():
        # OSError, deliberately: the fast path's own except catches only
        # RuntimeError/ValueError/AttributeError, so this reaches the outer
        # handler - which is the one that returns error_type="service_error".
        raise OSError("docker socket vanished")

    service._try_immediate_acquire = _boom

    result = await service.get_docker_client_service(DockerClientRequest())

    assert result.success is False
    assert result.error_type == "service_error"
    assert service._queue_stats['failures'] == 1
