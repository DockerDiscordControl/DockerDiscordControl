# -*- coding: utf-8 -*-
"""Making a group happens in a dialog, opened from where groups are used.

THE OPERATOR'S DECISION (2026-09-24): the group editor was a full section on
the settings page - a name field, a save button and a picker listing every
container DDC steers. It is the only part of the Containers tab that is not
about the containers themselves, and it is needed rarely: groups are made once
and used often.

It moves into a dialog, opened by a + where the groups themselves are shown.
That is where the operator already is when he discovers a group is missing or
wrong, so the shortest path from "I need a group" to "I have one" is one
click, and the page loses a section it mostly scrolled past.

WHERE THAT + SITS was rewritten on 2026-09-24: the bulk bar it was added to is
gone, and the groups are rows of the container table now
(test_a_group_is_a_row_like_a_container.py). The + moved with them, into the
heading that separates the group rows from the containers - still one click
from what it makes, just beside a different thing.

WHAT THAT COSTS, and it is the reason the nav lists change with it: the
section had a dot in the floating navigation and a place in the tab grouping.
A dot pointing at an id that no longer renders scrolls nowhere and says
nothing about why, so both lists lose that entry. Its test says so too.

WHAT DOES NOT CHANGE: the editor itself. Same markup, same container_groups.js,
same /api/groups. It saves through its own fetch and holds no field of the
settings form, so it can live outside <form id="config-form"> - which is where
a modal belongs anyway, beside the eight others.

HOW THIS TEST CAN FAIL: leaving the editor inline, putting the dialog inside
the settings form, or offering no way to open it beside the groups.

COUNTER-CHECK (2026-09-24): red before - the editor was included inline in the
Containers pane and nothing opened a dialog.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"
PAGE = TEMPLATES / "config.html"
SECTION = TEMPLATES / "_server_selection.html"
EDITOR = TEMPLATES / "_container_groups.html"


def _without_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_editor_is_a_dialog():
    editor = _without_comments(EDITOR.read_text(encoding="utf-8"))

    assert 'id="containerGroupsModal"' in editor, "the editor is not a dialog"
    assert 'class="modal fade' in editor


def test_the_dialog_is_outside_the_settings_form():
    """It saves through its own fetch to /api/groups and holds no field of the
    settings form. A modal inside that form would be one more thing the save
    has to ignore - and nested forms are what bit the task dialog."""
    page = PAGE.read_text(encoding="utf-8")
    opens = page.index('id="config-form"')
    after_form = page.index('id="save-notification"')
    position = page.index("_container_groups.html")

    assert not (opens < position < after_form), (
        "the group dialog is included inside the settings form")


def test_the_table_offers_a_way_to_make_one():
    """THE POINT: the shortest path from "this group is missing something" to
    "fixed" is a click, not a scroll to another section."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="group-rows-new"' in section, (
        "there is no way to open the group editor from the container table")
    position = section.index('id="group-rows-new"')
    button = section[section.rindex("<button", 0, position):section.index(">", position)]

    assert "containerGroupsModal" in button, "the button opens nothing"
    assert 'type="button"' in button, (
        "a button without type=button submits the settings form it sits in")


def test_it_sits_with_the_groups():
    """A + that is not beside the thing it adds to is a scavenger hunt. It is
    in the heading of the group rows, so it is the first thing in reach of an
    operator who has no groups at all - and that heading shows even then."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))
    heading = section.index('id="group-rows-heading"')
    plus = section.index('id="group-rows-new"')
    rows = section.index('id="group-rows"', heading + 1)

    assert 0 < plus - heading < 900, (
        f"the + is {plus - heading} characters from the group heading")
    assert plus < rows, "the + is below the rows it makes"


def test_the_navigation_no_longer_points_at_a_section_that_is_gone():
    """A dot pointing at an id nothing renders scrolls nowhere and explains
    nothing. Both lists that named it are updated."""
    nav = TEMPLATES / "base.html"
    script = ROOT / "app" / "static" / "js" / "floating_nav.js"

    assert 'href="#container-groups"' not in nav.read_text(encoding="utf-8"), (
        "the floating navigation still has a dot for the old section")
    assert "'container-groups'" not in script.read_text(encoding="utf-8"), (
        "the active-section list still names the old section")


def test_the_editor_still_works_the_way_it_did():
    """Counter-check on the move: same script, same route, same picker."""
    editor = EDITOR.read_text(encoding="utf-8")

    assert "DDC_GROUP_TEXTS" in editor, "the editor lost its texts"
    assert 'id="group-containers"' in editor and 'id="group-name"' in editor
    assert 'id="group-save-btn"' in editor
