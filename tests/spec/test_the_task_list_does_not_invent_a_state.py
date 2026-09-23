# -*- coding: utf-8 -*-
"""The task list does not report a state that was never written down.

THE FINDING (independent review of the scheduler, 2026-09-23): listing the
tasks is not only a read. An expired one-time task is switched off on the way
through, and the change is written back with update_task - which refuses a
system task, an invalid one, and answers False when tasks.json could not be
written at all (read-only mount, wrong permissions).

The row that goes to the browser is built BEFORE that write is attempted, and
it is sent whatever the write did. So the panel drew the switch as off for a
task that is still active in the file. Reloading showed it off again, and off
again, while the scheduler went on holding it as active. The operator sees a
task that is off and behaves as if it is on, and nothing on the page says why.

The log side of this was closed already (see
test_an_expired_task_is_only_called_saved_when_it_was.py) - an ERROR is
written. This is about what the page itself claims.

HOW THIS TEST CAN FAIL: it lets the write be refused and reads the row the
panel would send. If the row still says the task is off, the test is red.

COUNTER-CHECK (2026-09-23): red before - is_active came back False for a task
that stayed active in the file. The second test holds the everyday case: when
the write goes through, the row says off, because that is now true.
"""

import time

import pytest

from services.scheduling import scheduler
from services.web.task_management_service import TaskManagementService, ListTasksRequest


def _expired_one_time_task():
    task = scheduler.ScheduledTask(container_name="nginx", action="stop", cycle="once",
                                   year=2026, month=9, day=1, hour=3, minute=0,
                                   timezone_str="UTC")
    task.next_run_ts = time.time() - 24 * 3600
    task.is_active = True
    return task


def _row(monkeypatch, write_succeeds):
    task = _expired_one_time_task()
    service = TaskManagementService()
    monkeypatch.setattr(service, "_load_tasks_from_scheduler", lambda: [task])
    monkeypatch.setattr("services.scheduling.scheduler.update_task",
                        lambda updated: write_succeeds)

    result = service.list_tasks(ListTasksRequest())

    assert result.success
    assert len(result.tasks) == 1
    return result.tasks[0]


def test_a_task_still_active_in_the_file_is_not_drawn_as_switched_off(monkeypatch):
    """The write was refused, so the file still holds the task as active."""
    row = _row(monkeypatch, write_succeeds=False)

    assert row["is_active"] is True, (
        "the panel drew the switch as off for a task that is still active in tasks.json")
    assert row["frontend_status"] == "expired", (
        "the row should still say the task is expired - that part is true")


def test_a_task_that_was_written_off_is_drawn_as_switched_off(monkeypatch):
    """Counter-check: when the write goes through, off is the truth."""
    row = _row(monkeypatch, write_succeeds=True)

    assert row["is_active"] is False
    assert row["frontend_status"] == "expired"


def test_an_ordinary_task_is_not_written_at_all(monkeypatch):
    """Counter-check: a task with a future run is read, not rewritten."""
    task = scheduler.ScheduledTask(container_name="nginx", action="stop", cycle="daily",
                                   hour=3, minute=0, timezone_str="UTC")
    task.next_run_ts = time.time() + 3600
    task.is_active = True
    written = []
    service = TaskManagementService()
    monkeypatch.setattr(service, "_load_tasks_from_scheduler", lambda: [task])
    monkeypatch.setattr("services.scheduling.scheduler.update_task",
                        lambda updated: written.append(updated) or True)

    result = service.list_tasks(ListTasksRequest())

    assert written == [], "listing the tasks rewrote a task that had not changed"
    assert result.tasks[0]["is_active"] is True
    assert result.tasks[0]["frontend_status"] == "active"
