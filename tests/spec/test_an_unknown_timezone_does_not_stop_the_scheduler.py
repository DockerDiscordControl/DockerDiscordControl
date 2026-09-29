# -*- coding: utf-8 -*-
"""An unknown timezone in the configuration does not stop the scheduler.

THE FINDING (stage 4 review before v3.1.0, section 26b pass 3 F2 + pass 4
F2): the monthly donation message computes its next run with a raw
pytz.timezone(<configured zone>). An unknown zone - a hand edit, a crafted
save (the panel's save stores the posted value unchecked), null - raised
UnknownTimeZoneError, a KeyError none of the handlers catch. The first
load_tasks() after every start builds that task, so load_tasks() raised on
every call and the scheduler ran no task at all, logging an error each tick.
Every other place in the class falls back to UTC through _get_timezone().

THE CONTRACT: an unknown zone falls back to UTC here too; load_tasks()
returns the user's tasks and the donation task with a next run.

HOW THIS TEST CAN FAIL: the zone error escapes load_tasks() again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import time

import pytest

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduled_task as scheduled_task_mod
from services.scheduling import scheduler as scheduler_mod
from services.scheduling.scheduler import CYCLE_DAILY, DONATION_TASK_ID, ScheduledTask, save_tasks


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_last_load_failed", False)  # left by earlier tests
    yield
    scheduler_runtime.reset_scheduler_runtime()


@pytest.mark.parametrize("zone", ["Europe/Berlinn", None, ""])
def test_load_tasks_survives_an_unknown_zone(monkeypatch, zone):
    config = {"timezone": zone}
    monkeypatch.setattr(scheduled_task_mod, "load_config", lambda: config)
    monkeypatch.setattr(scheduler_mod, "load_config", lambda: config)
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled", lambda: False)
    assert save_tasks([ScheduledTask(task_id="mine", container_name="web", action="restart",
                                     cycle=CYCLE_DAILY, hour=4, minute=0, timezone_str="UTC")])

    tasks = {t.task_id: t for t in scheduler_mod.load_tasks()}

    assert "mine" in tasks
    assert DONATION_TASK_ID in tasks, "the donation task was not built"
    assert tasks[DONATION_TASK_ID].next_run_ts and tasks[DONATION_TASK_ID].next_run_ts > time.time()
