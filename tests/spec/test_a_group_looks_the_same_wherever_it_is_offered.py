# -*- coding: utf-8 -*-
"""A group is offered like a container, and marked the same way everywhere.

THE OPERATOR'S QUESTION (2026-09-23): is a group just treated like a container,
with a marker on it, so it fits into the panel everywhere? Measured that day:
mostly yes, and the panel already has a convention for the marker. It is not a
"*", it is two shapes, one per kind of control:

    a list of tick boxes   a bi-collection icon, text-warning instead of the
                           containers' text-info, and the member count in
                           brackets - the rule editor's target list
    a <select>             an <optgroup> headed "Container groups", and the
                           member count in brackets after the name - the task
                           form's target picker
    a row about one task   the same icon and colour, plus a "Group" badge

THE GAP, measured the same day: three places did not follow it.

    tasks.js fillEditGroups   the EDIT dialog listed groups with no count,
                              while the CREATE form right beside it has one
    container_groups.js       the groups section's own list - the one page
                              that is about groups - marked them not at all
    group_bulk.js             the bar added to the container table that
                              morning: a flat select of bare names

None of them is wrong on its own; together they mean the operator has to learn
what a group looks like three times, and in the edit dialog cannot see how big
the group he is picking is.

HOW THIS TEST CAN FAIL: it reads each site and asks for the marker its kind of
control calls for. A site that drops the count, or marks a group like a
container, is red.

COUNTER-CHECK (2026-09-23): red before at all three sites; the two that
already followed the convention (the rule editor and the task form) are
checked here too, so the convention cannot be dropped where it started.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "app" / "static" / "js"
TEMPLATES = ROOT / "app" / "templates"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_the_rule_editor_still_marks_a_group():
    """Where the convention started: icon, colour and count."""
    source = _read(JS / "auto_actions.js")

    assert "bi-collection" in source
    assert "'text-warning'" in source and "'text-info'" in source
    assert "box.count" in source, "the member count is gone"


def test_the_task_list_still_marks_a_group():
    source = _read(JS / "tasks.js")

    assert "bi-collection text-warning" in source
    assert "tasks.group_badge" in source


# tasks/_edit_modal.html, not tasks/list.html: the edit dialog moved out of the
# list on 2026-09-23, because inside the settings form its own <form> was a
# nested one and the browser dropped it.
@pytest.mark.parametrize("template", ["tasks/form.html", "tasks/_edit_modal.html"])
def test_both_task_target_pickers_head_the_groups(template):
    """A <select> cannot carry an icon, so the heading is the marker."""
    source = _read(TEMPLATES / template)

    assert "<optgroup" in source and "web.groups.title" in source


def test_the_edit_dialog_says_how_big_the_group_is():
    """THE GAP: the create form appends "name (5)", the edit dialog appended
    "name". Picking a group without knowing whether it holds one container or
    seven is the difference between restarting a server and restarting a rack.
    """
    source = _read(JS / "tasks.js")
    # The DEFINITION, not the first mention: "fillEditGroups" appears at the
    # call site first, and a slice from there reads the wrong function.
    start = source.index("async fillEditGroups(")
    block = source[start:source.index("\n    }", start)]

    assert "containers || []).length" in block, "the edit dialog drops the member count"


def test_the_groups_section_marks_its_own_groups():
    """THE GAP: the page that is about groups did not mark them at all."""
    source = _read(JS / "container_groups.js")

    assert "bi-collection" in source, "the groups list has no group marker"
    assert "text-warning" in source, "a group is not coloured like a group"
    assert "containers || []).length" in source, "the list does not say how big a group is"


def test_the_groups_in_the_container_table_are_marked_as_groups():
    """THE GAP: the bar added to the container table listed bare names.

    That bar is gone (2026-09-24) - the groups are rows of the table itself
    now, which makes the marker matter MORE, not less: a group row and a
    container row are the same ten columns, and the icon, the amber and the
    member count are the only things saying which is which."""
    # Comments stripped: this file EXPLAINS the marker at length, and a test
    # that a comment can satisfy is a test that stops noticing.
    source = re.sub(r"^\s*//.*$", "", _read(JS / "group_rows.js"), flags=re.M)

    assert "collection" in source, "a group row carries no group marker"
    assert "text-warning" in source, "a group row is not coloured like a group"
    assert "member_count" in source, "the row does not say how big the group is"

    section = _read(TEMPLATES / "_server_selection.html")
    assert "bi-collection" in section, "the group heading carries no group marker"
