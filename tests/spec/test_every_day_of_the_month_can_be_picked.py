# -*- coding: utf-8 -*-
"""Every day of the month can be picked when scheduling a task.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 09 F1, re-checked 2026-09-20):
``SimpleMonthdayDropdown`` offered 24 hand-picked days - the 5th, 6th, 11th,
17th, 18th, 26th and 29th were missing, with nothing in the interface saying
so. Whoever wanted a monthly restart on the 29th had no way to ask for it
here. Discord does limit a select to 25 options and a month has 31 days, so
one menu cannot hold them all; the operator chose paging (2026-09-20), which
also brings back the end of the month.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.status_info_integration import SimpleMonthdayDropdown

DISCORD_OPTION_LIMIT = 25


def _days(dropdown):
    return {int(option.value) for option in dropdown.options if option.value.isdigit()}


def _page_turners(dropdown):
    return [option.value for option in dropdown.options if not option.value.isdigit()]


def test_no_page_holds_more_than_discord_allows():
    """Premise: each page must still be a menu Discord will accept."""
    for page in (1, 2):
        assert len(SimpleMonthdayDropdown(page=page).options) <= DISCORD_OPTION_LIMIT


def test_all_31_days_are_reachable():
    reachable = _days(SimpleMonthdayDropdown(page=1)) | _days(SimpleMonthdayDropdown(page=2))

    assert reachable == set(range(1, 32)), (
        f"these days cannot be picked at all: {sorted(set(range(1, 32)) - reachable)}"
    )


def test_each_page_leads_to_the_other():
    assert _page_turners(SimpleMonthdayDropdown(page=1)), "no way from page 1 to the later days"
    assert _page_turners(SimpleMonthdayDropdown(page=2)), "no way back from page 2"


@pytest.mark.asyncio
async def test_turning_the_page_does_not_count_as_a_day():
    """The option that turns the page must not be saved as the chosen day."""
    dropdown = SimpleMonthdayDropdown(page=1)
    dropdown.row = 2
    view = MagicMock()
    view.selected_day = None
    dropdown._view = view
    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    # How py-cord fills Select.values for a string select: the interaction that
    # carried the click, plus the values it carried.
    dropdown._interaction = interaction
    dropdown._selected_values = [_page_turners(dropdown)[0]]

    await dropdown.callback(interaction)

    assert view.selected_day is None, f"the page turn was saved as a day: {view.selected_day}"
    assert view.add_item.called, "the other page was not put in place"
    interaction.response.edit_message.assert_awaited()
