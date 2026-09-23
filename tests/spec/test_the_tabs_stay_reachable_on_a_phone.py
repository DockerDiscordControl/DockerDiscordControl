# -*- coding: utf-8 -*-
"""On a phone the tab bar is the navigation, so it stays in reach.

MEASURED 2026-09-23. `base.html` hides the floating navigation below 768
pixels - thirteen dots down a 390-pixel screen would cover the page - so on a
phone the four tabs are the only way from one part of the settings to another.

And they scrolled away with everything else. The Containers pane holds a table
of 26 rows; by the time the operator is at the bottom of it, getting to System
means scrolling all the way back up past the whole table. On a desktop the
floating dots make that one click; on a phone there was nothing.

The bar sticks to the top of the screen.

REVISITED the same evening, and the earlier reasoning was wrong. The first
version pinned it only below 992 pixels, arguing that on a wide screen the
floating dots already do this job. The operator looked at it and asked for the
bar to travel down the page with him there too - and he is right about his own
panel: the dots are thirteen small circles at the edge of the window, the tabs
are four labelled buttons at the top of the thing they switch. They are not
the same control, and "one is nearby" is not a reason to make the other one
scroll away. The restriction is gone; the test that pinned it is below, saying
what it used to say and why that changed.

THE Z-INDEX IS PART OF IT, not decoration. The container table has a sticky
header of its own inside a 70vh scroll box. Both are pinned, to different
things - the table header to its box, the tab bar to the window - so where
they meet, the one that must win is the tab bar. Without that, switching tabs
on a phone means first finding a place where the table header is not in the
way.

WHAT THIS TEST DOES NOT CLAIM: it reads stylesheets. It cannot say what a
phone renders. It pins the decision - the bar is sticky below the breakpoint,
and it outranks the table header where they overlap.

HOW THIS TEST CAN FAIL: dropping the sticky rule, widening it to every screen
size, or letting the table header outrank it.

COUNTER-CHECK (2026-09-23): red before - there was no rule for the tab bar at
all, and the table header's z-index was the highest on the page.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The theme moved to app/static/css/theme.css on 2026-09-23.
BASE = ROOT / "app" / "static" / "css" / "theme.css"
SECTION = ROOT / "app" / "templates" / "_server_selection.html"


def _rule(css, selector):
    """The body of the first rule for `selector`, or None."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


def test_the_tab_bar_sticks_on_a_small_screen():
    """THE POINT: on a phone it is the only navigation there is."""
    base = BASE.read_text(encoding="utf-8")
    body = _rule(base, "#settings-tabs")

    assert body is not None, "#settings-tabs has no rule at all"
    assert "position: sticky" in body, "the tab bar scrolls away with the page"


def test_it_sticks_at_every_width():
    """THE REVISIT: this test used to assert the opposite.

    It read "it sticks only where the dots are gone" and required the rule to
    sit inside a max-width media query. The operator asked for the bar to
    travel with him on the desktop as well, and the argument for the
    restriction does not survive the question: the floating dots are thirteen
    circles at the edge of the window, the tabs are four labelled buttons at
    the top of what they switch. Nearby is not the same as equivalent.

    Kept rather than deleted, pointing the other way, so the next reader can
    see that the narrow-screen-only version was a decision and not an
    oversight.
    """
    base = BASE.read_text(encoding="utf-8")
    position = base.index("#settings-tabs")
    before = base[:position]
    # The rule must not be inside a media query: count the braces that are
    # still open where it starts.
    depth = before.count("{") - before.count("}")

    assert depth == 0, (
        "the tab bar's rule is nested inside a media query, so it stops "
        "sticking outside that range")


def test_the_tab_bar_outranks_the_tables_own_sticky_header():
    """Both are pinned, to different things. Where they meet the tab bar has to
    win, or switching tabs means hunting for a gap in the table header."""
    base = BASE.read_text(encoding="utf-8")
    bar = _rule(base, "#settings-tabs")

    bar_z = re.search(r"z-index:\s*(\d+)", bar or "")
    assert bar_z, "the tab bar has no z-index, so the overlap is left to chance"

    section = SECTION.read_text(encoding="utf-8")
    header_z = max(int(z) for z in re.findall(r"z-index:\s*(\d+)", section))

    assert int(bar_z.group(1)) > header_z, (
        f"the tab bar is z-index {bar_z.group(1)} and the table header "
        f"{header_z} - the header covers the tabs where they overlap")


def test_the_bar_is_opaque():
    """A see-through bar over scrolling rows is worse than none."""
    body = _rule(BASE.read_text(encoding="utf-8"), "#settings-tabs")

    assert "background" in body, "the rows will show through the pinned bar"
