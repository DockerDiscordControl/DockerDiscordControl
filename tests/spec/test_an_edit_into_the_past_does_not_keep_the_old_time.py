# -*- coding: utf-8 -*-
"""An edit to a time that has passed does not leave the old run time standing.

THE FINDING: calculate_next_run() writes self.next_run_ts only when a
calculator returned something. For a one-time task moved to a time already
past, the calculator answers None on purpose - and the PREVIOUS next_run_ts
stays. The panel's edit path then checks that stale value against "is it in
the past?", finds a future timestamp, saves the task and answers "Task
updated successfully".

So an operator who moves "restart plex on 1 December" to a time earlier
today gets a task that is still armed for 1 December - the date they just
removed - and nothing says so.

A recalculation that fails now clears the time it could not compute.

COUNTER-CHECK (2026-09-22): red before - next_run_ts kept the December
timestamp; a recurring task must still keep a real next run (third test).
"""

import time

import pytest

from services.scheduling.scheduler import CYCLE_DAILY, CYCLE_ONCE, ScheduledTask


def _task(cycle, **schedule):
    """A task as the panel builds it: the times live in schedule_details."""
    details = {"time": "10:00"}
    details.update(schedule)
    return ScheduledTask(container_name="plex", action="restart", cycle=cycle,
                         schedule_details=details, timezone_str="Europe/Berlin",
                         is_active=True)


def test_a_one_time_task_moved_into_the_past_has_no_next_run():
    task = _task(CYCLE_ONCE, year=2099, month=12, day=1)
    task.calculate_next_run()
    assert task.next_run_ts and task.next_run_ts > time.time(), "premise: it is armed"

    task.year_val, task.month_val, task.day_val = 2020, 1, 1   # the operator moves it back
    assert task.calculate_next_run() is None

    assert task.next_run_ts is None, (
        "the task is still armed for the date the operator removed")


def test_a_daily_task_keeps_a_real_next_run():
    """Counter-check: a calculation that works must not be cleared."""
    task = _task(CYCLE_DAILY)

    assert task.calculate_next_run() is not None
    assert task.next_run_ts > time.time()


def test_a_recalculated_daily_task_moves_forward():
    """Counter-check: the ordinary recalculation still replaces the value."""
    task = _task(CYCLE_DAILY)
    task.calculate_next_run()
    first = task.next_run_ts

    task.time_str = "23:59"
    task.calculate_next_run()

    assert task.next_run_ts != first
