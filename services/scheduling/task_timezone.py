# -*- coding: utf-8 -*-
"""Moving existing scheduled tasks to a new panel timezone.

A task carries its own `_timezone_str`, so changing the panel's timezone does
not touch it: "daily 10:00" goes on firing at 10:00 in the zone it was made
in. That is the right answer when the schedule is tied to something real
elsewhere, and the wrong one when the operator has simply relocated - and
nothing outside the operator's head can tell those apart, which is why the
panel asks instead of picking one (operator decision, 2026-09-23).

This module is the "take them along" answer: the task keeps its CLOCK time
and changes its zone, so 10:00 stays 10:00 and the moment moves. The other
answer needs no code - it is what not calling this does.

It lives beside scheduler.py rather than in it because scheduler.py is at its
line ceiling; there is no other reason.
"""

import logging
from typing import List

from services.scheduling.runtime import with_tasks_lock
from services.scheduling.scheduler import ScheduledTask, load_tasks, save_tasks
from utils.logging_utils import setup_logger

logger = setup_logger('ddc.scheduler', level=logging.INFO)


def tasks_in_other_timezones(timezone_str: str) -> List[ScheduledTask]:
    """The tasks that do NOT already run in `timezone_str`.

    What the panel's question counts. An empty list means there is nothing to
    ask about, and the panel then says nothing at all.
    """
    return [task for task in load_tasks() if task.timezone_str != timezone_str]


@with_tasks_lock
def retime_tasks(timezone_str: str) -> int:
    """Move every task to `timezone_str`, keeping its clock time. Returns how
    many moved.

    The next run is recalculated afterwards, because the same wall-clock time
    in a different zone is a different moment - leaving the old timestamp
    would have the task fire once at the old moment and only then settle.

    The whole read-modify-write cycle is held under the tasks.json lock, the
    way every other writer in scheduler.py is: this reads all tasks and writes
    all of them back, so a task added in between would be replaced by a list
    that never saw it. The lock is reentrant, so the load_tasks and save_tasks
    inside take it again without blocking.

    Tasks already in that zone are left untouched, including their next run:
    recalculating theirs would push a task whose moment has passed to
    tomorrow, and a save on an unrelated settings page is no reason to skip a
    run. When nothing moves, tasks.json is not written at all.
    """
    tasks = load_tasks()
    moved = [task for task in tasks if task.timezone_str != timezone_str]
    if not moved:
        return 0

    for task in moved:
        was = task.timezone_str
        task.timezone_str = timezone_str
        task.next_run_ts = task.calculate_next_run()
        logger.info("Task %s moved from %s to %s, next run %s",
                    task.task_id, was, timezone_str, task.next_run_ts)

    save_tasks(tasks)
    return len(moved)
