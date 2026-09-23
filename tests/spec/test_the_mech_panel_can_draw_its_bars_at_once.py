# -*- coding: utf-8 -*-
"""The helper the mech bars need is loaded before the code that calls it.

THE FINDING, reported by the operator on 2026-09-23 with a screenshot: the
panel's mech read OFFLINE, both bars were empty, and the next evolution said
"REPARIERTER MECH - $20 benötigt". Measured against the running container the
same minute, every one of those was wrong:

    /api/donation/status   level 6, "The Abyss Engine", 105.00 donated,
                           next "The Rift Strider" at 35.40,
                           speed 10 "Glacially slow"
    the page              OFFLINE, 0 % bars, level 1's name and threshold

The service was right. OFFLINE, "$20 benötigt" and width: 0% are the LITERALS
the template ships with, which updateBarsFromServerData() is supposed to
overwrite. The power figure beside them was correct (3.66), and that is the
tell: updatePowerDisplay() runs one line earlier and succeeded, so the failure
is inside updateBarsFromServerData.

Its first statement that can fail is barWidth(...). barWidth lives in
app/static/js/progress_bars.js, which _scripts.html loads at the END of
config.html - about 800 lines of markup after the inline power system that
calls it. loadInitialPowerData() awaits a fetch to localhost, so whether
barWidth exists by the time the answer comes back is a race between that fetch
and the browser parsing the rest of the page. When the fetch wins, the call
raises ReferenceError, loadInitialPowerData's own try/catch swallows it into a
console line, and the bars keep the literals they were born with until the
60-second sync happens to run.

Nothing about this is visible from the server: the API answers correctly, the
page returns 200, and the log says nothing.

HOW THIS TEST CAN FAIL: it asks whether the script that DEFINES barWidth is
loaded before the first line that CALLS it. Moving the tag back to the bottom
of the page, or to _scripts.html, is red.

COUNTER-CHECK (2026-09-23): red before - config.html called barWidth at line
1105 and included _scripts.html, which loads progress_bars.js, at line 1907.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "templates" / "config.html"
SCRIPTS = ROOT / "app" / "templates" / "_scripts.html"


def _without_comments(text):
    """Jinja comments and JS line comments removed.

    A first version of this test failed on the comment that explains the fix,
    because that comment names barWidth() above the script tag. A comment is
    not a call.
    """
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_helper_is_loaded_before_it_is_called():
    """THE POINT: no race between a fetch and the rest of the page."""
    page = _without_comments(PAGE.read_text(encoding="utf-8"))
    loaded = page.index("js/progress_bars.js")
    called = page.index("barWidth(")

    assert loaded < called, (
        "progress_bars.js is loaded after the code that calls barWidth() - "
        "whether the mech bars are drawn is then a race the page can lose, "
        "silently")


def test_it_is_loaded_in_exactly_one_place():
    """Counter-check: two tags would make the order look right while the late
    one still decides what the reader believes."""
    page = PAGE.read_text(encoding="utf-8")

    assert page.count("js/progress_bars.js") == 1
    assert "progress_bars.js" not in SCRIPTS.read_text(encoding="utf-8"), (
        "_scripts.html is included at the bottom of the page; loading it there "
        "is what the finding was about")


def test_the_helper_needs_nothing_from_the_page():
    """Why loading it early is safe: it is one pure function, no DOM, no
    DOMContentLoaded. If that changes, loading it in the head is not safe any
    more and this says so.
    """
    helper = (ROOT / "app" / "static" / "js" / "progress_bars.js").read_text(encoding="utf-8")

    for forbidden in ("document.", "window.", "addEventListener", "fetch("):
        assert forbidden not in helper, (
            f"progress_bars.js touches {forbidden} - it is loaded before the "
            "page exists")


def test_the_literals_it_must_overwrite_are_still_there():
    """The other half of the finding, so it cannot be 'fixed' by deleting them:
    the placeholders ARE the level-1 texts the operator saw, and they are what
    the page shows until the real values arrive."""
    page = PAGE.read_text(encoding="utf-8")

    assert 'id="powerLevel"' in page
    assert 'id="evolutionProgress"' in page
    assert 'id="nextEvolutionName"' in page
    assert 'id="speedStatusOverlay"' in page
