# -*- coding: utf-8 -*-
"""Channel row 51 is read like any other, not dropped and then deleted.

THE FINDING (independent review of the web panel, 2026-09-23): the form parser
walks a FIXED range of rows, ``range(1, MAX_CHANNEL_ROWS + 1)`` with
MAX_CHANNEL_ROWS = 50. The panel's own JavaScript has no such cap:
``getNextRowIndex`` simply returns max+1, so it will happily number a row 51,
or 137.

A row the parser never reads is absent from channel_permissions - and
save_all_channels removes every ``<channel_id>.json`` that is not in the parsed
set. So those channels do not merely fail to save: their permissions are
DELETED, the bot stops posting there and refuses commands there, and the panel
says "Configuration saved successfully."

find_unusable_channel_ids walks the same fixed range, so the warning machinery
that exists for a mistyped ID cannot see these either.

The cliff is reachable two ways: 51 channels of one kind, or - much cheaper -
about fifty add-and-delete cycles in one page session, because the next index
keeps climbing while the row count does not.

This is the same class as the gap the comment above _parse_channel_type already
describes (review B, section 11 F4): the gap was closed by walking every slot,
the CEILING stayed. The rows the form actually carries are now what is read, so
there is no ceiling to fall off.

HOW THIS TEST CAN FAIL: it submits rows numbered past 50 and asks what was
parsed. A missing channel is red.

COUNTER-CHECK (2026-09-23): red before - channels 51 and 137 were simply
absent. The last tests keep the rest: a mistyped ID is still skipped AND
still named, and an ordinary form parses exactly as before.
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService

parse = ConfigFormParserService.parse_channel_permissions_from_form
unusable = ConfigFormParserService.find_unusable_channel_ids


def _row(prefix, index, channel_id, name="a channel"):
    return {
        f"{prefix}_channel_id_{index}": channel_id,
        f"{prefix}_channel_name_{index}": name,
    }


def _form(*rows):
    form = {}
    for row in rows:
        form.update(row)
    return form


def _id(n):
    """A believable 18-digit Discord channel ID."""
    return str(100000000000000000 + n)


def test_a_row_past_the_old_ceiling_is_read():
    """THE FINDING: it was dropped, and then its permissions were deleted."""
    form = _form(*[_row("status", n, _id(n)) for n in range(1, 61)])

    parsed = parse(form)

    assert len(parsed) == 60, f"only {len(parsed)} of 60 channels survived the parse"
    assert _id(51) in parsed and _id(60) in parsed


def test_a_high_row_number_from_adding_and_deleting_is_read():
    """The cheaper route: the next index climbs, the row count does not."""
    form = _form(_row("status", 1, _id(1)), _row("status", 137, _id(137)))

    parsed = parse(form)

    assert _id(137) in parsed, (
        "a row the operator had just added was not read, and saving would then "
        "have deleted that channel's permissions")


def test_control_rows_past_the_ceiling_are_read_too():
    """Both tables are numbered independently."""
    form = _form(*[_row("control", n, _id(n)) for n in range(1, 56)])

    parsed = parse(form)

    assert len(parsed) == 55
    assert parsed[_id(55)]["commands"]["control"] is True


def test_a_mistyped_id_past_the_ceiling_is_still_named():
    """The warning machinery must reach as far as the parser does."""
    form = _form(_row("status", 1, _id(1)), _row("status", 60, "12345"))

    assert "12345" in unusable(form), (
        "a mistyped ID in a high row was skipped without being named - and a "
        "skipped row loses that channel's permissions")


def test_a_mistyped_id_is_still_skipped():
    """Counter-check: reading further must not mean accepting rubbish."""
    form = _form(_row("status", 1, _id(1)), _row("status", 2, "not-an-id"))

    parsed = parse(form)

    assert list(parsed) == [_id(1)]
    assert "not-an-id" in unusable(form)


def test_an_ordinary_form_parses_exactly_as_before():
    """Counter-check: the everyday case, three channels of each kind."""
    form = _form(*[_row("status", n, _id(n)) for n in (1, 2, 3)],
                 *[_row("control", n, _id(10 + n)) for n in (1, 2, 3)])

    parsed = parse(form)

    assert len(parsed) == 6
    assert parsed[_id(1)]["commands"]["control"] is False
    assert parsed[_id(11)]["commands"]["control"] is True
    assert unusable(form) == []


def test_an_empty_form_still_parses_to_nothing():
    """Counter-check: the 'delete all channels' case is untouched."""
    assert parse({}) == {}
    assert unusable({}) == []
