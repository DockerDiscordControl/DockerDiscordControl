# -*- coding: utf-8 -*-
"""Writing a task's run result down does not stop the bot from answering.

THE FINDING (independent review of the scheduler, 2026-09-23): the scheduler
runs inside the BOT's event loop, and every write-back of an executed task did
its file work right there. One write-back is load_tasks() plus save_tasks(),
and both take the cross-process lock (flock) on config/tasks.json - which on
this install is an SMB mount. It happens twice per task, once before the action
and once after, and once more for every task the cycle writes off as missed.

While that runs, nothing else in the bot moves: no button press is answered, no
heartbeat is sent. With a handful of tasks at 03:00 and a mount that answers
slowly, the bot is simply away for as long as the disk takes - and Discord
closes a gateway connection whose heartbeat stops.

The read at the top of the cycle was already taken off the loop
(scheduler_service.py, asyncio.to_thread(load_tasks)); the writes were not.

HOW THIS TEST CAN FAIL: it makes the write-back take 0.3 s and counts how often
a second coroutine gets to run meanwhile. If the write-back is back on the
event loop, the counter stays at its first tick and the test is red. It is also
red if the write-back runs on the loop's own thread.

COUNTER-CHECK (2026-09-23): red before the change - 1 tick, same thread. The
last test keeps the point of the write-back: it still happens, and it still
carries the task that ran.
"""

import asyncio
import threading
import time

import pytest

from services.scheduling import scheduler, scheduler_service, task_writeback


@pytest.fixture
def slow_disk(monkeypatch):
    """A write-back that takes 0.3 s, and remembers where it ran."""
    calls = []

    def save_run_result(task):
        calls.append({"thread": threading.get_ident(), "task": task})
        time.sleep(0.3)
        return True

    monkeypatch.setattr(task_writeback, "save_run_result", save_run_result)
    return calls


def _blocked_task():
    """A task Discord created for an action the container no longer allows.

    That path is execute_task() at its shortest: it writes the run down and
    returns, with no Docker call in between.
    """
    task = scheduler.ScheduledTask(container_name="postgres", action="restart", cycle="daily",
                                   hour=3, minute=0, timezone_str="UTC")
    task.created_by = "123456789"
    return task


async def _run_and_count_ticks(coro):
    """Run ``coro`` while a second coroutine ticks every 10 ms; return the ticks."""
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    beat = asyncio.ensure_future(heartbeat())
    try:
        await coro
    finally:
        beat.cancel()
    return ticks


def test_the_bot_keeps_answering_while_a_task_is_written_down(slow_disk, monkeypatch):
    """0.3 s of disk must not be 0.3 s of silence."""
    monkeypatch.setattr(scheduler, "_get_disallowed_action_reason",
                        lambda container, action: "restart is not allowed any more")

    ticks = asyncio.run(_run_and_count_ticks(scheduler.execute_task(_blocked_task())))

    assert ticks > 5, (
        f"the event loop only got to run {ticks} times while a task was saved - "
        "the bot was away for the whole write")


def test_the_write_does_not_happen_on_the_loops_own_thread(slow_disk, monkeypatch):
    """The plainest statement of the same thing."""
    monkeypatch.setattr(scheduler, "_get_disallowed_action_reason",
                        lambda container, action: "restart is not allowed any more")
    loop_thread = threading.get_ident()

    asyncio.run(scheduler.execute_task(_blocked_task()))

    assert slow_disk, "nothing was written down at all"
    assert all(call["thread"] != loop_thread for call in slow_disk), (
        "the task was written on the event loop's own thread")


def test_a_missed_task_is_rescheduled_off_the_loop(slow_disk):
    """The other write on the cycle's path: rescheduling what was missed."""
    service = scheduler_service.SchedulerService()
    task = scheduler.ScheduledTask(container_name="postgres", action="restart", cycle="daily",
                                   hour=3, minute=0, timezone_str="UTC")
    task.next_run_ts = time.time() - 24 * 3600  # long past the grace period

    async def no_system_tasks():
        return None

    async def no_batch(tasks):
        return None

    service._check_system_tasks = no_system_tasks
    service._execute_task_batch = no_batch
    loop_thread = threading.get_ident()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(scheduler_service, "load_tasks", lambda: [task])
        ticks = asyncio.run(_run_and_count_ticks(service._check_and_execute_tasks()))

    assert slow_disk, "the missed task was not written down"
    assert all(call["thread"] != loop_thread for call in slow_disk), (
        "the missed task was rescheduled on the event loop's own thread")
    assert ticks > 5, f"the loop only got to run {ticks} times while a missed task was saved"


def test_the_run_is_still_written_down(slow_disk, monkeypatch):
    """Counter-check: moving the write off the loop does not skip it."""
    monkeypatch.setattr(scheduler, "_get_disallowed_action_reason",
                        lambda container, action: "restart is not allowed any more")
    task = _blocked_task()

    result = asyncio.run(scheduler.execute_task(task))

    assert result is False
    assert [call["task"] for call in slow_disk] == [task]
    assert task.last_run_success is False
    assert task.last_run_error == "restart is not allowed any more"
