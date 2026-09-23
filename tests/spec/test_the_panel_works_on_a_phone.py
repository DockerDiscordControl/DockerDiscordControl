# -*- coding: utf-8 -*-
"""The panel can be used on a phone, not merely displayed on one.

MEASURED 2026-09-23 on the templates, not guessed. Bootstrap 5 and the
viewport meta tag mean the page SHOWS on a phone; three things mean it cannot
be USED there.

ONE, and it is mine, from this evening. base.html:169 reads

    @media (max-width: 768px) { .floating-nav { display: none; } }

The floating navigation is hidden on every phone - a reasonable decision for
thirteen dots down the side of a 390-pixel screen. This evening I put the
LOGOUT control in that navigation and nowhere else. So since then there has
been no way to log out of the panel on a phone at all. The route works; the
only thing pointing at it disappears below 768 pixels.

TWO. The container table has ten columns and one row per container - 26 on the
operator's server. On a phone `.table-responsive` gives it a horizontal
scrollbar, and the container's NAME is the third column. Scrolling right far
enough to reach Stop or Restart takes the name off screen, so the operator
ticks a permission box without being able to see which container it belongs
to. That is this morning's "unlabelled columns" problem turned on its side,
and the fix is the same shape: the name stays put while the rest scrolls.

THREE. The permissions table has eighteen header cells - the same problem,
wider, with the channel name as the anchor.

WHAT THIS TEST DOES NOT CLAIM: it reads templates and stylesheets. It cannot
say what a phone renders. It pins the three decisions above so they cannot be
undone by accident, and nothing more.

HOW THIS TEST CAN FAIL: hiding the logout control below 768 pixels again, or
dropping the sticky first column from either wide table.

COUNTER-CHECK (2026-09-23): red before on all three - no mobile logout, no
sticky column in either table.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"
THEME = ROOT / "app" / "static" / "css" / "theme.css"
NAV_CSS = ROOT / "app" / "static" / "css" / "floating_nav.css"
NAV = TEMPLATES / "base.html"


def _without_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_floating_navigation_is_still_hidden_on_a_phone():
    """Not a defect - thirteen dots down a 390-pixel screen would cover the
    page. It is pinned because the logout fix below depends on it being true."""
    nav = NAV_CSS.read_text(encoding="utf-8")

    assert re.search(r"@media\s*\(max-width:\s*768px\)\s*\{\s*\.floating-nav\s*\{\s*display:\s*none",
                     nav), "the navigation is no longer hidden on phones - re-read this test"


def test_there_is_a_way_to_log_out_on_a_phone():
    """MY REGRESSION, from this evening: the only logout control lives in the
    navigation that phones do not get."""
    page = _without_comments((TEMPLATES / "config.html").read_text(encoding="utf-8"))
    nav = _without_comments(NAV.read_text(encoding="utf-8"))

    outside_the_floating_nav = "login.logout" in page
    assert outside_the_floating_nav, (
        "the only logout control is in the floating navigation, which is "
        "display:none below 768px - a phone cannot log out at all")
    # And it must still be a POST form, for the same reason as on the desktop:
    # a GET that changes state is followed by anything that walks links.
    position = page.index("login.logout")
    block = page[max(0, position - 400):position + 400]
    assert 'method="POST"' in block, "the mobile logout is a link"
    assert "csrf_token()" in block, "the mobile logout carries no token"


def test_the_container_name_stays_visible_while_the_table_scrolls():
    """TWO: ten columns on a 390-pixel screen. Reaching Stop or Restart takes
    the name off screen, and the operator ticks a box for a container they can
    no longer see."""
    section = _without_comments((TEMPLATES / "_server_selection.html").read_text(encoding="utf-8"))

    assert "sticky-name-column" in section, (
        "nothing keeps the container name in view while the table scrolls "
        "sideways")


def test_the_channel_name_stays_visible_in_the_permissions_table():
    """THREE: eighteen header cells, same problem, wider."""
    section = _without_comments((TEMPLATES / "_permissions_table.html").read_text(encoding="utf-8"))

    assert "sticky-name-column" in section, (
        "nothing keeps the channel name in view while the permissions table "
        "scrolls sideways")


def test_the_sticky_column_is_defined_once():
    """Counter-check: two tables, one rule. A copy in each template is two
    things to keep in step, and they would drift."""
    defined_in = [path.name
                  for path in list(TEMPLATES.rglob("*.html")) + list((ROOT / "app" / "static" / "css").glob("*.css"))
                  if ".sticky-name-column" in path.read_text(encoding="utf-8")]

    assert defined_in == ["theme.css"], (
        f"the sticky column rule is defined in {defined_in}; it belongs in the "
        f"one stylesheet both tables already share")
