# -*- coding: utf-8 -*-
"""The task dropdowns in Discord offer no date that does not exist.

THE FINDING (operator, 2026-10-05, screenshot "Yearly · 31 · February"):
after any day the month dropdown offered all twelve months. A yearly task for
31 February was accepted and ran on 28 February (29th in leap years) without
a word; a one-time task for it was refused with "the calculated execution time
is invalid (e.g., in the past)". The web panel refuses such dates.

THE CONTRACT: after the day, only months that have it (31: seven, 30:
eleven, 29: all twelve, since 29 February exists); for a one-time task, only
years in which the date exists (29 February: leap years).

HOW THIS TEST CAN FAIL: a month or year offered in which the chosen day does
not exist, or a day callback that builds the month dropdown without the day.

COUNTER-CHECK (2026-10-05): red with the filter switched off (twelve months
after the 31st, eleven years after 29 February).
"""

import calendar
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.status_info_integration import SimpleMonthdayDropdown
from cogs.task_ui import MonthDropdown, YearDropdown


def _months(dropdown):
    return [int(option.value) for option in dropdown.options]


@pytest.mark.asyncio
@pytest.mark.parametrize("day, months", [
    (31, [1, 3, 5, 7, 8, 10, 12]),
    (30, [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]),
    (29, list(range(1, 13))),
    (1, list(range(1, 13))),
])
async def test_only_months_that_have_the_day(day, months):
    assert _months(MonthDropdown(day=day)) == months


@pytest.mark.asyncio
async def test_29_february_only_in_leap_years():
    years = [int(option.value) for option in YearDropdown(day=29, month=2).options]

    assert years and all(calendar.isleap(year) for year in years), years


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle", ["yearly", "once"])
async def test_the_day_reaches_the_month_dropdown(cycle):
    dropdown = SimpleMonthdayDropdown(page=2)
    dropdown.row = 2
    view = MagicMock()
    view.selected_cycle, view.selected_action = cycle, "restart"
    view.container_name = "valheim"
    view.get_next_available_row.return_value = 3
    dropdown._view = view
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    dropdown._interaction = interaction
    dropdown._selected_values = ["31"]

    await dropdown.callback(interaction)

    added = [call.args[0] for call in view.add_item.call_args_list
             if isinstance(call.args[0], MonthDropdown)]
    assert added and 2 not in _months(added[0]), "February is offered after the 31st"
