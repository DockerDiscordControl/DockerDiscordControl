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

from utils.logging_utils import get_module_logger

logger = get_module_logger('scheduler')


def _scheduler():
    """Imported lazily: scheduler.py owns the file, this module owns the rules."""
    from services.scheduling import scheduler

    return scheduler


SCHEDULE_FIELDS = ("container_name", "action", "cycle", "cron_string", "time_str",
                   "year_val", "month_val", "day_val", "weekday_val", "timezone_str")


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
