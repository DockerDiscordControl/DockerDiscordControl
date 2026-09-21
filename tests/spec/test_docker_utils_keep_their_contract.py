# -*- coding: utf-8 -*-
"""When Docker is unreachable these must answer, not raise. Every caller expects a value.

THE FINDING (review E43, services/docker_service/docker_utils.py): seven
functions open with ``async with get_docker_client_async(...)`` and declare a
return type - ``bool``, ``List[Dict]``, ``dict``, ``str``. Their handlers list
``docker.errors.NotFound``, ``asyncio.TimeoutError`` and
``(DockerException, APIError, OSError, RuntimeError)``.

``get_docker_client_async`` raises ``DockerConnectionError`` when every way of
building a client has failed - the socket unmounted, the daemon stopped
(``docker_client_pool.py:731``). It is a ``DockerServiceError``, a
``DDCBaseException``, and it is in none of those tuples. So with Docker gone
these functions RAISE where their signature promises a value.

``docker_action`` is the one that matters: it is what start, stop and restart
go through, from the buttons and from the scheduled tasks at four in the
morning. Every caller reads its answer as "did it work"; an exception is not
an answer.

This is the same sentence as reviews E15 and E16, found by running the
DDC-exception scan over the WHOLE repository rather than only over the files
no pass had covered. E12 to E16 came from scanning 22 files; this came from
scanning 183.

The three diagnostics in the list are here too, because a diagnostic that
raises when the thing it diagnoses is broken is the least useful moment for it
to stop answering.
"""

import contextlib

import pytest

from services.exceptions import DockerConnectionError


@pytest.fixture
def docker_is_gone(monkeypatch):
    """The pool as it behaves when the daemon cannot be reached at all."""
    import services.docker_service.docker_utils as docker_utils

    @contextlib.asynccontextmanager
    async def broken(*_a, **_kw):
        raise DockerConnectionError("Failed to create Docker client: connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(docker_utils, "get_docker_client_async", broken)
    return docker_utils


@pytest.mark.asyncio
async def test_a_container_action_answers_false(docker_is_gone):
    """start/stop/restart - the most consequential of the seven."""
    result = await docker_is_gone.docker_action("minecraft", "stop")

    assert result is False, (
        "pressing Stop with Docker unreachable raised instead of answering "
        "False; every caller reads this as 'did it work'"
    )


@pytest.mark.asyncio
async def test_listing_containers_answers_a_list(docker_is_gone):
    result = await docker_is_gone.list_docker_containers()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_container_existence_answers_a_bool(docker_is_gone):
    result = await docker_is_gone.is_container_exists("minecraft")
    assert result is False


@pytest.mark.asyncio
async def test_container_data_answers_a_list(docker_is_gone):
    result = await docker_is_gone.get_containers_data()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_the_diagnostics_answer_too(docker_is_gone):
    """A diagnostic that raises when the thing is broken is no diagnostic."""
    assert isinstance(await docker_is_gone.analyze_docker_stats_performance("minecraft"), dict)
    assert isinstance(await docker_is_gone.compare_container_performance(["minecraft"]), str)
    assert isinstance(await docker_is_gone.test_docker_performance(), dict)


@pytest.mark.asyncio
async def test_the_reason_is_logged(docker_is_gone, caplog):
    """Counter-check: answering must not mean swallowing."""
    import logging

    with caplog.at_level(logging.DEBUG):
        await docker_is_gone.docker_action("minecraft", "stop")

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "the action failed and nothing was logged"
    )
