# -*- coding: utf-8 -*-
"""A timezone pytz does not know does not take the task list, form and add down.

THE FINDING (stage 4 review before v3.1.0, section 31 pass 4 F3): with a
config.json 'timezone' that pytz does not know (a hand edit, or a crafted
settings POST - the settings save does not check the field), the task
list, the task form and task creation failed as a whole: the helpers'
fallbacks catch neither pytz.UnknownTimeZoneError nor the KeyError it is,
and the page said "Failed to list tasks" with no task at all. The bot
itself falls back to UTC in that case (app/bootstrap/runtime.py).

THE CONTRACT: the panel does as the bot does - an unknown zone is logged
and UTC applies.

HOW THIS TEST CAN FAIL: the list or the form fails again.

COUNTER-CHECK (2026-09-30): red before the change (success False).
"""

import time

import pytest

from services.scheduling import scheduler
from services.web.task_management_service import (
    ListTasksRequest, TaskFormRequest, TaskManagementService)


@pytest.fixture
def unknown_zone(monkeypatch):
    monkeypatch.setattr("services.config.config_service.load_config",
                        lambda *a, **k: {"timezone": "Europe/Berln"})


def test_the_list_still_shows_the_tasks(unknown_zone, monkeypatch):
    task = scheduler.ScheduledTask(container_name="nginx", action="restart", cycle="daily",
                                   hour=4, minute=0, timezone_str="UTC")
    task.next_run_ts = time.time() + 3600
    task.is_active = True
    service = TaskManagementService()
    monkeypatch.setattr(service, "_load_tasks_from_scheduler", lambda: [task])

    result = service.list_tasks(ListTasksRequest())

    assert result.success, result.error
    assert [row.get("container", row.get("container_name")) for row in result.tasks] == ["nginx"]


def test_the_form_still_opens(unknown_zone, monkeypatch):
    monkeypatch.setattr("app.utils.shared_data.load_active_containers_from_config", lambda: None)
    monkeypatch.setattr("app.utils.shared_data.get_active_containers", lambda: ["nginx"])

    result = TaskManagementService().get_task_form_data(TaskFormRequest())

    assert result.success, result.error
    assert result.form_data["timezone_str"] == "UTC"
