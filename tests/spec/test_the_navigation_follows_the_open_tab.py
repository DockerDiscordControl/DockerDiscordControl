# -*- coding: utf-8 -*-
"""The tab bar fills its width, and the dots show only what is on screen.

TWO THINGS THE OPERATOR ASKED FOR after seeing the tabs (2026-09-23).

ONE. The four tabs sat bunched against the left edge while the cards below
them run the full width of the page. They fill it now.

TWO, and it is the one that was actually wrong: the floating navigation on the
right still listed all thirteen sections. Since this morning ten of them are
inside a tab pane, and three panes are hidden at any moment - so ten of the
thirteen dots pointed at something not on screen. Clicking one still worked,
because a dot opens its pane before scrolling, but the navigation was
describing a page that no longer exists: one long scroll of everything.

The dots now show the sections of the OPEN pane, plus the ones that belong to
no pane at all - the mech panel above the tabs and the log below them. Switch
tabs and the list changes with it.

HOW IT KNOWS: each dot asks the DOM which pane its target sits in. No second
list of which section belongs to which tab - a second list is a second thing
to keep in step, and the one in updateActiveSection already has to be
maintained by hand.

HOW THIS TEST CAN FAIL: the tab bar losing its full width, or the dots being
shown without regard to which pane is open.

COUNTER-CHECK (2026-09-23): red before - nav-pills with no fill class, and
nothing in the navigation knew about panes except the click handler.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "templates" / "config.html"
# The navigation's script moved to app/static/js/floating_nav.js on
# 2026-09-23, when it grew past the inline budget. The markup stayed in
# base.html.
NAV = ROOT / "app" / "static" / "js" / "floating_nav.js"


def _without_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_tab_bar_fills_the_width_of_the_cards_below_it():
    """THE FIRST ASK: four pills bunched left under cards that run the full
    width."""
    page = _without_comments(PAGE.read_text(encoding="utf-8"))
    position = page.index('id="settings-tabs"')
    tag = page[page.rindex("<ul", 0, position):page.index(">", position)]

    assert "nav-justified" in tag or "nav-fill" in tag, (
        f"the tab bar does not fill its width: {tag}")


def test_the_dots_follow_the_open_tab():
    """THE SECOND ASK, and the real defect: ten of the thirteen dots pointed
    into panes that are not on screen."""
    nav = _without_comments(NAV.read_text(encoding="utf-8"))

    assert "updateVisibleDots" in nav, (
        "nothing hides the dots whose section is in a closed tab")
    assert "shown.bs.tab" in nav, (
        "the dot list is never recomputed, so it is right only until the first "
        "tab change")


def test_it_asks_the_page_rather_than_keeping_a_second_list():
    """A map of section-to-tab would be a second thing to keep in step with the
    markup, and updateActiveSection's list already has to be maintained by
    hand. The DOM knows the answer."""
    nav = _without_comments(NAV.read_text(encoding="utf-8"))
    block = nav[nav.index("updateVisibleDots"):]

    assert "closest('.tab-pane')" in block, (
        "the dot list does not ask the DOM which pane a section is in")


def test_a_section_outside_every_pane_always_shows():
    """The mech panel sits above the tabs and the log below them. They belong
    to no pane, and a dot for them must not vanish because some tab is open."""
    nav = _without_comments(NAV.read_text(encoding="utf-8"))
    block = nav[nav.index("updateVisibleDots"):]

    assert "!pane" in block or "pane === null" in block or "if (!pane)" in block, (
        "a section that is in no pane is treated like one in a closed pane")
