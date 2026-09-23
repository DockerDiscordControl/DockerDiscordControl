# -*- coding: utf-8 -*-
"""The tab bar reads as one menu, not four links floating in the dark.

THE OPERATOR'S OBSERVATION (2026-09-23): after the tabs were spread across the
full width, only the active one had a box. The other three sat in black space
with nothing around them and nothing between them, so the strip read as four
separate links that happen to be on the same line - not as one control with
four positions.

He is right, and it is the predictable cost of nav-justified on a dark
background: spreading the items apart removes the one thing that made them
look related, which was being next to each other.

WHAT IT GETS: the surface the floating navigation already uses - a rounded,
slightly lighter panel with a hairline border - with the four buttons inside
it. That is the same visual language on both navigation controls, and a
segmented strip is unmistakably one thing.

The inactive buttons get a resting colour and a hover, so they look like parts
of a control rather than text that happens to be blue; the active one keeps
the filled pill.

WHAT THIS TEST DOES NOT CLAIM: it reads a stylesheet and cannot say how the
page looks. It pins that the bar has a surface of its own and that the
inactive buttons react - the two things whose absence made it read as four
links.

HOW THIS TEST CAN FAIL: taking the surface off the bar, or leaving the
inactive buttons without a resting or hover state.

COUNTER-CHECK (2026-09-23): red before - #settings-tabs had a background only
as a sticky backdrop, matching the page, and no rule at all for the buttons
inside it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "app" / "static" / "css" / "theme.css"


def _rule(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


def test_the_bar_has_a_surface_of_its_own():
    """THE FINDING: it had the page's own colour, so there was nothing to see
    between the buttons."""
    body = _rule(THEME.read_text(encoding="utf-8"), "#settings-tabs")

    assert body is not None, "#settings-tabs has no rule"
    assert "border-radius" in body, "the bar has no shape"
    assert "border:" in body, "the bar has no edge, so it has no extent"

    background = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", body)
    assert background, "the bar has no surface colour"
    assert background.group(1).lower() != "#030603", (
        "the bar is painted the page's own colour, which is what made it "
        "invisible between the buttons")


def test_the_inactive_buttons_look_like_part_of_a_control():
    """They were plain blue text with nothing around them."""
    css = THEME.read_text(encoding="utf-8")

    resting = _rule(css, "#settings-tabs .nav-link")
    assert resting is not None, "the buttons have no resting state"
    assert "border-radius" in resting, "an inactive button has no shape"

    hover = _rule(css, "#settings-tabs .nav-link:hover")
    assert hover is not None, "nothing happens when the pointer is over them"
    assert "background" in hover, "hovering changes no surface, only text"


def test_the_active_button_is_still_the_obvious_one():
    """Counter-check: giving the inactive ones a surface must not make the
    active one blend in."""
    css = THEME.read_text(encoding="utf-8")
    active = _rule(css, "#settings-tabs .nav-link.active")

    assert active is not None, "the active tab has no rule of its own"
    assert "background-color" in active


def test_it_shares_the_floating_navigations_language():
    """Two navigation controls on one page that look unrelated are two things
    to learn. The floating bar's surface is the one already there."""
    nav_css = (ROOT / "app" / "static" / "css" / "floating_nav.css").read_text(encoding="utf-8")
    bar = _rule(nav_css, ".floating-nav")
    tabs = _rule(THEME.read_text(encoding="utf-8"), "#settings-tabs")

    assert "border: 1px solid rgba(255, 255, 255, 0.08)" in bar, (
        "the floating navigation changed - re-read this test")
    assert "rgba(255, 255, 255, 0.08)" in tabs, (
        "the tab bar's edge does not match the floating navigation's")
