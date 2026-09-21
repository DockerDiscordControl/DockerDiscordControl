# -*- coding: utf-8 -*-
"""Discord shows 25 options. The 26th container must not just disappear.

THE FINDING (review E37, cogs/control_ui.py): both container dropdowns build
their options with ``containers[:25]``, because that is Discord's hard limit
on a select. Everything past the twenty-fifth is dropped, and nothing anywhere
says so - not in the dropdown, not in the log.

An operator running thirty containers opens the admin panel, sees
twenty-five, and **cannot control the other five from Discord at all.** There
is no message, no marker, no hint that a list was cut: it looks exactly like a
configuration that only has twenty-five containers in it.

The project has already met this limit once and answered it properly:
``SimpleMonthdayDropdown`` pages through a month's 31 days
(``status_info_integration.py:1744``, "Discord shows at most 25 options in one
select, and a month has 31 days"). So paging is the right answer here too -
but it is a feature, not a repair, and it is written up as a question for the
operator in ``docs/quality/reviews/CONTROL_UI.md`` rather than built
unasked.

What is fixed here is the silence. The placeholder says how many of how many
are shown, so the operator can see a list has been cut while looking at it,
and a warning names the ones that were left out.

``control_helpers.container_select`` also truncates at 25 and is deliberately
NOT changed: it is a Discord AUTOCOMPLETE, where narrowing by typing is how
the interface works and twenty-five suggestions is the normal contract.
"""

import logging

import pytest


def _containers(count):
    return [{"display": f"Container {i:02d}", "name": f"c{i:02d}",
             "docker_name": f"c{i:02d}", "order": i} for i in range(count)]


@pytest.mark.parametrize("dropdown_name,extra", [
    ("ContainerInfoDropdown", ()),
    ("AdminContainerDropdown", (111,)),
])
def test_a_cut_list_says_how_many_are_shown(dropdown_name, extra, caplog):
    import cogs.control_ui as control_ui

    dropdown_class = getattr(control_ui, dropdown_name)
    with caplog.at_level(logging.DEBUG):
        dropdown = dropdown_class(None, _containers(30), *extra)

    assert len(dropdown.options) == 25, "Discord's own limit still applies"
    assert "25" in dropdown.placeholder and "30" in dropdown.placeholder, (
        f"the operator is looking at 25 of 30 containers and the dropdown does "
        f"not say so: {dropdown.placeholder!r}"
    )


@pytest.mark.parametrize("dropdown_name,extra", [
    ("ContainerInfoDropdown", ()),
    ("AdminContainerDropdown", (111,)),
])
def test_the_missing_ones_are_named_in_the_log(dropdown_name, extra, caplog):
    import cogs.control_ui as control_ui

    dropdown_class = getattr(control_ui, dropdown_name)
    with caplog.at_level(logging.DEBUG):
        dropdown_class(None, _containers(30), *extra)

    warnings = " ".join(r.getMessage() for r in caplog.records
                        if r.levelno >= logging.WARNING)
    assert warnings, "a list was silently cut and nothing was logged"
    assert "c29" in warnings or "5" in warnings, (
        f"the log does not say WHICH containers were left out: {warnings!r}"
    )


@pytest.mark.parametrize("dropdown_name,extra", [
    ("ContainerInfoDropdown", ()),
    ("AdminContainerDropdown", (111,)),
])
def test_a_list_that_fits_is_left_alone(dropdown_name, extra, caplog):
    """Counter-check: the normal case must stay quiet and unmarked."""
    import cogs.control_ui as control_ui

    dropdown_class = getattr(control_ui, dropdown_name)
    with caplog.at_level(logging.DEBUG):
        dropdown = dropdown_class(None, _containers(7), *extra)

    assert len(dropdown.options) == 7
    assert "7" not in dropdown.placeholder, (
        f"a list that fits was marked as cut: {dropdown.placeholder!r}"
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "seven containers produced a warning"
    )
