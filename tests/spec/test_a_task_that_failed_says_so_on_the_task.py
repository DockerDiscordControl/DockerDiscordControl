# -*- coding: utf-8 -*-
"""A scheduled task that failed says so on the task, not only in the log.

THE FINDING (review E3, section 26 - one of the three sections NEITHER review
pass ever looked at). `execute_task` records every failure it knows about on
the task itself:

    task.last_run_success = False
    task.last_run_error = <what went wrong>
    task.update_after_execution()
    _persist_executed_task(task)

...for a timeout, for "Docker action failed", for a data error and for a
dependency error. Its handlers list `(ImportError, AttributeError,
RuntimeError)` and `(ValueError, TypeError, KeyError)`.

The one thing a scheduled container action realistically fails with is in
neither list. The chain is reachable and was checked link by link:

    execute_task -> docker_action_service_first -> execute_docker_action
                 -> get_docker_client_async  ->  raise DockerConnectionError

and `DockerConnectionError` -> `DockerServiceError` -> **DDCBaseException** ->
Exception. Not an OSError, not a RuntimeError. It passes every handler on the
way out, including both of `execute_docker_action`'s own.

What the operator sees: the Docker daemon is unreachable, the nightly restart
does not happen - and the task in the panel shows no error at all. It still
shows whatever it showed last time, quite possibly a success. The failure
exists only as a line in the log, which C6 made sure of; C6 fixed the silence
in the LOG and left the silence on the TASK.

The repair follows the four handlers that were already there rather than
inventing a fifth behaviour: record it, move the task on to its next run, and
answer False. A connection error is not more retryable than "Docker action
failed", and that one has never been retried immediately either.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import services.scheduling.runtime as scheduler_runtime
import services.scheduling.scheduler as scheduler_mod
from services.exceptions import DockerConnectionError
from services.scheduling.scheduler import ScheduledTask


@pytest.fixture
def task(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    monkeypatch.setattr(scheduler_mod, "_get_disallowed_action_reason", lambda c, a: None)
    monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kwargs: None)
    monkeypatch.setattr(scheduler_mod, "_persist_executed_task", lambda t: True)

    async def _no_wait(_seconds):
        return None

    monkeypatch.setattr(scheduler_mod.asyncio, "sleep", _no_wait)

    # Reaching the real Docker daemon here would take 15 s per test and is not
    # what is under examination; the timeout lookup has its own handler.
    async def _plain_timeout(task, timeout):
        return timeout

    monkeypatch.setattr(scheduler_mod, "_get_action_timeout", _plain_timeout)

    scheduled = ScheduledTask(container_name="valheim", action="restart",
                              cycle="daily", hour=4, minute=0,
                              timezone_str="Europe/Berlin")
    scheduled.last_run_success = True          # the last run went fine
    scheduled.last_run_error = None
    yield scheduled
    scheduler_runtime.reset_scheduler_runtime()


def _docker_raises(monkeypatch, error):
    # scheduler.py binds this name at import (line 27), so the patch goes to
    # the scheduler's own module - patching the action module does nothing and
    # the first version of this test reached the real Docker daemon.
    monkeypatch.setattr(scheduler_mod, "docker_action_service_first",
                        AsyncMock(side_effect=error))


async def test_an_unreachable_docker_is_written_on_the_task(task, monkeypatch):
    """The finding: the one error this really fails with left no trace."""
    _docker_raises(monkeypatch, DockerConnectionError("Docker daemon unreachable"))

    result = await scheduler_mod.execute_task(task)

    assert result is False
    assert task.last_run_success is False, (
        "the task still says its last run succeeded, and the panel shows that"
    )
    assert task.last_run_error, "the task carries no reason at all"
    assert "unreachable" in str(task.last_run_error).lower(), task.last_run_error


async def test_the_task_moves_on_to_its_next_run(task, monkeypatch):
    """Like every other failure here - the run is written off, not repeated.

    Checked through last_run_ts and the status, not through next_run_ts: for a
    daily task at 04:00, "the next 04:00" computed twice in the same second is
    the same number, so comparing it proves nothing. The first version of this
    test compared it and was wrong about arithmetic, not about the rule.
    """
    _docker_raises(monkeypatch, DockerConnectionError("Docker daemon unreachable"))
    task.last_run_ts = None

    await scheduler_mod.execute_task(task)

    assert task.last_run_ts is not None, (
        "the run was not written off at all, so the scheduler tries this task "
        "again on every cycle for as long as Docker is down"
    )
    assert task.status == "pending"


async def test_a_plain_failure_still_behaves_as_before(task, monkeypatch):
    """The counter-case: the handlers that were already there keep working."""
    monkeypatch.setattr(scheduler_mod, "docker_action_service_first",
                        AsyncMock(return_value=False))

    result = await scheduler_mod.execute_task(task)

    assert result is False
    assert task.last_run_success is False
    assert "Docker action failed" in str(task.last_run_error)


async def test_a_run_that_works_still_says_so(task, monkeypatch):
    """And the healthy path is untouched."""
    monkeypatch.setattr(scheduler_mod, "docker_action_service_first",
                        AsyncMock(return_value=True))
    # The polling loop after a successful action looks the server up; it is
    # imported inside execute_task, so the patch goes to its own module.
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: SimpleNamespace(get_all_servers=lambda: []))

    result = await scheduler_mod.execute_task(task)

    assert result is True
    assert task.last_run_success is True
    assert task.last_run_error is None
