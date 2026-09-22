# -*- coding: utf-8 -*-
"""A label that wraps does not push its input field out of line.

THE FINDING (operator, 2026-09-22, screenshot of the German panel): in
"Web-UI-Authentifizierung" the middle label - "Neues Passwort (leer lassen,
um aktuelles beizubehalten)" - needs two lines, and its input field sits a
line lower than the two beside it. The columns align their content at the
top, so the longest label decides where its own field lands. It happens in
any language whose label is longer than the column, so shortening one
translation would not fix it.

The three columns lay their content out as a column and push the input to
the bottom, so all three fields sit on one line whatever the labels do.

COUNTER-CHECK (2026-09-22): red before - no column carried the flex class
and no input the mt-auto that holds it at the bottom.
"""

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[2] / "app" / "templates" / "_auth_settings.html"
FIELDS = ("web_ui_user", "new_web_ui_password", "confirm_web_ui_password")


@pytest.fixture
def markup():
    return TEMPLATE.read_text(encoding="utf-8")


def _column_of(markup, field):
    """The column <div> that holds this field."""
    position = markup.index(f'id="{field}"')
    start = markup.rindex('<div class="col-md-4', 0, position)
    return markup[start:position]


@pytest.mark.parametrize("field", FIELDS)
def test_every_column_lays_its_content_out_as_a_column(markup, field):
    column = _column_of(markup, field)
    assert "d-flex" in column and "flex-column" in column, column.split(">")[0]


@pytest.mark.parametrize("field", FIELDS)
def test_every_input_is_held_at_the_bottom(markup, field):
    line = next(line for line in markup.splitlines() if f'id="{field}"' in line)
    assert re.search(r'class="[^"]*\bmt-auto\b', line), line.strip()


def test_the_three_fields_are_still_side_by_side(markup):
    """Counter-check: the fix must not turn the row into three rows."""
    assert markup.count('<div class="col-md-4') == 3
    assert '<div class="row"' in markup or '<div class="row">' in markup
