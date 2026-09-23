# -*- coding: utf-8 -*-
"""The long lists are paged, not scrolled inside a box.

OPERATOR DECISION (2026-09-24): the container table was given a 70vh scroll
box that morning, with a sticky header so the column names stayed visible
while the rows moved under them. He looked at it and said the inner scrolling
is not nice - show seven rows and put a page switcher underneath. The same for
the group picker.

He is right, and it also removes the thing the scroll box was for. The sticky
header existed BECAUSE the box scrolled; with seven rows the header never
leaves the screen, so the box, its height and the sticky rule all go together.
One idea instead of three.

WHAT PAGING MUST NOT BREAK: a row that is not on the current page is hidden,
not removed. Every container row carries eighteen form fields, thirteen of
them hidden round-trip values, and saveConfigAjax collects what is inside
#config-form. A removed row would be absent from the save, and the handler
reads an absent checkbox as OFF - the whole container's permissions would go
quiet. Hiding keeps them submitted.

THE CASE THAT BITES, and it is why clamping is tested in node: the operator is
on page 4, types three letters into the search, and five rows match. Page 4 of
1 is nothing at all - an empty table and no message. The page comes back to
the last one that exists.

HOW THIS TEST CAN FAIL: bringing the scroll box back, removing rows instead of
hiding them, or losing the pager.

COUNTER-CHECK (2026-09-24): red before - max-height: 70vh on the table box, a
sticky thead, and no pager anywhere.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"
TABLE = TEMPLATES / "_server_selection.html"
EDITOR = TEMPLATES / "_container_groups.html"
PAGING = ROOT / "app" / "static" / "js" / "paging.js"


def _without_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_container_table_no_longer_scrolls_inside_itself():
    """THE OPERATOR'S POINT."""
    table = _without_comments(TABLE.read_text(encoding="utf-8"))
    position = table.index("table-responsive")
    box = table[position:table.index(">", position)]

    assert "max-height" not in box, (
        "the table still scrolls inside a box of its own")


def test_the_sticky_header_went_with_it():
    """It existed only because the box scrolled. With seven rows the column
    names never leave the screen, so keeping the rule would be a seam for
    nothing."""
    table = _without_comments(TABLE.read_text(encoding="utf-8"))

    assert "position: sticky" not in table, (
        "the sticky header outlived the scroll box it was written for")


def test_both_long_lists_have_a_pager():
    for path, pager in ((TABLE, "container-pager"), (EDITOR, "group-pager")):
        markup = _without_comments(path.read_text(encoding="utf-8"))
        assert f'id="{pager}"' in markup, f"{path.name} has no page switcher"


def test_a_row_off_the_page_is_hidden_and_not_removed():
    """THE ASSERTION THAT GUARDS THE SAVE: a container row carries eighteen
    form fields. Removed, they are absent from the next save, and the handler
    reads an absent checkbox as off."""
    source = PAGING.read_text(encoding="utf-8")

    assert ".hidden = " in source, "rows are not hidden by the pager"
    assert "remove()" not in source and "removeChild" not in source, (
        "the pager removes rows from the page, which takes their form fields "
        "out of the save")


def test_seven_to_a_page():
    for path in (TABLE, EDITOR):
        markup = path.read_text(encoding="utf-8")
        assert "data-per-page=\"7\"" in markup, (
            f"{path.name} does not say how many rows a page holds")


def test_the_page_switcher_is_not_a_link():
    """A pager built from <a href> puts a history entry in the back button for
    every page, and on this page the back button means "leave the settings"."""
    for path in (TABLE, EDITOR):
        markup = _without_comments(path.read_text(encoding="utf-8"))
        position = markup.index("pager")
        block = markup[max(0, position - 400):position + 400]
        assert "<a href" not in block, f"{path.name} builds its pager from links"


def test_the_rules_hold_in_node():
    """The real check: the arithmetic, run as the browser runs it."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/paging.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "paging.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 7, result.stdout
