# -*- coding: utf-8 -*-
"""A run that DDC was stopped in the middle of is not repeated - and the task moves on.

THE FINDING (stage 4 review before v3.1.0, section 49 pass 4 F1, verified
2026-09-29 in a corrected form). execute_task writes last_run_ts before it
acts, so that a DDC restart mid-action does not act a second time
(test_a_restart_does_not_run_a_task_twice.py). When DDC is stopped while
the action runs - an image update, a container stop - next_run_ts is never
advanced. After the restart the "already begun" guard skipped the task
with a bare `continue`, before the missed-run handling could reach it -
every cycle, for good: a daily restart never ran again and a one-time task
stayed active for ever, with an INFO line a minute as the only trace.

THE CONTRACT: the begun occurrence is not run again, and it is moved on:
marked not successful with the reason, a recurring task gets its next run,
a one-time task is switched off - and that is saved.

HOW THIS TEST CAN FAIL: the guard skips without moving the task on again.

It runs a real cycle of SchedulerService and the real reschedule down to
the save, which is recorded.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
import time

import pytest

from services.scheduling import scheduler, scheduler_service


@pytest.fixture
def world(monkeypatch):
    started, saved = [], []
    service = scheduler_service.SchedulerService()

    async def no_system_tasks():
        return None

    async def batch(tasks):
        started.extend(t.task_id for t in tasks)

    monkeypatch.setattr(scheduler_service, "load_tasks", lambda: list(service._tasks_for_test))
    monkeypatch.setattr(scheduler, "_persist_executed_task", lambda task: saved.append(task) or True)
    monkeypatch.setattr(service, "_check_system_tasks", no_system_tasks)
    monkeypatch.setattr(service, "_execute_task_batch", batch)
    service.started, service.saved = started, saved
    return service


def _begun(cycle="daily"):
    task = scheduler.ScheduledTask(container_name="postgres", action="restart", cycle=cycle,
                                   hour=3, minute=0, year=2026, month=9, day=29,
                                   timezone_str="UTC")
    task.next_run_ts = time.time() - 70
    task.last_run_ts = time.time() - 69     # begun, then DDC stopped
    return task


def test_a_recurring_task_is_not_repeated_but_gets_its_next_run(world):
    task = _begun()
    world._tasks_for_test = [task]

    asyncio.run(world._check_and_execute_tasks())

    assert world.started == [], "the begun run was repeated"
    assert world.saved, "the task was not moved on - it would be skipped every cycle"
    assert task.next_run_ts > time.time(), "the next run was not calculated"
    assert task.last_run_success is False and task.last_run_error


def test_a_one_time_task_is_switched_off(world):
    task = _begun(cycle="once")
    world._tasks_for_test = [task]

    asyncio.run(world._check_and_execute_tasks())

    assert world.started == [] and world.saved
    assert task.is_active is False
