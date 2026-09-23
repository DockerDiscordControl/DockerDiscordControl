# -*- coding: utf-8 -*-
"""The container table can be searched, and its column headers stay put.

THE GAP, measured on 2026-09-23 while looking at the page as a whole: the
container table renders one row per container - 26 on the operator's server -
and about 2,200 lines of HTML. Each row carries ten visible controls: Active, a
display name, four permission boxes, the player toggle and three buttons. By
row fifteen the column headers have scrolled off the top, so the operator is
ticking boxes in unlabelled columns and counting across to work out whether
this one is Stop or Restart. Finding one container means reading 26 names.

WHAT CHANGES: a search box above the table that hides the rows that do not
match, and a header that stays visible while the rows scroll under it.

THE STICKY TRAP, and why the table gets a height: `position: sticky` is
relative to the nearest SCROLLING ancestor. The table sits in
`<div class="table-responsive">`, which is `overflow-x: auto` - and CSS
computes `overflow-y: visible` next to an `auto` to `auto`, so that div is a
scroll container whether or not anyone meant it to be. A sticky `thead` inside
it therefore sticks to the top of that div, not to the viewport, and with the
div as tall as its content that top is never reached. So the div gets a
max-height and scrolls: the header pins to the box, and the box stays on
screen. Removing `.table-responsive` instead would take the horizontal scroll
with it, which is what makes ten columns usable on a laptop.

THE SEARCH REUSES matchingContainers: the groups section already has a search
box over the same container names (`#group-search`,
app/static/js/container_groups.js), with four node cases on the matching rule.
A second implementation of "does this name match" is a second thing to get
wrong, and the two boxes would start disagreeing about case or substrings.

HOW THIS TEST CAN FAIL: it reads the section and the stylesheet and asks for a
search input bound to the rows, a scroll box with a height, a sticky header,
and a filter that calls the shared helper rather than its own copy. It also
pins that a search matching nothing SAYS so - an empty table with no message
looks like a table that lost its containers.

COUNTER-CHECK (2026-09-23): red before - there was no search box, no height on
the scroll box and no sticky rule anywhere for this table.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECTION = ROOT / "app" / "templates" / "_server_selection.html"
FILTER = ROOT / "app" / "static" / "js" / "container_filter.js"
KEYS = ("web.server.search_placeholder", "web.server.search_no_match")


def _without_comments(text):
    """Jinja and JS comments removed - a sentence about a rule is not the rule.

    My own comments have defeated my own assertions four times today.
    """
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_table_has_a_search_box():
    """THE GAP: finding one container among 26 meant reading 26 names."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="container-search"' in section, "the container table has no search"
    assert "web.server.search_placeholder" in section


def test_a_search_that_matches_nothing_says_so():
    """An empty table with no message reads as a table that lost its rows."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert 'id="container-search-no-match"' in section
    assert "web.server.search_no_match" in section


def test_the_scroll_box_has_a_height_so_the_header_can_pin():
    """THE STICKY TRAP: .table-responsive is a scroll container whether or not
    anyone meant it to be, so a sticky header pins to a box that is as tall as
    its content - i.e. never."""
    section = _without_comments(SECTION.read_text(encoding="utf-8"))
    position = section.index("table-responsive")
    box = section[position:section.index(">", position)]

    assert "max-height" in box, (
        "the scroll box is as tall as its content, so a sticky header has "
        "nothing to stick to")


def test_the_column_headers_stay_put():
    section = _without_comments(SECTION.read_text(encoding="utf-8"))

    assert "position: sticky" in section, "the column headers scroll away"
    assert "thead" in section


def test_the_filter_uses_the_matching_rule_that_is_already_tested():
    """A second implementation of "does this name match" is a second thing to
    get wrong, and the two search boxes on this page would start disagreeing."""
    source = FILTER.read_text(encoding="utf-8")

    assert "matchingContainers" in source, "the filter brought its own matcher"
    assert "toLowerCase" not in source, (
        "the filter matches on its own after all - that is the copy this "
        "avoids")


def test_the_filter_acts_on_the_rows_the_table_marks():
    source = _without_comments(FILTER.read_text(encoding="utf-8"))

    assert "data-container-name" in source or "containerName" in source


def test_the_script_is_loaded_after_the_one_it_borrows_from():
    """Order matters: matchingContainers is defined by container_groups.js."""
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    assert "container_filter.js" in scripts, "the filter is never loaded"
    assert scripts.index("container_groups.js") < scripts.index("container_filter.js")


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_texts_exist(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    missing = [key for key in KEYS if not catalogue.get(key)]

    assert missing == [], f"{language}.json has no text for {missing}"


def test_every_locale_has_the_texts():
    locales = [p for p in (ROOT / "locales").glob("*.json") if p.name != "meta.json"]

    assert len(locales) >= 40
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        assert all(key in catalogue for key in KEYS), path.name


def test_the_german_texts_are_really_german():
    german = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))

    same = [key for key in KEYS if german[key] == english[key]]

    assert same == [], f"these are still the English texts: {same}"
