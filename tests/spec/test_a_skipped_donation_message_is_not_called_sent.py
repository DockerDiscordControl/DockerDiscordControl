# -*- coding: utf-8 -*-
"""A donation message that was deliberately skipped is not recorded as sent.

THE FINDING (independent review of the scheduler, 2026-09-23): the donation
task is skipped when donations are switched off (premium key). Skipping it is
right - what was wrong is what it wrote down afterwards:

    task.last_run_success = True
    task.last_run_error = None
    task.update_after_execution()

with the comment "Update task as if it ran successfully to reschedule it". The
task list then showed a green "Success" badge and a last-run time for a
message that was never sent, every second Sunday, for as long as donations
stay off. An operator checking why nobody sees the donation message reads that
DDC sent it.

Rescheduling is the only thing that needed to happen. The run itself did not,
so it is written down as what it was: skipped, with the reason, and the time
of the last run that really happened is left alone.

HOW THIS TEST CAN FAIL: it switches donations off, runs the task and reads
what the panel reads. A green Success badge or a moved last-run time is red.

COUNTER-CHECK (2026-09-23): red before - last_run_success came back True and
last_run_error None. The second test keeps the point of the skip: the task is
still moved to its next occurrence, and execute_task still answers True so the
scheduler treats it as dealt with.
"""

import asyncio
import time

import pytest

from services.scheduling import scheduler


@pytest.fixture
def donations_off(monkeypatch):
    """Donations switched off, and the write-back kept off the real file."""
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: True)
    monkeypatch.setattr(scheduler, "_persist_executed_task", lambda task: True)


def _donation_task():
    task = scheduler.ScheduledTask(container_name="SYSTEM", action="donation_message",
                                   cycle="monthly", day=8, hour=13, minute=37,
                                   timezone_str="UTC")
    task.next_run_ts = time.time() - 60
    task.last_run_ts = time.time() - 30 * 24 * 3600
    task.last_run_success = True
    task.last_run_error = None
    return task


def test_a_message_that_was_never_sent_is_not_reported_as_sent(donations_off):
    task = _donation_task()

    asyncio.run(scheduler.execute_task(task))

    assert task.last_run_success is not True, (
        "the panel shows a green Success badge for a donation message "
        "that was never sent")
    assert task.last_run_error, "nothing says why no message went out"
    assert "kipped" in task.last_run_error or "witched off" in task.last_run_error, (
        f"the note does not say the run was skipped: {task.last_run_error!r}")


def test_the_time_of_the_last_message_is_not_moved(donations_off):
    """No message went out, so the last one is still the last one."""
    task = _donation_task()
    sent_at = task.last_run_ts

    asyncio.run(scheduler.execute_task(task))

    assert task.last_run_ts == sent_at


def test_the_task_is_still_moved_on_and_counted_as_dealt_with(donations_off):
    """Counter-check: the skip must not leave the task due forever."""
    task = _donation_task()

    result = asyncio.run(scheduler.execute_task(task))

    assert result is True, "the scheduler would treat the task as still due"
    assert task.next_run_ts > time.time(), "the task was not moved to its next occurrence"
    assert task.status == "pending"
