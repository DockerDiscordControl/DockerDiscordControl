# -*- coding: utf-8 -*-
"""
THE FEATURE (review E37, asked and answered by the operator 2026-09-22):
Discord shows at most 25 options in one select. It is a hard limit of the
platform, not a choice DDC gets to make.

E37 repaired the *silence*: both container dropdowns did `containers[:25]`,
so an operator running thirty containers saw twenty-five and could not reach
the other five from Discord at all - with no message, no marker, nothing in
the log. After E37 the placeholder said "(25/30)" and a warning named the ones
left out. The containers were still unreachable; the operator could just see
that they were.

This builds the real answer, the one the project had already built once for
the 31 days of a month (`SimpleMonthdayDropdown`, review B21): the list
**pages**. Nothing is left out any more.

The rule this file holds is one sentence:

    every container in the list is reachable from some page.

That is what a `containers[:25]` can never satisfy, and it is the assertion
that fails if a future change quietly starts cutting again.

The counter-checks matter as much: an install with seven containers - which
is every install this was ever reported from - must see exactly seven options,
no arrows, no markers, and nothing in the log. Paging that shows itself when
it is not needed is a regression, not a feature.

`control_helpers.container_select` still truncates at 25 and is deliberately
NOT paged: it is a Discord AUTOCOMPLETE, where narrowing by typing is how the
interface works and twenty-five suggestions is the normal contract.

This file REPLACES `test_a_container_beyond_the_limit_is_not_hidden.py`, which
pinned E37's warning: "25 of 30 are shown, here are the five that are not".
That guarantee is strictly weaker than this one and can no longer be true at
the same time - there is nothing left to warn about. Its counter-check, that a
list which fits is left completely alone, is kept below.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as control_ui


DROPDOWNS = [
    ("ContainerInfoDropdown", (), "name"),
    ("AdminContainerDropdown", (111,), "docker_name"),
]


def _containers(count):
    return [{"display": f"Container {i:02d}", "name": f"c{i:02d}",
             "docker_name": f"c{i:02d}", "order": i} for i in range(count)]


def _build(dropdown_name, extra, containers, page=0):
    cls = getattr(control_ui, dropdown_name)
    return cls(None, containers, *extra, page=page)


def _real_values(dropdown):
    """The option values that are containers, not page arrows."""
    arrows = {control_ui.SELECT_PAGE_PREV, control_ui.SELECT_PAGE_NEXT}
    return [o.value for o in dropdown.options if o.value not in arrows]


def _arrows(dropdown):
    arrows = {control_ui.SELECT_PAGE_PREV, control_ui.SELECT_PAGE_NEXT}
    return [o.value for o in dropdown.options if o.value in arrows]


# --------------------------------------------------------------------------- #
# The one sentence
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dropdown_name,extra,key", DROPDOWNS)
@pytest.mark.parametrize("count", [26, 30, 51, 74])
def test_every_container_is_reachable_from_some_page(dropdown_name, extra, key, count):
    """THE FEATURE: walk every page and account for every container."""
    containers = _containers(count)

    seen = []
    page = 0
    while True:
        dropdown = _build(dropdown_name, extra, containers, page=page)
        assert len(dropdown.options) <= 25, (
            f"page {page} offers {len(dropdown.options)} options; Discord takes 25"
        )
        seen.extend(_real_values(dropdown))
        if control_ui.SELECT_PAGE_NEXT not in _arrows(dropdown):
            break
        page += 1
        assert page < 100, "the pages never ran out - the next arrow loops"

    expected = [c[key] for c in containers]
    assert seen == expected, (
        f"{len(expected) - len(set(seen) & set(expected))} of {count} containers "
        f"cannot be reached from any page"
    )


@pytest.mark.parametrize("dropdown_name,extra,key", DROPDOWNS)
def test_the_first_page_has_no_way_back_and_the_last_no_way_on(dropdown_name, extra, key):
    containers = _containers(30)

    first = _build(dropdown_name, extra, containers, page=0)
    assert control_ui.SELECT_PAGE_PREV not in _arrows(first), (
        "the first page offers a way back to nowhere"
    )
    assert control_ui.SELECT_PAGE_NEXT in _arrows(first)

    last = _build(dropdown_name, extra, containers, page=1)
    assert control_ui.SELECT_PAGE_PREV in _arrows(last)
    assert control_ui.SELECT_PAGE_NEXT not in _arrows(last), (
        "the last page offers a way on to nowhere"
    )


@pytest.mark.parametrize("dropdown_name,extra,key", DROPDOWNS)
async def test_choosing_the_arrow_turns_the_page(dropdown_name, extra, key):
    """The arrow is not a container: picking it must swap the dropdown for the
    next page in the same view, not try to control something called '→'."""
    containers = _containers(30)
    dropdown = _build(dropdown_name, extra, containers, page=0)

    view = MagicMock()
    view.children = [dropdown]
    removed, added = [], []
    view.remove_item = removed.append
    view.add_item = added.append
    dropdown._view = view

    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.user = SimpleNamespace(id=4711, name="someone")
    interaction.channel = SimpleNamespace(id=111)
    dropdown._interaction = interaction
    dropdown._selected_values = [control_ui.SELECT_PAGE_NEXT]

    await dropdown.callback(interaction)

    assert removed == [dropdown], "the old page was not taken out of the view"
    assert len(added) == 1, "no new page was put in"
    assert added[0].page == 1, f"the arrow led to page {added[0].page}, not page 1"
    assert interaction.response.edit_message.await_count == 1, (
        "the message was never redrawn, so the operator sees the old page"
    )


# --------------------------------------------------------------------------- #
# Counter-checks: the seven-container install must not notice any of this
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dropdown_name,extra,key", DROPDOWNS)
def test_a_list_that_fits_has_no_arrows_and_no_marker(dropdown_name, extra, key, caplog):
    with caplog.at_level(logging.DEBUG):
        dropdown = _build(dropdown_name, extra, _containers(7))

    assert len(dropdown.options) == 7, "seven containers, seven options"
    assert not _arrows(dropdown), "a list that fits was given page arrows"
    assert "7" not in dropdown.placeholder, (
        f"a list that fits was marked as paged: {dropdown.placeholder!r}"
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "seven containers produced a warning"
    )


@pytest.mark.parametrize("dropdown_name,extra,key", DROPDOWNS)
def test_exactly_twenty_five_still_fits_on_one_page(dropdown_name, extra, key):
    """The boundary. 25 is what Discord takes, so 25 needs no paging at all."""
    dropdown = _build(dropdown_name, extra, _containers(25))

    assert len(dropdown.options) == 25
    assert not _arrows(dropdown), "twenty-five containers were split for no reason"
