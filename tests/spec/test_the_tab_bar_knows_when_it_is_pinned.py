# -*- coding: utf-8 -*-
"""The tab bar looks different once it is pinned, because it is doing a
different job.

THE OPERATOR'S OBSERVATION (2026-09-24): the bar looks right where it starts,
and wrong once it sticks to the top. He is right, and the reason is that a
card and a toolbar are not the same object.

At rest it sits in the page: rounded on all four corners, a hairline all the
way round, no shadow. That reads as a card among cards. Pinned, the same shape
is wrong - the rounding at the top has nothing above it to be rounded away
from, the border closes a box whose content is sliding out from under it, and
without a shadow the rows scroll up to the bar's edge and stop dead, with
nothing saying one is above the other.

WHAT CHANGES WHEN IT STICKS: the top corners square off against the top of the
window, the box becomes a band - no top border, a bottom hairline instead -
and a shadow puts it above the page rather than in it.

HOW IT KNOWS. `position: sticky` gives CSS no way to ask "am I stuck": there
is a `:stuck` selector in the specification and no browser the operator runs
supports it. The technique that works is a sentinel - an empty element
immediately above the bar - watched by an IntersectionObserver: while the
sentinel is on screen the bar is at rest, and the moment it scrolls out the
bar is pinned. No scroll handler, so nothing runs on every frame.

WHAT THIS TEST DOES NOT CLAIM: it reads a stylesheet and a template and cannot
say how the page looks. It pins the two halves - the sentinel and the class it
drives, and a pinned style that actually differs from the resting one.

HOW THIS TEST CAN FAIL: dropping the sentinel, the observer, or the pinned
rule - or writing a pinned rule identical to the resting one, which would
leave the operator where he started.

COUNTER-CHECK (2026-09-24): red before - one rule for both states and no
sentinel.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "templates" / "config.html"
THEME = ROOT / "app" / "static" / "css" / "theme.css"


def _rule(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


def test_there_is_a_sentinel_above_the_bar():
    """CSS cannot ask a sticky element whether it is stuck."""
    page = PAGE.read_text(encoding="utf-8")

    assert 'id="settings-tabs-sentinel"' in page, (
        "nothing tells the page when the bar has pinned")
    assert page.index("settings-tabs-sentinel") < page.index('id="settings-tabs"'), (
        "the sentinel is below the bar, so it can never leave the screen first")


def test_something_watches_it():
    """An IntersectionObserver, not a scroll handler: a scroll handler runs on
    every frame of every scroll for a class that changes twice."""
    page = PAGE.read_text(encoding="utf-8")

    assert "IntersectionObserver" in page, "nothing watches the sentinel"
    assert "is-stuck" in page, "the observer sets no class"


def test_the_pinned_look_is_not_the_resting_look():
    """The whole point. A pinned rule that matches the resting one would leave
    the operator exactly where he started."""
    css = THEME.read_text(encoding="utf-8")
    resting = _rule(css, "#settings-tabs")
    pinned = _rule(css, "#settings-tabs.is-stuck")

    assert resting is not None, "#settings-tabs has no rule"
    assert pinned is not None, "there is no pinned rule"

    def declarations(body):
        return {piece.split(":")[0].strip(): piece.split(":", 1)[1].strip()
                for piece in body.split(";") if ":" in piece}

    same = declarations(resting) == declarations(pinned)
    assert not same, "the pinned rule says the same as the resting one"


def test_pinned_it_is_a_band_and_not_a_card():
    """Square at the top, open at the top, and above the page rather than in
    it - the three things that made the card shape wrong up there."""
    pinned = _rule(THEME.read_text(encoding="utf-8"), "#settings-tabs.is-stuck")

    assert "border-top" in pinned, "the box still closes over content sliding out of it"
    assert "border-radius" in pinned, "the top corners are still rounded against the window"
    assert "box-shadow" in pinned, (
        "nothing says the bar is above the rows, so they scroll up to its edge "
        "and stop dead")


def test_at_rest_it_is_still_a_card():
    """Counter-check: the resting look is the one the operator said was good."""
    resting = _rule(THEME.read_text(encoding="utf-8"), "#settings-tabs")

    assert "border-radius" in resting
    assert "border:" in resting
