# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""What a finished run writes back into tasks.json.

Split out of scheduler.py (2026-09-23), which is on the size list and may only
shrink - and it is a subject of its own: the scheduler works on the object it
loaded at the top of its cycle, while the panel may have edited the file in
the meantime.
"""

from __future__ import annotations

import asyncio

from services.scheduling.runtime import get_scheduler_runtime
from utils.logging_utils import get_module_logger

logger = get_module_logger('scheduler')


def _scheduler():
    """Imported lazily: scheduler.py owns the file, this module owns the rules."""
    from services.scheduling import scheduler

    return scheduler


SCHEDULE_FIELDS = ("container_name", "action", "cycle", "cron_string", "time_str",
                   "year_val", "month_val", "day_val", "weekday_val", "timezone_str")


def store_system_task_state(task) -> None:
    """Remember a system task's run state across load_tasks() calls.

    System tasks are not stored in tasks.json and are rebuilt on every load;
    their last_run/next_run is kept in the scheduler runtime (per process).
    Memory only - this is the one write-back that touches no disk.
    """
    get_scheduler_runtime().store_system_task_state(task.task_id, {
        "last_run_ts": task.last_run_ts,
        "next_run_ts": task.next_run_ts,
        "last_run_success": task.last_run_success,
        "last_run_error": task.last_run_error,
    })


def persist_executed_task(task) -> bool:
    """Save an executed (or missed) task. Blocking - see the async twin below."""
    if task.is_system_task():
        store_system_task_state(task)
        return True
    return save_run_result(task)


async def persist_executed_task_async(task) -> bool:
    """The same write, off the event loop.

    The scheduler runs inside the BOT's loop, and this write is load_tasks()
    plus save_tasks() under the cross-process lock, on a config directory that
    is often a network mount. Left on the loop, the bot answered nothing - no
    button, no gateway heartbeat - for as long as the disk took, twice per
    task. The read at the top of the cycle was already moved off the loop.

    Looked up through the module so a test that replaces
    scheduler._persist_executed_task still gets its replacement.
    """
    return await asyncio.to_thread(_scheduler()._persist_executed_task, task)


def save_run_result(task) -> bool:
    """Save the result and reschedule of an executed (or missed) task.

    Only what the RUN produced. The scheduler works on the object it loaded at
    the top of its cycle, and an edit made in the panel WHILE the task runs is
    in the file by the time this writes - putting the whole stale object back
    threw that edit away without a word, and re-armed a task the operator had
    just switched off.

    The next run is written only when the schedule it was computed from is
    still the one in the file; an edit brings its own.

    No collision check: the new next_run comes from the task's own schedule,
    and a refused update would keep the old one (double execution, then stuck).
    """
    from services.scheduling.runtime import with_tasks_lock

    # The lock spans the read AND the write: the panel is another process.
    return with_tasks_lock(_save_under_lock)(_scheduler(), task)


def _save_under_lock(scheduler, task) -> bool:
    """The read-modify-write itself; the caller holds the task lock."""
    tasks = scheduler.load_tasks()
    for index, stored in enumerate(tasks):
        if stored.task_id != task.task_id:
            continue
        same_schedule = all(getattr(stored, field, None) == getattr(task, field, None)
                            for field in SCHEDULE_FIELDS)
        stored.last_run_ts = task.last_run_ts
        stored.last_run_success = task.last_run_success
        stored.last_run_error = task.last_run_error
        if same_schedule:
            stored.next_run_ts = task.next_run_ts
            stored.status = task.status
            if task.cycle == scheduler.CYCLE_ONCE:
                stored.is_active = task.is_active
        else:
            logger.info(f"Task {task.task_id} was edited while it ran; the run's result is "
                        f"saved and the new schedule is kept")
        tasks[index] = stored
        return scheduler.save_tasks(tasks)

    logger.warning(f"Task {task.task_id} is gone - its result is not saved")
    return False
