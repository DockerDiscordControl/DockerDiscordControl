# -*- coding: utf-8 -*-
"""The container status service has an error result. It must use it, not raise.

THE FINDING (review E44, services/infrastructure/container_status_service.py):
``get_container_status`` returns a ``ContainerStatusResult`` and has a whole
vocabulary for failure - ``success=False`` with ``error_type`` of
``"service_error"``, ``"data_error"``, ``"not_found"``. Its handlers list
``(AttributeError, ImportError, RuntimeError)`` and
``(ValueError, TypeError, KeyError)``.

``_fetch_container_status`` beneath it opens
``async with get_docker_client_async(...)``, which raises
``DockerConnectionError`` when the daemon cannot be reached at all. That is a
``DockerServiceError``, and it is in none of the five handler tuples in this
file. So with Docker gone the service raises, and the carefully built error
result - the one every caller knows how to read - is never returned.

The BULK path is already safe and was left alone: it gathers with
``return_exceptions=True`` and turns an exception result into a
``ContainerStatusResult`` with ``error_type="exception"``. Two of the three
scan hits in this file were real; that one was not.

Same sentence as reviews E15, E16 and E43. This is the fourth place it has
been found, which is why the scan now runs over the whole repository rather
than over a chosen subset.
"""

import contextlib

import pytest

from services.exceptions import DockerConnectionError


@pytest.fixture
def docker_is_gone(monkeypatch):
    import services.docker_service.docker_client_pool as pool

    @contextlib.asynccontextmanager
    async def broken(*_a, **_kw):
        raise DockerConnectionError("Failed to create Docker client: connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(pool, "get_docker_client_async", broken)


def _service():
    from services.infrastructure.container_status_service import (
        get_container_status_service)
    return get_container_status_service()


def _request(name="minecraft"):
    from services.infrastructure.container_status_service import ContainerStatusRequest
    return ContainerStatusRequest(container_name=name)


@pytest.mark.asyncio
async def test_it_answers_with_a_result(docker_is_gone):
    service = _service()
    service._cache = {}          # a cache hit would hide the point

    result = await service.get_container_status(_request())

    assert result is not None, (
        "the status service raised instead of returning the failure result it "
        "was built to return"
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_the_result_names_the_kind_of_failure(docker_is_gone):
    service = _service()
    service._cache = {}

    result = await service.get_container_status(_request())

    assert result.error_type, "no error_type - the caller cannot tell what happened"
    assert result.error_message, "no error_message"


@pytest.mark.asyncio
async def test_the_bulk_path_still_answers(docker_is_gone):
    """Counter-check: the path that was already safe stays safe."""
    from services.infrastructure.container_status_service import (
        ContainerBulkStatusRequest)

    service = _service()
    service._cache = {}

    result = await service.get_bulk_container_status(
        ContainerBulkStatusRequest(container_names=["alpha", "beta"]))

    assert result is not None
