# -*- coding: utf-8 -*-
"""
THE FINDING (review C6, section 27 F1): ``_execute_task_batch`` writes

    self._executed_runs[task.task_id] = task.next_run_ts

BEFORE it awaits ``execute_task(task)``. The entry is never corrected when the
execution does not happen. ``execute_task`` advances ``next_run_ts`` itself on
every path it handles, so the mark is harmless there - but it handles only
``ImportError, AttributeError, RuntimeError, ValueError, TypeError, KeyError``
and ``asyncio.TimeoutError``. Every DDC exception escapes: ``DDCBaseException``
derives straight from ``Exception``, so a ``DockerConnectionError`` from the
Docker action service flies past it. Then ``next_run_ts`` has NOT moved, the
save that would persist it is skipped, and on the next cycle the guard at
scheduler_service.py:393 finds ``_executed_runs[id] == task.next_run_ts`` and
skips the occurrence - as "already executed".

The same exception also escapes ``execute_single_task``'s own except list, and
``asyncio.gather(..., return_exceptions=True)`` then drops it without a word.
So a task that crashed leaves no ERROR line at all; the only trace is a DEBUG
"already executed ... skipping" that looks exactly like a task that ran fine.

WHAT THE REPORT GOT WRONG: it says the task is skipped "forever". It is not.
After MISSED_RUN_GRACE_SECONDS (300 s by default) the missed-run branch at
scheduler_service.py:379 reschedules it, and a recurring task runs again at its
next occurrence. What is real: the due occurrence is silently dropped, and for
a ONE-TIME task the recovery is the damage - ``reschedule_missed_task``
deactivates it with "Missed scheduled time ... (scheduler not running); not
executed", which is false twice over: the scheduler was running, and it was the
attempt that failed, not the clock.

The counter-check (test_a_task_that_ran_is_not_run_twice) keeps the guard the
_executed_runs entry exists for: an occurrence that really did execute must not
be executed a second time in the same cycle window.
"""

from __future__ import annotations

import logging
import time as _time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.exceptions import DockerConnectionError
from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling import scheduler_service as ss
from services.scheduling.scheduler import (
    CYCLE_DAILY,
    CYCLE_ONCE,
    ScheduledTask,
    load_tasks,
    save_tasks,
)


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    monkeypatch.setattr(scheduler_mod, "_get_disallowed_action_reason", lambda c, a: None)
    monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)
    monkeypatch.setattr(scheduler_mod, "_get_container_stop_timeout", AsyncMock(return_value=None))
    yield tmp_path
    scheduler_runtime.reset_scheduler_runtime()


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    clock = {"now": _time.time()}
    monkeypatch.setattr(ss, "time", SimpleNamespace(time=lambda: clock["now"]))
    monkeypatch.setattr(ss, "MISSED_RUN_GRACE_SECONDS", 300)
    monkeypatch.setattr(ss, "CHECK_INTERVAL", 60)
    monkeypatch.setattr(ss, "BATCH_PAUSE_SECONDS", 0)
    return clock


def _due_task(cycle=CYCLE_DAILY, task_id="t1", **kwargs):
    params = {"hour": 4, "minute": 0}
    if cycle == CYCLE_ONCE:
        params.update(year=2099, month=1, day=1)
    params.update(kwargs)
    return ScheduledTask(task_id=task_id, container_name="c1", action="restart",
                         cycle=cycle, timezone_str="UTC", **params)


def _store(task, clock):
    task.next_run_ts = clock["now"] - 1
    assert save_tasks([task]) is True


async def test_an_occurrence_that_crashed_is_tried_again(monkeypatch, _clock):
    """THE FINDING: a DDC exception must not count as a completed run."""
    _store(_due_task(), _clock)
    attempts = []

    async def _crashing_execute(task):
        attempts.append(task.task_id)
        raise DockerConnectionError("Docker daemon unreachable")

    monkeypatch.setattr(ss, "execute_task", _crashing_execute)
    service = ss.SchedulerService()

    await service._check_and_execute_tasks()
    _clock["now"] += 60
    await service._check_and_execute_tasks()

    assert attempts == ["t1", "t1"], "the crashed occurrence was skipped as 'already executed'"


async def test_a_one_time_task_that_crashed_is_not_written_off(monkeypatch, _clock):
    """A one-time task must still get its run when the next attempt works -
    instead of being deactivated with 'scheduler not running'."""
    _store(_due_task(cycle=CYCLE_ONCE), _clock)
    attempts = []

    async def _flaky_execute(task):
        attempts.append(task.task_id)
        if len(attempts) == 1:
            raise DockerConnectionError("Docker daemon unreachable")
        task.last_run_success = True
        task.update_after_execution()

    monkeypatch.setattr(ss, "execute_task", _flaky_execute)
    service = ss.SchedulerService()

    await service._check_and_execute_tasks()
    _clock["now"] += 60
    await service._check_and_execute_tasks()

    assert attempts == ["t1", "t1"]
    stored = load_tasks()[0]
    assert "scheduler not running" not in (stored.last_run_error or "")


async def test_a_crashed_task_leaves_a_trace(monkeypatch, _clock, caplog):
    """An exception the batch does not know must be logged, not swallowed by
    asyncio.gather(return_exceptions=True)."""
    _store(_due_task(), _clock)

    async def _crashing_execute(task):
        raise DockerConnectionError("Docker daemon unreachable")

    monkeypatch.setattr(ss, "execute_task", _crashing_execute)

    with caplog.at_level(logging.ERROR):
        await ss.SchedulerService()._check_and_execute_tasks()

    assert any("t1" in r.message or "c1" in r.message
               for r in caplog.records if r.levelno >= logging.ERROR), \
        "the crash left no error line at all"


async def test_a_task_that_ran_is_not_run_twice(monkeypatch, _clock):
    """COUNTER-CHECK: the _executed_runs guard must keep doing its job. A task
    whose reschedule could not be saved must not run again for the same
    occurrence."""
    _store(_due_task(), _clock)
    attempts = []

    async def _execute_without_saving(task):
        attempts.append(task.task_id)  # deliberately does NOT advance next_run_ts

    monkeypatch.setattr(ss, "execute_task", _execute_without_saving)
    service = ss.SchedulerService()

    await service._check_and_execute_tasks()
    _clock["now"] += 60
    await service._check_and_execute_tasks()

    assert attempts == ["t1"]


async def test_the_next_occurrence_still_runs(monkeypatch, _clock):
    """COUNTER-CHECK: the mark must name the occurrence that ran, not the one
    that comes next. Recording task.next_run_ts AFTER execute_task advanced it
    would block the following occurrence instead of the finished one."""
    _store(_due_task(), _clock)
    attempts = []

    async def _execute_and_reschedule(task):
        attempts.append(task.next_run_ts)
        task.last_run_success = True
        task.update_after_execution()

    monkeypatch.setattr(ss, "execute_task", _execute_and_reschedule)
    service = ss.SchedulerService()

    await service._check_and_execute_tasks()
    _clock["now"] = load_tasks()[0].next_run_ts + 1
    await service._check_and_execute_tasks()

    assert len(attempts) == 2, "the task's next occurrence was skipped as 'already executed'"
