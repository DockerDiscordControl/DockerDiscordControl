# -*- coding: utf-8 -*-
"""A one-time task whose time has passed says so instead of "added".

THE FINDING: a one-time task with a time in the past is saved, immediately
switched off (_validate_and_calculate_next_run, "automatically deactivated
because the execution time is in the past"), and the panel is told "Task
added successfully". The operator sets a restart for tonight, mistypes the
date, sees the green message and believes it is scheduled - it will never run.
SPEC.md Z3: no success is reported that did not happen.

The task is still saved and still returned - only the message says what
happened, and the panel shows that message.

COUNTER-CHECK (2026-09-23): red before - "Task added successfully" for a task
that was switched off in the same call. test_a_task_in_the_future_is_just
_added holds the other side: a message about being switched off would show up
for every task without it.
"""

import time
from types import SimpleNamespace

import pytest

from services.web.task_management_service import AddTaskRequest, TaskManagementService


@pytest.fixture
def scheduler(monkeypatch):
    """Accept every save, so only the message is under test."""
    saved = []
    monkeypatch.setattr("services.scheduling.scheduler.add_task",
                        lambda task: saved.append(task) or True)
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        lambda *a, **k: None)
    return saved


def _add(when):
    """A one-time task at `when` (a struct_time-shaped local time string)."""
    moment = time.localtime(when)
    return AddTaskRequest(
        container="nginx",
        action="restart",
        cycle="once",
        schedule_details={
            "year": moment.tm_year, "month": moment.tm_mon, "day": moment.tm_mday,
            "time": time.strftime("%H:%M", moment),
        },
        timezone_str="UTC",
    )


def test_a_task_in_the_past_says_it_will_not_run(scheduler):
    result = TaskManagementService().add_task(_add(time.time() - 3 * 24 * 3600))

    assert result.success is True                 # it IS saved, and listed
    assert result.task_data["is_active"] is False
    assert "not run" in result.message.lower() or "past" in result.message.lower(), (
        f"the panel was told {result.message!r} for a task that was switched off")


def test_a_task_in_the_future_is_just_added(scheduler):
    """Counter-check: the everyday case keeps the plain message."""
    result = TaskManagementService().add_task(_add(time.time() + 3 * 24 * 3600))

    assert result.success is True
    assert result.task_data["is_active"] is True
    assert result.message == "Task added successfully"


def test_the_task_is_saved_either_way(scheduler):
    """Counter-check: the message is the change, not the saving."""
    TaskManagementService().add_task(_add(time.time() - 3 * 24 * 3600))

    assert len(scheduler) == 1


def test_the_form_shows_what_the_server_said():
    """The page must show it: the form printed its own green line for a 201.

    COUNTER-CHECK: red before - the template had no taskAddedNotice in it, and
    the message this service returns never reached a human.
    """
    import shutil
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    form = (root / "app" / "templates" / "tasks" / "form.html").read_text(encoding="utf-8")

    assert "taskAddedNotice(data.body" in form, "the form still writes its own message"
    assert "'alert', 'alert-success'" not in form, "a 201 is still always green"
    assert "task_added_notice.js" in (
        root / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8"), (
        "the page does not load the helper it calls")

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/task_added_notice.test.js by hand")
    result = subprocess.run([node, str(root / "tests" / "js" / "task_added_notice.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 4, result.stdout
