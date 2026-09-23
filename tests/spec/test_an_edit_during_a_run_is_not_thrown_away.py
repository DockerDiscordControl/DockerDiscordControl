# -*- coding: utf-8 -*-
"""An edit made while a task runs survives the run.

THE FINDING (independent review of the scheduler, 2026-09-23): the scheduler
loads its tasks at the top of a cycle, executes, and then writes its own
IN-MEMORY object back over whatever is in the file by then.

    03:00:00  the cycle loads the daily restart of plex and starts it
    03:00:12  the operator moves the task to 05:00 in the panel; the panel
              reads the file, recalculates, saves, and answers
              "Task ... updated successfully"
    03:00:41  the restart finishes; update_after_execution() runs on the STALE
              object (still 03:00) and writes it back - the edit is gone

The panel shows 03:00 again on the next refresh, with no error anywhere. The
cross-process lock does not help: both writes are atomic on their own, the
read-modify-write spans them. The same race re-arms a task the operator
switched OFF during the run.

Writing back a run touches only what the RUN produced: the result, the last
run, the status - and the next run only when the schedule it was computed from
is still the one in the file.

COUNTER-CHECK (2026-09-23): red before - the edit was overwritten with the
schedule the scheduler had loaded. The other tests keep the ordinary
write-back, which must still move the next run.
"""

import json
import time

import pytest

from services.scheduling import scheduler


@pytest.fixture
def tasks_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.scheduling import runtime

    runtime.reset_scheduler_runtime() if hasattr(runtime, "reset_scheduler_runtime") else None
    monkeypatch.setattr(scheduler, "TASKS_FILE", tmp_path / "tasks.json", raising=False)
    return tmp_path / "tasks.json"


def _task(hour, minute=0):
    return scheduler.ScheduledTask(container_name="plex", action="restart", cycle="daily",
                                   hour=hour, minute=minute, timezone_str="UTC")


def test_the_panels_edit_survives(tasks_file, monkeypatch):
    running = _task(3)
    running.calculate_next_run()

    # what the file holds by the time the run finishes: the operator's 05:00
    edited = scheduler.ScheduledTask.from_dict(running.to_dict())
    edited.time_str = "05:00"
    edited.calculate_next_run()
    edited_next_run = edited.next_run_ts
    monkeypatch.setattr(scheduler, "load_tasks", lambda: [edited])
    saved = []
    monkeypatch.setattr(scheduler, "save_tasks", lambda tasks: saved.append(tasks) or True)

    # the scheduler finishes its run on the stale object and writes it back
    running.last_run_success = True
    running.update_after_execution()
    scheduler._persist_executed_task(running)

    assert saved, "nothing was written at all"
    written = saved[-1][0]
    assert written.time_str == "05:00", (
        f"the edit was overwritten with {written.time_str}")
    assert written.next_run_ts == edited_next_run, (
        "the list would show 05:00 while the task still runs at 03:00 - found after a "
        "sabotage run that took the run's next time regardless")
    assert written.last_run_success is True, "the run's own result was lost"
    assert written.last_run_ts == running.last_run_ts


def test_a_task_switched_off_during_the_run_stays_off(tasks_file, monkeypatch):
    running = _task(3)
    running.calculate_next_run()
    switched_off = scheduler.ScheduledTask.from_dict(running.to_dict())
    switched_off.is_active = False
    monkeypatch.setattr(scheduler, "load_tasks", lambda: [switched_off])
    saved = []
    monkeypatch.setattr(scheduler, "save_tasks", lambda tasks: saved.append(tasks) or True)

    running.update_after_execution()
    scheduler._persist_executed_task(running)

    assert saved[-1][0].is_active is False, "the task re-armed itself"


def test_an_untouched_task_still_gets_its_new_next_run(tasks_file, monkeypatch):
    """Counter-check: the ordinary write-back must still move the schedule on."""
    running = _task(3)
    running.calculate_next_run()
    # as it stands the moment the run finishes: the occurrence just passed
    running.next_run_ts = time.time() - 60
    first_run = running.next_run_ts
    unchanged = scheduler.ScheduledTask.from_dict(running.to_dict())
    monkeypatch.setattr(scheduler, "load_tasks", lambda: [unchanged])
    saved = []
    monkeypatch.setattr(scheduler, "save_tasks", lambda tasks: saved.append(tasks) or True)

    running.update_after_execution()
    scheduler._persist_executed_task(running)

    written = saved[-1][0]
    assert written.next_run_ts == running.next_run_ts
    assert written.next_run_ts != first_run, "the task would run at the same time again"
