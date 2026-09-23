# -*- coding: utf-8 -*-
"""A task that is running right now was not missed.

THE FINDING: in the scheduler's cycle the missed-run check comes BEFORE the
"already running" check. A task's next_run_ts only moves once its execution
returns, so while a slow action is still running - a container with a long
stop timeout, a Docker call that hangs - the same occurrence keeps looking
due. After the grace period (300 s, five cycles) the cycle calls
reschedule_missed_task on it: a one-time task is deactivated with
"Missed scheduled time ...; not executed" while it is executing, and a
recurring one is pushed to its next occurrence from underneath the run whose
result is written afterwards.

Running is not missing. The "already running" check and the "already
executed" check come first.

COUNTER-CHECK (2026-09-23): red before - reschedule_missed_task was called
for a task in active_tasks. test_a_task_nobody_is_running_is_still_rescheduled
holds the other side: never rescheduling would be green without it, and that
was the bug this check was written for (review R5-3).
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from services.scheduling import scheduler_service as module


def _task(task_id, due_secs_ago, last_run_ts=None):
    # last_run_ts is part of a real task and the cycle reads it: execute_task
    # writes the occurrence down before it acts, so a last run at or after the
    # due time means this one was already begun
    # (tests/spec/test_a_restart_does_not_run_a_task_twice.py).
    return SimpleNamespace(
        task_id=task_id, container_name="nginx", action="restart", last_run_ts=last_run_ts,
        is_active=True, next_run_ts=time.time() - due_secs_ago, cycle="daily")


@pytest.fixture
def service(monkeypatch):
    """A scheduler whose cycle reads the tasks we hand it and runs nothing."""
    rescheduled = []
    executed = []

    service = module.SchedulerService()
    monkeypatch.setattr(module, "reschedule_missed_task",
                        lambda task: rescheduled.append(task.task_id))
    monkeypatch.setattr(module, "load_tasks", lambda: list(service._tasks_for_test))

    async def no_system_tasks():
        return None

    async def batch(tasks):
        executed.extend(t.task_id for t in tasks)

    monkeypatch.setattr(service, "_check_system_tasks", no_system_tasks)
    monkeypatch.setattr(service, "_execute_task_batch", batch)
    service.rescheduled = rescheduled
    service.executed = executed
    return service


def test_a_task_that_is_running_is_left_alone(service):
    """The long run is still in flight; its occurrence has not moved."""
    late = _task("slow", due_secs_ago=module.MISSED_RUN_GRACE_SECONDS + 120)
    service._tasks_for_test = [late]
    service.active_tasks.add("slow")

    asyncio.run(service._check_and_execute_tasks())

    assert service.rescheduled == [], (
        "a task was written off as missed while it was running")
    assert service.executed == [], "and it must not be started a second time either"


def test_a_task_whose_run_already_happened_is_left_alone(service):
    """The same for a run whose reschedule could not be saved."""
    late = _task("done", due_secs_ago=module.MISSED_RUN_GRACE_SECONDS + 120)
    service._tasks_for_test = [late]
    service._executed_runs["done"] = late.next_run_ts

    asyncio.run(service._check_and_execute_tasks())

    assert service.rescheduled == []


def test_a_task_nobody_is_running_is_still_rescheduled(service):
    """Counter-check: the case the missed-run handling exists for."""
    late = _task("forgotten", due_secs_ago=module.MISSED_RUN_GRACE_SECONDS + 120)
    service._tasks_for_test = [late]

    asyncio.run(service._check_and_execute_tasks())

    assert service.rescheduled == ["forgotten"]
    assert service.executed == []


def test_a_task_that_is_simply_due_runs(service):
    """Counter-check: the everyday case still executes."""
    due = _task("now", due_secs_ago=5)
    service._tasks_for_test = [due]

    asyncio.run(service._check_and_execute_tasks())

    assert service.executed == ["now"]
    assert service.rescheduled == []
