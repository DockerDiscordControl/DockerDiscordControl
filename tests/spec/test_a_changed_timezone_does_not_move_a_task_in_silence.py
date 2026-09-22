# -*- coding: utf-8 -*-
"""Editing a task under a different timezone says that it moved.

THE FINDING: every task carries the timezone it was created in, and the edit
form sends the timezone the PANEL is set to right now
(tasks.js: `timezone_str: window.DDC_CONFIG?.timezone`). So after the operator
changes the panel's timezone, opening an old task and saving anything at all -
a container name, the action - rewrites its timezone, and the same "20:00"
means a different moment. Measured with a daily task at 20:00 moved from
Europe/Berlin to America/New_York: the next run went from 18:00 UTC to 00:00
UTC. Tasks that were not touched keep the old zone, so two tasks showing
"20:00" run six hours apart.

Which of the two meanings is right is the operator's call. What is not a
question is that it happened in silence: the panel printed its own
"updated successfully" and threw the service's message away.

COUNTER-CHECK (2026-09-23): red before - the message said only "updated
successfully" for a task whose timezone had just been rewritten, and tasks.js
did not read result.message at all. test_an_edit_in_the_same_timezone_is_plain
holds the other side: mentioning the timezone every time would be green
without it.
"""

import time
from types import SimpleNamespace

import pytest

from services.scheduling.scheduler import ScheduledTask
from services.web.task_management_service import EditTaskRequest, TaskManagementService


@pytest.fixture
def service(monkeypatch):
    """The service with a single daily task at 20:00 Berlin, saved in memory."""
    task = ScheduledTask(container_name="nginx", action="restart", cycle="daily",
                         hour=20, minute=0, timezone_str="Europe/Berlin")
    task.calculate_next_run()

    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id",
                        lambda task_id: task if task_id == task.task_id else None)
    monkeypatch.setattr("services.scheduling.scheduler.update_task",
                        lambda updated, **kwargs: True)
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        lambda *a, **k: None)
    management = TaskManagementService()
    management.task = task
    return management


def _edit(service, timezone):
    return service.edit_task(EditTaskRequest(
        task_id=service.task.task_id, operation="update",
        data={"container": "nginx", "action": "restart", "cycle": "daily",
              "timezone_str": timezone}))


def test_a_task_that_moved_says_so(service):
    before = service.task.next_run_ts

    result = _edit(service, "America/New_York")

    assert result.success is True
    assert service.task.next_run_ts != before, "the probe itself must move the task"
    assert "America/New_York" in result.message and "Europe/Berlin" in result.message, (
        f"the operator was told {result.message!r} for a task that now runs at "
        f"another time")


def test_an_edit_in_the_same_timezone_is_plain(service):
    """Counter-check: the everyday edit keeps the plain message."""
    result = _edit(service, "Europe/Berlin")

    assert result.success is True
    assert "Europe/Berlin" not in result.message, result.message


def test_the_panel_shows_what_the_service_said():
    """The page must show it - it printed its own line and dropped the message."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "app" / "static" / "js" /
          "tasks.js").read_text(encoding="utf-8")

    assert "result.message" in js, "the panel still writes its own success text"
