# -*- coding: utf-8 -*-
"""The 10-minute collision check looks at the runs that will really happen.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F11): adding or
editing a task refused it when another task for the same container ran within
10 minutes - but it compared only each task's NEXT run, and it counted paused
tasks too:

* a paused task at 04:00 blocked a new one at 04:05, although the paused one
  never runs;
* a daily restart at 04:00 and a new weekly stop on some later day at 04:05
  were let through, because the daily task's next run is tomorrow - and on
  that later day both fire five minutes apart.

THE OPERATOR (2026-09-29): ignore paused tasks, and look at the later runs of
recurring tasks.

HOW THIS TEST CAN FAIL: a paused task blocks again; a clash on a later day
slips through; or the check overreaches and refuses tasks an hour apart.

It goes through scheduler.add_task, the one both the panel and Discord use.

COUNTER-CHECK (2026-09-29): the first two cases were red before the change,
the third green before and after.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling.scheduler import (CYCLE_DAILY, CYCLE_WEEKLY, DAYS_OF_WEEK,
                                           ScheduledTask, add_task, save_tasks)


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    yield
    scheduler_runtime.reset_scheduler_runtime()


def _daily(task_id, hour, minute, active=True):
    return ScheduledTask(task_id=task_id, container_name="Valheim", action="restart",
                         cycle=CYCLE_DAILY, hour=hour, minute=minute, timezone_str="UTC",
                         is_active=active)


def _weekly_in_three_days(task_id, hour, minute):
    weekday = (datetime.now(timezone.utc) + timedelta(days=3)).weekday()
    return ScheduledTask(task_id=task_id, container_name="Valheim", action="stop",
                         cycle=CYCLE_WEEKLY, hour=hour, minute=minute, timezone_str="UTC",
                         weekday=weekday)


def test_a_paused_task_does_not_block_a_new_one():
    assert save_tasks([_daily("paused", 4, 0, active=False)]) is True
    assert add_task(_daily("new", 4, 5)) is True, "a paused task that never runs refused the new one"


def test_a_clash_on_a_later_day_is_found():
    assert save_tasks([_daily("every-day", 4, 0)]) is True
    assert add_task(_weekly_in_three_days("weekly", 4, 5)) is False, (
        "a daily 04:00 and a weekly 04:05 fire five minutes apart on that day - "
        "the check only compared the next runs")


def test_tasks_an_hour_apart_are_not_refused():
    assert save_tasks([_daily("every-day", 4, 0)]) is True
    assert add_task(_weekly_in_three_days("weekly", 5, 0)) is True
