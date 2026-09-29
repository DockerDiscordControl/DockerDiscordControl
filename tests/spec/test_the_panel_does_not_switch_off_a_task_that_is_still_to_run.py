# -*- coding: utf-8 -*-
"""Listing the tasks in the panel does not switch off a one-time task the scheduler will still run.

THE FINDING (second review before v3.1.0, 2026-09-29). The task list of the
web panel tidies up: a one-time task whose next run lies in the past is
marked "expired", switched off and saved. The scheduler, however, runs a due
task in its next cycle (every 60 s), treats it as missed only after a grace
of MISSED_RUN_GRACE_SECONDS - and a task with "only when nobody plays" waits
up to 720 minutes past its time on purpose. Opening the panel in that time
switched the task off for good:

  * a one-time restart at 04:00 "only when nobody plays", players still on,
    the operator looks at the panel at 04:30 -> switched off, the restart
    never comes, not even at the end of the wait it promised;
  * without any option, the page loaded in the seconds between 04:00:00 and
    the scheduler's next cycle did the same.

THE CONTRACT: the panel calls a one-time task expired, and switches it off,
only once the scheduler would no longer run it: past its time by more than
the grace and the task's own wait.

HOW THIS TEST CAN FAIL: the panel decides "expired" by the time alone again.

It goes through list_tasks - the call the page makes - not the helper alone.

COUNTER-CHECK (2026-09-29): written before the fix and red then - the first
two cases were switched off; the two tidy-up cases were green before and after.
"""

import time

import pytest

from services.scheduling.scheduled_task import ScheduledTask
from services.scheduling.scheduler_service import MISSED_RUN_GRACE_SECONDS
from services.web.task_management_service import ListTasksRequest, TaskManagementService


def _one_time(seconds_ago, options=None):
    task = ScheduledTask(container_name="Icarus2", action="restart", cycle="once",
                         timezone_str="UTC")
    task.next_run_ts = time.time() - seconds_ago
    task.is_active = True
    task.status = "pending"
    task.options = options or {}
    return task


def _listed(monkeypatch, task):
    service = TaskManagementService()
    saved = []
    monkeypatch.setattr(service, "_load_tasks_from_scheduler", lambda: [task])

    def _save(tasks):
        saved.extend(tasks)
        return set()

    monkeypatch.setattr(service, "_save_updated_tasks", _save)
    result = service.list_tasks(ListTasksRequest(timezone_str="UTC"))
    assert result.success, result.error
    return saved


def test_a_task_waiting_for_an_empty_server_stays_on(monkeypatch):
    task = _one_time(30 * 60, {"wait_for_empty": True, "max_wait_minutes": 120})

    saved = _listed(monkeypatch, task)

    assert task.is_active and not saved, "the panel switched off a restart that is still waiting"


def test_a_task_the_scheduler_has_not_reached_yet_stays_on(monkeypatch):
    task = _one_time(20)

    saved = _listed(monkeypatch, task)

    assert task.is_active and not saved, "switched off 20 s after its time, before the scheduler ran"


def test_a_really_missed_task_is_still_tidied_up(monkeypatch):
    """Counter-check: the clean-up itself stays."""
    task = _one_time(MISSED_RUN_GRACE_SECONDS + 3600)

    saved = _listed(monkeypatch, task)

    assert not task.is_active and saved == [task]


def test_a_wait_that_is_over_is_tidied_up_too(monkeypatch):
    """Counter-check: the wait extends the time, it does not make it endless."""
    task = _one_time(120 * 60 + MISSED_RUN_GRACE_SECONDS + 600,
                     {"wait_for_empty": True, "max_wait_minutes": 120})

    saved = _listed(monkeypatch, task)

    assert not task.is_active and saved == [task]
