# -*- coding: utf-8 -*-
"""A donation message that fails with an unlisted error is recorded and moves on.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F7): the
scheduled donation message caught only ImportError, AttributeError and
RuntimeError. Anything else - an OSError from the mech state (a full disk,
a permission) is one that really escapes - left execute_task without
touching the task: no failed result, no next run. The task stayed due and
was attempted again every scheduler cycle, about once a minute, for ever,
while the panel showed the previous result.

THE CONTRACT: whatever the error, the run is recorded as failed with its
reason and the task moves to its next run.

HOW THIS TEST CAN FAIL: the error escapes again, or the task stays due.

COUNTER-CHECK (2026-09-29): red before the change (the OSError escaped).
"""

import time

import pytest

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    yield
    scheduler_runtime.reset_scheduler_runtime()


async def test_an_oserror_is_recorded_and_the_task_moves_on(monkeypatch):
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled", lambda: False)

    async def _disk_full(bot=None):
        raise OSError("disk full")
    monkeypatch.setattr(
        "services.scheduling.donation_message_service.execute_donation_message_task", _disk_full)
    monkeypatch.setattr("services.scheduling.donation_message_service.get_bot_instance", lambda: None)
    monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kwargs: None)

    task = scheduler_mod.create_donation_system_task()
    task.next_run_ts = time.time() - 60

    assert await scheduler_mod.execute_task(task) is False
    assert task.last_run_success is False and "disk full" in (task.last_run_error or "")
    assert task.next_run_ts and task.next_run_ts > time.time(), "the task stayed due"
