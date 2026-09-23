# -*- coding: utf-8 -*-
"""The panel can schedule a task on a group, not only on a container.

The scheduler can run a group task (test_a_task_can_target_a_group.py). This
is the way in: the form, the route and the service have to carry the one bit
that says "this name is a group".

What it has to get right:

* a task created with a group keeps the flag - without it the scheduler would
  look for a CONTAINER called "Gameserver" and fail every Sunday at 4;
* the flag survives being written and read back, because a task is saved to
  tasks.json and loaded again on the next start;
* editing a task does not silently turn a group task into a container task;
* the form offers the groups, and says which choice is which.

COUNTER-CHECK (2026-09-23): red before - AddTaskRequest had no such field, the
form had no group choice, and a task built from it targeted a container that
does not exist.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.scheduling.scheduler import ScheduledTask
from services.web.task_management_service import AddTaskRequest, TaskManagementService

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scheduler(monkeypatch):
    saved = []
    monkeypatch.setattr("services.scheduling.scheduler.add_task",
                        lambda task: saved.append(task) or True)
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        lambda *a, **k: None)
    return saved


def _request(target_is_group):
    moment = time.localtime(time.time() + 3 * 24 * 3600)
    return AddTaskRequest(
        container="Gameserver", action="restart", cycle="once",
        schedule_details={"year": moment.tm_year, "month": moment.tm_mon,
                          "day": moment.tm_mday, "time": time.strftime("%H:%M", moment)},
        timezone_str="UTC", target_is_group=target_is_group)


def test_a_task_on_a_group_keeps_the_flag(scheduler):
    result = TaskManagementService().add_task(_request(True))

    assert result.success is True
    assert scheduler[0].target_is_group is True, (
        "the scheduler would look for a container called 'Gameserver'")
    assert result.task_data["target_is_group"] is True


def test_a_task_on_a_container_is_not_a_group(scheduler):
    """Counter-check: the flag must not be set for everyone."""
    result = TaskManagementService().add_task(_request(False))

    assert scheduler[0].target_is_group is False
    assert result.task_data["target_is_group"] is False


def test_the_flag_survives_a_round_trip_through_the_file():
    """A task is written to tasks.json and read back on the next start."""
    task = ScheduledTask(container_name="Gameserver", action="restart", cycle="daily",
                         hour=4, minute=0, timezone_str="UTC", target_is_group=True)

    written = json.loads(json.dumps(task.to_dict()))
    read_back = ScheduledTask.from_dict(written)

    assert read_back.target_is_group is True
    assert read_back.container_name == "Gameserver"


def test_a_task_from_an_older_version_is_not_a_group():
    """Counter-check: tasks.json entries written before this release."""
    old = {"id": "abc", "container": "Valheim", "action": "restart", "cycle": "daily",
           "schedule_details": {"time": "04:00"}}

    assert ScheduledTask.from_dict(old).target_is_group is False


def test_the_form_offers_the_choice():
    form = (ROOT / "app" / "templates" / "tasks" / "form.html").read_text(encoding="utf-8")

    assert "task-target-group" in form, "the form has no way to pick a group"
    assert "target_is_group" in form, "the form does not send which kind of target it is"


def test_editing_a_group_task_keeps_it_a_group_task(monkeypatch):
    """The edit form sends the fields it knows; the flag is not one of them.

    COUNTER-CHECK (2026-09-23): red before - _update_task_with_data left
    target_is_group untouched only by accident, and the first edit that carried
    a "target_is_group": false would have turned the task into one looking for
    a container called "Gameserver". Now the update reads the field when it is
    there and keeps what the task had when it is not.
    """
    from services.web.task_management_service import EditTaskRequest

    task = ScheduledTask(container_name="Gameserver", action="restart", cycle="daily",
                         hour=4, minute=0, timezone_str="UTC", target_is_group=True)
    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id",
                        lambda task_id: task if task_id == task.task_id else None)
    monkeypatch.setattr("services.scheduling.scheduler.update_task",
                        lambda updated, **kwargs: True)
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        lambda *a, **k: None)

    service = TaskManagementService()
    # An edit that says nothing about the target keeps it
    service.edit_task(EditTaskRequest(task_id=task.task_id, operation="update",
                                      data={"container": "Gameserver", "action": "stop",
                                            "cycle": "daily"}))
    assert task.target_is_group is True

    # An edit that says so switches it
    service.edit_task(EditTaskRequest(task_id=task.task_id, operation="update",
                                      data={"container": "Valheim", "action": "stop",
                                            "cycle": "daily", "target_is_group": False}))
    assert task.target_is_group is False
