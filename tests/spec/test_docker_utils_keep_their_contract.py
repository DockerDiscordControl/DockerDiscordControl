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
async def test_container_existence_answers_the_unknown(docker_is_gone):
    """It must ANSWER - and since 2026-09-23 the answer is None, not False.

    The contract of this file is unchanged: with Docker gone these functions
    return a value instead of raising. What changed is WHICH value this one
    returns. False meant "the container does not exist", and the automation
    announced exactly that to the operator and skipped the action. Unknown is
    its own answer now. See
    tests/spec/test_a_container_we_could_not_ask_about_is_not_called_missing.py
    """
    result = await docker_is_gone.is_container_exists("minecraft")
    assert result is None


@pytest.mark.asyncio
async def test_container_data_answers_a_list(docker_is_gone):
    result = await docker_is_gone.get_containers_data()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_the_diagnostics_answer_too(docker_is_gone):
    """A diagnostic that raises when the thing is broken is no diagnostic."""
    assert isinstance(await docker_is_gone.compare_container_performance(["minecraft"]), str)
    assert isinstance(await docker_is_gone.test_docker_performance(), dict)


# --------------------------------------------------------------------------- #
# Review E49: two more of the same, and one assertion above that could not fail
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_container_stats_answer_a_pair(docker_is_gone):
    """E49: `get_docker_stats` is documented "Tuple of (CPU percentage, memory
    usage) or (None, None) on error". Its handlers are
    `(DockerException, OSError, RuntimeError, KeyError, ValueError)` - E43
    repaired the function forty lines below it and left this one."""
    result = await docker_is_gone.get_docker_stats("minecraft")

    assert result == (None, None), (
        "get_docker_stats raised where it promises a pair"
    )


@pytest.mark.asyncio
async def test_container_info_answers_none(docker_is_gone):
    """E49: `get_docker_info` is declared `-> Optional[Dict[str, Any]]` and its
    one live caller, the automation service's `_get_running_state`, reads None
    as "could not be determined" and says so in the log."""
    result = await docker_is_gone.get_docker_info("minecraft")

    assert result is None, "get_docker_info raised where it promises None"


@pytest.mark.asyncio
async def test_the_performance_report_reaches_its_containers(docker_is_gone):
    """E49: the assertion in test_the_diagnostics_answer_too calls
    `test_docker_performance()` with no names. That path asks
    `get_containers_data()`, which E43 taught to answer `[]` with Docker gone,
    so the function returns `{}` before its loop ever runs. It could not fail
    on the finding it was written for.

    With names it reaches the loop - and what keeps it alive there is one
    keyword. `get_docker_info` and `get_docker_stats` are awaited through

        asyncio.gather(info_task, stats_task, return_exceptions=True)

    so an unreachable daemon arrives as a VALUE that line 958 records as an
    error string, not as a raise. The per-container handler below it lists only
    `(DockerException, RuntimeError)`; drop `return_exceptions` and the tool
    dies on the first container it was asked to diagnose, which is C57's
    sentence and C57's comment sits right above that handler.

    A scan cannot see that keyword. This test is what stands in for it."""
    result = await docker_is_gone.test_docker_performance(["minecraft", "valheim"],
                                                          iterations=1)

    assert isinstance(result, dict)
    assert result.get('total_containers') == 2, (
        "the report never reached its containers"
    )
    recorded = result.get('container_results', {})
    assert set(recorded) == {"minecraft", "valheim"}, (
        "the report dropped a container it was asked about"
    )
    for name, entry in recorded.items():
        assert entry['errors'], (
            f"{name} was unreachable and the report says nothing about it"
        )


@pytest.mark.asyncio
async def test_the_reason_is_logged(docker_is_gone, caplog):
    """Counter-check: answering must not mean swallowing."""
    import logging

    with caplog.at_level(logging.DEBUG):
        await docker_is_gone.docker_action("minecraft", "stop")

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "the action failed and nothing was logged"
    )
