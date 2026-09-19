# -*- coding: utf-8 -*-
"""The task list does not show an expired task as active.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review pass 1, section 31 F2, re-checked 2026-09-19):
``_process_task_for_frontend`` copies ``task.is_active`` into the dictionary
BEFORE it calls ``_calculate_frontend_status``, which is what recognises an
expired one-time task and sets ``is_active = False`` (and has it saved). The
browser therefore gets ``frontend_status: "expired"`` together with
``is_active: true`` - the row shows the switch as on for a task that was
just switched off.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.web.task_management_service import ListTasksRequest, TaskManagementService


class _Task:
    """A one-time task whose time has passed and that never ran."""

    def __init__(self):
        self.task_id = "t1"
        self.container_name = "vrising"
        self.cycle = "once"
        self.action = "start"
        self.status = "pending"
        self.is_active = True
        self.next_run_ts = time.time() - 3600
        self.created_at_ts = time.time() - 7200
        self.last_run_ts = None
        self.last_run_error = None

    def to_dict(self):
        return {"task_id": self.task_id, "container_name": self.container_name,
                "cycle": self.cycle, "action": self.action, "status": self.status,
                "is_active": self.is_active, "next_run_ts": self.next_run_ts}

    def is_system_task(self):
        return False

    def is_donation_task(self):
        return False


@pytest.fixture
def listed(monkeypatch):
    service = TaskManagementService()
    task = _Task()
    monkeypatch.setattr(service, "_load_tasks_from_scheduler", lambda: [task])
    monkeypatch.setattr(service, "_determine_timezone", lambda _tz: "UTC")
    monkeypatch.setattr(service, "_update_tasks_in_scheduler", lambda tasks: None,
                        raising=False)
    monkeypatch.setattr("services.scheduling.scheduler.update_task", lambda t: True,
                        raising=False)
    result = service.list_tasks(ListTasksRequest(timezone_str="UTC"))
    assert result.success, getattr(result, "error", None)
    return result.tasks[0], task


def test_an_expired_task_is_not_listed_as_active(listed):
    listed_task, task = listed

    assert listed_task["frontend_status"] == "expired", "premise: it counts as expired"
    assert task.is_active is False, "premise: the service switched it off"
    assert listed_task["is_active"] is False, (
        "the row says the task is still active although it was just recognised as "
        "expired and switched off"
    )


@pytest.fixture
def listed_future(monkeypatch):
    """A daily task whose next run is ahead - nothing to expire here."""
    service = TaskManagementService()
    task = _Task()
    task.cycle = "daily"
    task.next_run_ts = time.time() + 3600
    monkeypatch.setattr(service, "_load_tasks_from_scheduler", lambda: [task])
    monkeypatch.setattr(service, "_determine_timezone", lambda _tz: "UTC")
    result = service.list_tasks(ListTasksRequest(timezone_str="UTC"))
    assert result.success, getattr(result, "error", None)
    return result.tasks[0], task


def test_an_active_task_is_still_listed_as_active(listed_future):
    """Counter-check: otherwise 'always inactive' would pass the test above."""
    listed_task, task = listed_future

    assert task.is_active is True, "premise: nothing switched it off"
    assert listed_task["is_active"] is True, listed_task
