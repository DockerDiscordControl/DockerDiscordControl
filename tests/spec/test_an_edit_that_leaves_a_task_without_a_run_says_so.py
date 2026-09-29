# -*- coding: utf-8 -*-
"""Editing a task checks the cron expression and switches off a task without a run.

THE FINDING (stage 4 review before v3.1.0, section 31 pass 4 F1): adding a
task refuses an unreadable cron expression and saves a task without a next
run switched off, with a message. The edit path did neither and answered
"Task ... updated successfully" for three cases:

* a cron task edited to "*/5 * * *" (four fields - unreadable);
* a cron task edited to "0 0 31 2 *" (readable, never occurs);
* a one-time task edited to a date in the past.

Each was saved ACTIVE with no next run, never ran, and the next page load
called it expired and switched it off. (Its own check for past one-time
tasks could never fire: calculate_next_run() already answers None.)

THE CONTRACT: an unreadable expression is refused and the stored task stays
as it was; a task that has no next run is saved switched off and the answer
says so.

HOW THIS TEST CAN FAIL: any of the three is saved active and "updated
successfully" again.

It goes through TaskManagementService.edit_task, the route's path.

COUNTER-CHECK (2026-09-29): all three cases red before the change.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling.scheduler import CYCLE_CRON, CYCLE_DAILY, ScheduledTask, save_tasks
from services.web.task_management_service import EditTaskRequest, TaskManagementService


@pytest.fixture
def stored(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    monkeypatch.setattr(scheduler_mod, "_last_load_failed", False)
    monkeypatch.setattr(scheduler_mod, "_unreadable_entries", [])
    task = ScheduledTask(task_id="t1", container_name="web", action="restart", cycle=CYCLE_CRON,
                         description="0 4 * * *", timezone_str="UTC")
    task.cron_string = "0 4 * * *"
    task.calculate_next_run()
    assert save_tasks([task])
    yield fresh.tasks_file_path
    scheduler_runtime.reset_scheduler_runtime()


def _edit(data):
    return TaskManagementService().edit_task(EditTaskRequest(task_id="t1", operation="update", data=data))


def _on_disk(path):
    return {t["id"]: t for t in json.loads(path.read_text(encoding="utf-8"))}["t1"]


def test_an_unreadable_cron_expression_is_refused(stored):
    result = _edit({"cycle": "cron", "schedule_details": {"cron_string": "*/5 * * *"}})
    assert not result.success, "an unreadable cron expression was 'updated successfully'"
    assert "0 4 * * *" in json.dumps(_on_disk(stored)), "the refused edit changed the stored task"


def test_a_cron_that_never_occurs_is_saved_switched_off(stored):
    result = _edit({"cycle": "cron", "schedule_details": {"cron_string": "0 0 31 2 *"}})
    assert _on_disk(stored)["is_active"] is False, "a task that never runs was saved active"
    assert "updated successfully" not in f"{result.message} {result.error}"


def test_a_one_time_task_moved_into_the_past_is_saved_switched_off(stored):
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    result = _edit({"cycle": "once", "schedule_details": {
        "time": "10:00", "day": yesterday.day, "month": yesterday.month, "year": yesterday.year}})
    assert _on_disk(stored)["is_active"] is False, "a one-time task in the past was saved active"
    assert "updated successfully" not in f"{result.message} {result.error}"
