# -*- coding: utf-8 -*-
"""The configuration page is markup, not a script with some markup around it.

MEASURED 2026-09-23, before the change:

    config.html            1996 lines   89,508 bytes
      one inline <style>    444 lines   12,169 bytes
      one inline <script>  1222 lines   59,838 bytes
      everything else                   17,501 bytes

Eighty per cent of the page was two blocks belonging to the mech panel, and
`_base.html:14` sets `Cache-Control: no-cache, no-store, must-revalidate`, so
all 72 KB went over the wire again on every single load of the panel. A static
file is not covered by that meta tag: the browser caches it like any other
asset and asks for it once.

Neither block contains a single Jinja expression - checked before moving, and
checked again here, because a block that needs templating cannot live in a
static file and would fail silently at the first `{{` somebody adds.

THE LOAD ORDER IS PART OF THE MOVE. The script is not deferred and not async:
it was inline at that point in the document and ran while the page was being
parsed, and `initializePowerSystem()` depends on that. A classic `<script src>`
in the same place blocks and runs the same way. It must still come after
progress_bars.js, which defines barWidth - the race that had the mech reading
OFFLINE this afternoon.

HOW THIS TEST CAN FAIL: it measures the page's inline blocks against a budget
and checks that the two files exist, are referenced, carry no Jinja, and load
in the right order. A new thousand-line block pasted into the page is red.

COUNTER-CHECK (2026-09-23): red before - the inline script was 1222 lines.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "templates" / "config.html"
STATIC = ROOT / "app" / "static"

# A budget, not a target. The page keeps small page-specific scripts - the one
# that remembers the open tab is twenty lines - but nothing that belongs in a
# file of its own.
INLINE_BUDGET = 120

JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)


def _blocks(text, tag):
    return re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.S)


def test_the_page_carries_no_block_that_belongs_in_a_file():
    """THE FINDING: one script of 1222 lines and one style of 444."""
    page = PAGE.read_text(encoding="utf-8")

    oversized = [len(block.splitlines())
                 for block in _blocks(page, "script") + _blocks(page, "style")
                 if len(block.splitlines()) > INLINE_BUDGET]

    assert oversized == [], (
        f"inline block(s) of {oversized} lines in config.html; over "
        f"{INLINE_BUDGET} it belongs in app/static, where the browser can "
        f"cache it - the page itself is sent no-cache")


def test_the_two_files_exist_and_are_referenced():
    page = PAGE.read_text(encoding="utf-8")

    for name in ("css/mech_panel.css", "js/mech_panel.js"):
        assert (STATIC / name).is_file(), f"{name} is missing"
        assert name in page, f"{name} is never loaded"


def test_neither_file_needs_templating():
    """A moved block that contains {{ ... }} would render as itself in a static
    file - no error, just a page that quietly stops working."""
    for name in ("css/mech_panel.css", "js/mech_panel.js"):
        content = (STATIC / name).read_text(encoding="utf-8")
        found = JINJA.findall(content)
        assert found == [], f"{name} still needs Jinja: {found[:3]}"


def test_the_mech_script_still_comes_after_the_helper_it_needs():
    """barWidth lives in progress_bars.js. The mech script calling it before it
    exists is exactly the race that had the mech reading OFFLINE with empty
    bars this afternoon."""
    page = PAGE.read_text(encoding="utf-8")

    assert page.index("js/progress_bars.js") < page.index("js/mech_panel.js")


def test_the_mech_script_is_not_deferred():
    """It ran while the page was being parsed and initializePowerSystem()
    depends on that. defer or async would move it after the document and change
    when the mech starts."""
    page = PAGE.read_text(encoding="utf-8")
    position = page.index("js/mech_panel.js")
    tag = page[page.rindex("<script", 0, position):page.index(">", position)]

    assert "defer" not in tag and "async" not in tag, tag


def test_the_page_still_renders_with_the_mech_on_it():
    """Counter-check on the move: the panel must still be there."""
    from flask import Flask, render_template
    from jinja2 import ChainableUndefined

    app = Flask(__name__, template_folder=str(ROOT / "app" / "templates"))
    app.jinja_env.undefined = ChainableUndefined
    app.jinja_env.globals["_t"] = lambda key, **kwargs: key
    app.jinja_env.globals["csrf_token"] = lambda: "test-token"
    app.jinja_env.globals["url_for"] = lambda endpoint, **values: "/static/x"

    with app.test_request_context("/"):
        html = render_template(
            "config.html", config={}, all_containers=[], configured_servers={},
            container_info_data={}, active_container_names=[],
            DEFAULT_CONFIG={"default_channel_permissions": {}})

    for element in ('id="donationSection"', 'id="powerLevel"',
                    'id="evolutionProgress"', 'id="speedStatusOverlay"'):
        assert element in html, f"{element} did not survive the move"
