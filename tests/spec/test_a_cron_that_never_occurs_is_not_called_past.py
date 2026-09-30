# -*- coding: utf-8 -*-
"""A cron task whose date never occurs is not told "the time is in the past".

THE FINDING (stage 4 review before v3.1.0, section 31 pass 4 F7): a cron
expression that is readable but never occurs ('0 0 31 2 *', '0 0 30 2 *',
'0 0 31 4 *') gets no next run, and the task is saved switched off. The
only switched-off wording was the one for a one-time task in the past:
"the time given is in the past ... Set a new time to switch it on" - no
time is in the past, and a new time is not what is wrong.

THE CONTRACT: the message names the actual reason: the schedule has no
next run because its date never occurs. The one-time wording stays for a
one-time task.

HOW THIS TEST CAN FAIL: the past-time wording comes back for a schedule.

COUNTER-CHECK (2026-09-30): red before the change ("in the past").
"""

import pytest

from services.web.task_management_service import AddTaskRequest, TaskManagementService


@pytest.fixture
def service(monkeypatch):
    service = TaskManagementService()
    monkeypatch.setattr(service, "_save_task_via_scheduler", lambda task: {"success": True})
    monkeypatch.setattr(service, "_log_task_creation", lambda task: None)
    monkeypatch.setattr(service, "_determine_timezone", lambda tz: "UTC")
    return service


@pytest.mark.parametrize("cron", ["0 0 31 2 *", "0 0 30 2 *", "0 0 31 4 *"])
def test_the_message_says_the_date_never_occurs(service, cron):
    result = service.add_task(AddTaskRequest(container="nginx", action="restart", cycle="cron",
                                             schedule_details={"cron_string": cron}))
    assert result.success, result.error
    assert result.task_data["is_active"] is False
    assert "in the past" not in result.message
    assert "never occurs" in result.message


def test_a_one_time_task_in_the_past_keeps_its_wording(service):
    result = service.add_task(AddTaskRequest(container="nginx", action="restart", cycle="once",
                                             schedule_details={"time": "04:00", "year": 2020,
                                                               "month": 1, "day": 1}))
    assert result.success, result.error
    assert "in the past" in result.message
