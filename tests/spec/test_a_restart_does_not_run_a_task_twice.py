# -*- coding: utf-8 -*-
"""A task interrupted by a DDC restart is not carried out a second time.

THE FINDING (independent review of the scheduler, 2026-09-23): next_run_ts
only moves AFTER the Docker call returns, and the "already executed" guard is
in memory. So:

    03:00:00  the cycle starts the nightly restart of a database
              (StopTimeout 120, so the action has 150 seconds)
    03:00:20  the DDC container is itself updated and killed
    03:01:10  DDC is back; the task still says next run 03:00, and it is
              70 seconds late - inside the five-minute grace
    03:01:10  the database is restarted A SECOND TIME, mid-boot

That is not a rare path: DDC is restarted by every image update, and a nightly
task is exactly when an unattended update runs.

The occurrence is written down BEFORE the action, so a restart finds it
already begun. What that costs is the opposite case - a run that was begun and
did not finish is not retried - and for a container action that is the safer
of the two.

COUNTER-CHECK (2026-09-23): red before - the second cycle ran the action
again. The other tests keep a task that was never begun runnable, and the
ordinary sequence unchanged.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from services.scheduling import scheduler, scheduler_service


@pytest.fixture
def world(monkeypatch):
    """A scheduler whose cycle reads one due task and records what it runs."""
    started = []

    service = scheduler_service.SchedulerService()

    async def no_system_tasks():
        return None

    async def batch(tasks):
        started.extend(t.task_id for t in tasks)

    monkeypatch.setattr(scheduler_service, "load_tasks", lambda: list(service._tasks_for_test))
    monkeypatch.setattr(scheduler_service, "reschedule_missed_task", lambda task: None)
    monkeypatch.setattr(service, "_check_system_tasks", no_system_tasks)
    monkeypatch.setattr(service, "_execute_task_batch", batch)
    service.started = started
    return service


def _task(next_run_ago, last_run_ago=None):
    task = scheduler.ScheduledTask(container_name="postgres", action="restart", cycle="daily",
                                   hour=3, minute=0, timezone_str="UTC")
    task.next_run_ts = time.time() - next_run_ago
    task.last_run_ts = None if last_run_ago is None else time.time() - last_run_ago
    return task


def test_a_run_that_was_already_begun_is_not_begun_again(world):
    """The task was started at 03:00 and DDC came back at 03:01."""
    task = _task(next_run_ago=70, last_run_ago=69)
    world._tasks_for_test = [task]

    asyncio.run(world._check_and_execute_tasks())

    assert world.started == [], (
        "the container was acted on a second time after a restart")


def test_a_task_that_was_never_begun_still_runs(world):
    """Counter-check: the everyday case - due, never started."""
    task = _task(next_run_ago=70)
    world._tasks_for_test = [task]

    asyncio.run(world._check_and_execute_tasks())

    assert world.started == [task.task_id]


def test_yesterdays_run_does_not_block_todays(world):
    """Counter-check: the last run belongs to the occurrence before this one."""
    task = _task(next_run_ago=70, last_run_ago=24 * 3600)
    world._tasks_for_test = [task]

    asyncio.run(world._check_and_execute_tasks())

    assert world.started == [task.task_id], (
        "a task that ran yesterday was taken for one that is running now")


def test_the_occurrence_is_written_down_before_the_action(monkeypatch):
    """Without the write, a restart cannot tell a begun run from a due one."""
    persisted = []
    monkeypatch.setattr(scheduler, "_persist_executed_task", lambda task: persisted.append(
        (task.task_id, task.last_run_ts, task.next_run_ts)))
    monkeypatch.setattr(scheduler, "log_user_action", lambda **kwargs: None)

    async def docker_action(name, action, **kwargs):
        # At this moment the occurrence must already be on disk
        assert persisted, "the action started before the occurrence was written down"
        return True, ""

    monkeypatch.setattr(scheduler, "docker_action", docker_action, raising=False)
    monkeypatch.setattr("services.docker_service.docker_utils.docker_action", docker_action)

    task = _task(next_run_ago=0)
    asyncio.run(scheduler.execute_task(task, timeout=5))

    assert len(persisted) >= 2, "the run was written down once, not before and after"
