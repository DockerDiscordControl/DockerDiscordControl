# -*- coding: utf-8 -*-
""""Create Task" in Discord refuses a date that does not exist, and says which.

THE FINDING (operator, 2026-10-05, screenshot "Yearly · 31 · February"):
the button checked only that the day lay between 1 and 31. A yearly task for
31 February was saved and ran on 28 February without a word; a one-time one
was refused as "the calculated execution time is invalid (e.g., in the past)".
The dropdowns no longer offer such dates, but a panel opened before that can
still hold one.

THE CONTRACT: no task for a date that does not exist (31 February, 29
February 2027), the user is told "There is no day 31 in February"; a date that
exists (29 February for a yearly task, 29 February 2028) is created.

HOW THIS TEST CAN FAIL: a task written for an impossible date, or a refusal
of a possible one.

COUNTER-CHECK (2026-10-05): all four impossible cases red with the check
switched off (the yearly ones were written, the one-time ones refused as "in
the past").
"""

import asyncio
from types import SimpleNamespace

import pytest

from tests.spec.test_z5_task_creation_needs_the_permission import _Created, _press, _sent


def _with_date(button, cycle, day, month, year=None):
    button._view = SimpleNamespace(selected_cycle=cycle, selected_action="restart",
                                   selected_time="04:00", selected_day=str(day),
                                   selected_month=str(month),
                                   selected_year=str(year) if year else None,
                                   container_name="vrising")


@pytest.mark.parametrize("cycle, day, month, year", [
    ("yearly", 31, 2, None), ("yearly", 31, 4, None), ("once", 29, 2, 2027), ("once", 31, 11, 2027),
])
def test_an_impossible_date_is_refused_with_a_reason(monkeypatch, cycle, day, month, year):
    button, interaction = _press(monkeypatch, schedule=True)
    _with_date(button, cycle, day, month, year)

    asyncio.run(button.callback(interaction))       # must not reach add_task

    assert f"there is no day {day} in" in _sent(interaction).lower(), _sent(interaction)


@pytest.mark.parametrize("cycle, day, month, year", [
    ("yearly", 29, 2, None), ("yearly", 31, 12, None), ("once", 29, 2, 2028),
])
def test_a_date_that_exists_is_created(monkeypatch, cycle, day, month, year):
    button, interaction = _press(monkeypatch, schedule=True)
    _with_date(button, cycle, day, month, year)

    with pytest.raises(_Created):
        asyncio.run(button.callback(interaction))
