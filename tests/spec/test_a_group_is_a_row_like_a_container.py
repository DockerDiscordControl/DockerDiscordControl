# -*- coding: utf-8 -*-
"""A group is a row in the container table, set apart from the containers.

OPERATOR DECISION (2026-09-24): the "apply to group" bar was still hard to
understand - pick a group from a dropdown, tick four boxes somewhere else,
press Apply. He asked for the group to behave like a container and to be shown
like one: its own row, in the same table, with the same columns, below the
individual containers and clearly separated from them. Up to seven groups to a
page, with the same page switcher the containers have.

SO THE BAR GOES, and with it the idea behind it. I first built the row so that
ticking Restart on a group ticked Restart on each of its containers, tri-state
and all, and he corrected it the same evening: a group is DECOUPLED from the
single-container control. A container that is switched off in DDC, or that may
only be stopped on its own, can sit in a group that is allowed to do anything
else. A group summarising its members can never say that.

So the row edits the GROUP's own Active and its own four actions, which live
in groups.json beside its name and members
(test_a_group_carries_its_own_permissions.py). It reads no container box and
writes none. There is no Apply and no Save here either: the containers are
saved with the settings form, a group is its own file behind /api/groups, and
a tick goes straight there.

IT ALSO FIXES A BUG THE OPERATOR HIT: a group made in the dialog did not
appear in the old dropdown until the page was reloaded, because the dropdown
was filled once on load. The rows are rebuilt whenever the dialog saves or
deletes, so a new group is there immediately.

HOW THIS TEST CAN FAIL: keeping the bar, losing the separation between groups
and containers, losing the pager, or going back to a row that reads or writes
its containers' boxes.

COUNTER-CHECK (2026-09-24): red before - there was a bulk bar, no group rows
and no tri-state anywhere.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"
SECTION = TEMPLATES / "_server_selection.html"
ROWS = ROOT / "app" / "static" / "js" / "group_rows.js"


def _without_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_old_bar_is_gone():
    """Everything it did is in the row now; two ways to do one thing is one
    too many, and the bar was the one he could not read."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="bulk-group-bar"' not in section, "the apply-to-group bar is still there"
    assert 'id="bulk-apply-btn"' not in section


def test_the_groups_have_their_own_body_in_the_same_table():
    """Same table, so the columns line up without being kept in step by hand."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="group-rows"' in section, "there is no place for the group rows"
    table_start = section.index("<table")
    table_end = section.index("</table>")
    assert table_start < section.index('id="group-rows"') < table_end, (
        "the group rows are outside the container table, so the columns are "
        "only aligned by luck")
    assert section.index('id="docker-container-list"') < section.index('id="group-rows"'), (
        "the groups are above the containers")


def test_the_groups_are_set_apart():
    """Below the containers AND visibly separate - otherwise a group reads as
    just another container with a strange name."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="group-rows-heading"' in section, (
        "nothing separates the groups from the containers above them")


def test_the_groups_have_a_pager_of_their_own():
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="group-rows-pager"' in section
    assert section.count('data-per-page="7"') >= 2, (
        "the group rows do not say how many fit on a page")


def test_a_group_row_does_not_touch_a_container_at_all():
    """THE CORRECTION, pinned: no member's box is read and none is written.

    The comments are stripped first - they talk about `allow_` and
    `selected_servers` precisely because the row must not use them, and my own
    comments have defeated my own tests four times already."""
    source = _without_comments(ROWS.read_text(encoding="utf-8"))

    assert "allow_" not in source, (
        "the group row writes a container's permission boxes - a group is "
        "decoupled from the single-container control")
    assert "selected_servers" not in source, (
        "the group row switches containers on, which is the design the "
        "operator rejected")
    assert "docker-container-list" not in source, (
        "the group row reaches into the container table")


def test_the_row_shows_the_groups_own_permissions():
    """They are the group's, so they come from the group and go back to it."""
    source = _without_comments(ROWS.read_text(encoding="utf-8"))

    assert "allowed_actions" in source, "the row does not read the group's permissions"
    assert "'/api/groups'" in source, "the row has nowhere to save them"
    assert "indeterminate" not in source, (
        "the row still draws a group as a summary of its members")


def test_the_rows_come_back_when_a_group_is_made():
    """THE BUG THE OPERATOR HIT: he made a group and it was not there."""
    source = _without_comments(ROWS.read_text(encoding="utf-8"))
    editor = _without_comments(
        (ROOT / "app" / "static" / "js" / "container_groups.js").read_text(encoding="utf-8"))

    assert "ddc:groups-changed" in source, "nothing listens for a new group"
    assert "ddc:groups-changed" in editor, (
        "the dialog saves without telling anyone, so the rows stay as they "
        "were until the page is reloaded")


def test_the_editor_is_still_reachable():
    """The + moved with the bar it sat in."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert "containerGroupsModal" in section, "there is no way to make a group"


def test_the_rules_hold_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/group_rows.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "group_rows.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 8, result.stdout


# --- the two texts the rows need ------------------------------------------
# Carried over from test_the_container_table_can_act_on_a_group.py, which went
# with the bar it tested: the bar's eight keys are deleted and these two took
# their place. The checks are the ones that caught real gaps back then - a key
# missing from a locale, and a "translation" that is still the English text.

KEYS = ("web.server.group_rows_hint", "web.server.group_members",
        "web.server.group_save_failed")


def _locales():
    return sorted(p for p in (ROOT / "locales").glob("*.json") if p.name != "meta.json")


def test_every_locale_has_the_new_texts():
    import json

    locales = _locales()

    assert len(locales) >= 40, f"only {len(locales)} locale files were found"
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in KEYS if key not in catalogue]

        assert missing == [], (path.name, missing)


def test_the_german_texts_are_really_german():
    """A key copied into de.json with the English text still in it is the way
    this has gone wrong before: present, formatted, and not German."""
    import json

    german = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    same = [key for key in KEYS if german[key] == english[key]]

    assert same == [], f"these are still the English texts: {same}"


def test_the_member_count_keeps_its_placeholder():
    """group_rows.js replaces {count}; a translation that dropped it would
    print a fixed string where the size of the group should be."""
    import json

    for path in _locales():
        text = json.loads(path.read_text(encoding="utf-8"))["web.server.group_members"]

        assert "{count}" in text, f"{path.name} has no place for the number"


# --- the search finds them too ----------------------------------------------
# THE GAP (2026-09-24): the search box above the table filters the container
# rows and left the group rows standing, whatever was typed. With one group
# that is invisible; with twenty it is a table that ignores the search.

def test_the_search_filters_the_groups_as_well():
    source = _without_comments(ROWS.read_text(encoding="utf-8"))

    assert "container-search" in source, (
        "the group rows do not listen to the search box")
    assert "groupMatches" in source, "there is no rule for what a group matches"


def test_a_group_matches_by_its_members_too():
    """Typing a container's name shows the container AND the groups it is in -
    which is the question an operator actually has when they type one."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/group_rows.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "group_rows.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "matches" in result.stdout, result.stdout
