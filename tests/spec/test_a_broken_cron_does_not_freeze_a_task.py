# -*- coding: utf-8 -*-
"""A cron expression is checked, and a broken one does not freeze the task.

THE FINDING (independent review of the scheduler, 2026-09-23): two halves of
the same hole.

* Nothing validates a cron string on any write path. `is_valid()` only asks
  that it is non-empty, and add_task exempts cron from the "must have a next
  run" rule - so `*/5 * * *` (four fields, a typo) or `0 25 * * *` (hour 25)
  is stored, and the panel answers "Task added, but switched off: the time
  given is in the past" about an expression that has no time in it at all.
* When croniter then fails, _calculate_cron_next_run returns None WITHOUT
  touching next_run_ts - every other cycle falls through to the tail of
  calculate_next_run, which sets it to None. So the old timestamp survives in
  the past: the task list shows "active, next run yesterday", the run is
  suppressed as already executed, and after a restart the missed-run handling
  reschedules it to the same past time once a minute, for ever, with a warning
  line each time.

COUNTER-CHECK (2026-09-23): red before - the broken expression was accepted
with "switched off because the time is in the past", and the frozen timestamp
survived the failed recalculation.
"""

import time

import pytest

from services.scheduling.scheduler import ScheduledTask
from services.web.task_management_service import AddTaskRequest, TaskManagementService


@pytest.fixture
def scheduler(monkeypatch):
    saved = []
    monkeypatch.setattr("services.scheduling.scheduler.add_task",
                        lambda task: saved.append(task) or True)
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        lambda *a, **k: None)
    return saved


def _cron_task(expression):
    return ScheduledTask(container_name="plex", action="restart", cycle="cron",
                         schedule_details={"cron_string": expression}, timezone_str="UTC")


@pytest.mark.parametrize("expression", ["*/5 * * *", "0 25 * * *", "not a cron at all"])
def test_a_broken_expression_leaves_no_time_standing(expression):
    task = _cron_task(expression)
    task.next_run_ts = time.time() + 3600      # as a working expression had left it

    task.calculate_next_run()

    assert task.next_run_ts is None, (
        f"{expression!r} left {task.next_run_ts} standing - the task shows as active, "
        f"never runs, and is rescheduled to that same past time every minute")


def test_a_working_expression_still_gets_its_time():
    """Counter-check: the refusal must not swallow valid cron."""
    task = _cron_task("0 3 * * *")

    task.calculate_next_run()

    assert task.next_run_ts and task.next_run_ts > time.time()


@pytest.mark.parametrize("expression", ["*/5 * * *", "0 25 * * *"])
def test_the_panel_refuses_a_broken_expression(scheduler, expression):
    result = TaskManagementService().add_task(AddTaskRequest(
        container="plex", action="restart", cycle="cron",
        schedule_details={"cron_string": expression}, timezone_str="UTC"))

    assert result.success is False, (
        f"{expression!r} was stored; the operator was told about a time that was never given")
    assert "cron" in (result.error or "").lower(), result.error
    assert scheduler == []


def test_the_panel_still_takes_a_good_expression(scheduler):
    """Counter-check: cron tasks must remain possible."""
    result = TaskManagementService().add_task(AddTaskRequest(
        container="plex", action="restart", cycle="cron",
        schedule_details={"cron_string": "30 4 * * 1"}, timezone_str="UTC"))

    assert result.success is True, result.error
    assert len(scheduler) == 1
