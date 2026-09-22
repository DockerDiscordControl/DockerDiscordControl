# -*- coding: utf-8 -*-
"""Start, stop and restart must come back with a result. The code says so itself.

THE FINDING (review E45, services/docker_service/docker_action_service.py):
``execute_docker_action`` returns a ``DockerActionResult`` and carries a full
vocabulary for failure - ``error_type`` of ``"invalid_action"``,
``"validation_failed"``, ``"not_found"``. The handler around the whole method
is introduced by this comment:

    # ... so the caller gets a clean failure instead of an exception
    except (RuntimeError, OSError, docker.errors.APIError, docker.errors.DockerException) as e:

The intent is written down. The tuple does not meet it: the method opens
``async with get_docker_client_async(...)``, which raises
``DockerConnectionError`` when the daemon cannot be reached at all, and that is
a ``DockerServiceError`` - in none of the tuples here.

So with Docker gone, the one method that every start, stop and restart passes
through gave its callers an exception where its own comment promises a clean
failure. Those callers are the admin overview's bulk buttons and the scheduler
at four in the morning.

Fourth file, same sentence as E15, E16, E43 and E44 - and the first where the
code had already written down what it was supposed to do.
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


def _request(action="stop", name="minecraft"):
    from services.docker_service.docker_action_service import DockerActionRequest
    return DockerActionRequest(container_name=name, action=action)


def _service():
    from services.docker_service.docker_action_service import get_docker_action_service
    return get_docker_action_service()


@pytest.mark.asyncio
async def test_stopping_a_container_answers_with_a_result(docker_is_gone):
    result = await _service().execute_docker_action(_request("stop"))

    assert result is not None, (
        "the method whose own comment promises 'a clean failure instead of an "
        "exception' raised at its caller"
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_the_result_names_the_kind_of_failure(docker_is_gone):
    result = await _service().execute_docker_action(_request("restart"))

    assert result.error_type, "no error_type - the caller cannot tell what happened"
    assert result.error_message


@pytest.mark.asyncio
async def test_a_rejected_action_still_answers_the_old_way(docker_is_gone):
    """Counter-check: the validation failures that already worked still work."""
    result = await _service().execute_docker_action(_request("selfdestruct"))

    assert result.success is False
    assert result.error_type == "invalid_action"
