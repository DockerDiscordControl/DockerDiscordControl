# -*- coding: utf-8 -*-
""""Monthly on the 31st" runs every month, on the last day of the short ones.

THE FINDING (independent review of the scheduler, 2026-09-23): the same
question - what does a day that this month does not have mean? - got three
different answers, and the one the operator meets most often was the silent
one. Measured before the change:

* MONTHLY, day 31: the months without a 31st were skipped, so the task ran
  SEVEN times a year while the panel called it monthly. It was said only at
  DEBUG level, which is to say nowhere the operator looks.
* YEARLY, 29 February: clamped to the 28th in ordinary years and back to the
  29th in leap years, and said so at INFO level.
* The Discord validator, yearly: refused 29 February outright - the one date
  the calculation above handles on purpose.

The operator decided (2026-09-23): monthly clamps to the last day of the
month, like yearly already does, and Discord accepts 29 February.

So "monthly on the 31st" is twelve runs a year: 31, 30 or 28/29, whichever
the month ends on. A task that ran seven times a year now runs twelve - that
is the point, and it is in the release notes.

HOW THIS TEST CAN FAIL: it asks a task scheduled for the 31st for its next run
from inside a 30-day month. If the answer is in the month after, the skip is
back and the test is red.

COUNTER-CHECK (2026-09-23): red before - the next run from mid-April jumped to
31 May. The last two tests hold the everyday case: a day the month really has
is not moved, and February is not clamped for a task that asks for the 1st.
"""

import calendar
from datetime import datetime

import pytest
import pytz

from services.scheduling import scheduler


def _monthly_task(day):
    return scheduler.ScheduledTask(container_name="nginx", action="restart", cycle="monthly",
                                   day=day, hour=3, minute=0, timezone_str="UTC")


def _next_run_from(task, now_dt):
    """The next run this task would compute if now were ``now_dt`` (UTC)."""
    tz = pytz.timezone("UTC")
    return task._calculate_monthly_next_run(tz, tz.localize(now_dt), 3, 0)


def test_the_31st_lands_on_the_30th_in_a_30_day_month():
    """April has no 31st, so the run is on the 30th - not in May."""
    run = _next_run_from(_monthly_task(31), datetime(2026, 4, 15, 12, 0))

    assert (run.year, run.month, run.day) == (2026, 4, 30), (
        f"a monthly task skipped April altogether: {run}")


def test_the_31st_lands_on_the_last_day_of_february():
    """The shortest month, and a leap year gives the 29th."""
    ordinary = _next_run_from(_monthly_task(31), datetime(2026, 2, 10, 12, 0))
    leap = _next_run_from(_monthly_task(31), datetime(2028, 2, 10, 12, 0))

    assert (ordinary.month, ordinary.day) == (2, 28)
    assert (leap.month, leap.day) == (2, 29)


def test_a_monthly_task_runs_twelve_times_a_year():
    """The whole point: twelve occurrences, one per month."""
    task = _monthly_task(31)
    months = []
    at = datetime(2026, 1, 1, 12, 0)
    for _ in range(12):
        run = _next_run_from(task, at)
        months.append((run.month, run.day))
        at = run.replace(tzinfo=None)

    assert [month for month, _ in months] == list(range(1, 13)), (
        f"a monthly task did not run in every month: {months}")
    assert all(day == calendar.monthrange(2026, month)[1] for month, day in months)


def test_a_day_the_month_really_has_is_not_moved():
    """Counter-check: the everyday case is untouched."""
    run = _next_run_from(_monthly_task(15), datetime(2026, 4, 1, 12, 0))

    assert (run.month, run.day) == (4, 15)


def test_the_day_stored_on_the_task_does_not_change():
    """Counter-check: clamping is per month, not a rewrite of the schedule."""
    task = _monthly_task(31)
    _next_run_from(task, datetime(2026, 4, 15, 12, 0))

    assert str(task.day_val) == "31", (
        "the task's own day was rewritten, so it would stay on the 30th forever")


def test_discord_accepts_the_29th_of_february_for_a_yearly_task():
    """The calculation handles it; the validator refused it. Now it does not."""
    valid, message = scheduler.validate_new_task_input(
        container_name="nginx", action="restart", cycle="yearly",
        month=2, day=29, hour=3, minute=0)

    assert valid, f"Discord still refuses 29 February: {message}"


def test_discord_still_refuses_a_date_that_exists_in_no_year():
    """Counter-check: 31 February is not a date, leap year or not."""
    valid, _ = scheduler.validate_new_task_input(
        container_name="nginx", action="restart", cycle="yearly",
        month=2, day=31, hour=3, minute=0)

    assert not valid
