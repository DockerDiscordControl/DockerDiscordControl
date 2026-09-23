# -*- coding: utf-8 -*-
"""A run that was skipped is not shown as the last run having succeeded.

THE FINDING (independent review of the scheduler, 2026-09-23): when a
recurring task's time passes while DDC is not running, the scheduler does not
carry the run out afterwards - it moves the task to its next occurrence. That
is right. What it did not do was say so anywhere the operator looks.

last_run_success and last_run_error were left exactly as the last run that DID
happen left them, so the task list kept a green "Success" badge. A nightly
database restart could be skipped a week running, and the panel said the same
thing every morning: last run, successful. The only trace was one WARNING line
in the log.

The one-time branch already wrote the reason down (the task is switched off, so
it had to). The recurring branch now writes the same kind of note, and leaves
last_run_ts alone - no run happened, so the time of the last real run stays the
time of the last real run.

HOW THIS TEST CAN FAIL: it lets a daily task miss its time and then reads what
the panel reads. If the mark is missing, last_run_success is still True and the
test is red.

COUNTER-CHECK (2026-09-23): red before - last_run_success came back True with
the old error text. The last two tests hold the rest still: the one-time
wording is unchanged, and a real run afterwards clears the mark.
"""

import time

import pytest

from services.scheduling import scheduler


@pytest.fixture
def saved(monkeypatch):
    """Keep the write-back off the real tasks.json; remember what it was given."""
    written = []
    monkeypatch.setattr(scheduler, "_persist_executed_task",
                        lambda task: written.append(task) or True)
    return written


def _task_that_succeeded_yesterday(cycle="daily"):
    task = scheduler.ScheduledTask(container_name="postgres", action="restart", cycle=cycle,
                                   hour=3, minute=0, timezone_str="UTC",
                                   year=2026, month=9, day=21)
    task.next_run_ts = time.time() - 24 * 3600
    task.last_run_ts = time.time() - 48 * 3600
    task.last_run_success = True
    task.last_run_error = None
    return task


def test_a_missed_nightly_run_is_not_reported_as_successful(saved):
    task = _task_that_succeeded_yesterday()

    scheduler.reschedule_missed_task(task)

    assert task.last_run_success is False, (
        "the panel still shows a green Success badge for a run that never happened")
    assert task.last_run_error, "nothing says why the run is missing"
    assert "issed" in task.last_run_error, (
        f"the note does not say the run was missed: {task.last_run_error!r}")


def test_the_time_of_the_last_real_run_is_not_moved(saved):
    """No run happened, so the last run is still the last run."""
    task = _task_that_succeeded_yesterday()
    ran_at = task.last_run_ts

    scheduler.reschedule_missed_task(task)

    assert task.last_run_ts == ran_at
    assert task.next_run_ts > time.time(), "the task was not moved to its next occurrence"
    assert task.is_active, "a recurring task must not be switched off by one missed run"


def test_a_one_time_task_keeps_its_own_wording(saved):
    """Counter-check: that branch was already right and is left alone."""
    task = _task_that_succeeded_yesterday(cycle="once")

    scheduler.reschedule_missed_task(task)

    assert task.is_active is False
    assert task.last_run_success is False
    assert "not executed" in task.last_run_error


def test_a_real_run_afterwards_clears_the_mark(saved):
    """Counter-check: the mark is about the missed run, not about the task."""
    task = _task_that_succeeded_yesterday()
    scheduler.reschedule_missed_task(task)

    task.last_run_success = True
    task.last_run_error = None
    task.last_run_ts = time.time()

    assert task.last_run_success is True
    assert task.last_run_error is None
