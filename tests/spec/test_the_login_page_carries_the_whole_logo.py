# -*- coding: utf-8 -*-
"""The login page shows the whole mark, whale and DDC, and it flickers.

THE OPERATOR (2026-09-25), with a screenshot of the password page: the logo is
only half there. The whale is on it; the red "DDC" underneath is not. "On the
normal landing page there is still the DDC part - they belong together. Please
take the flicker over too."

He is right that it is one mark: config.html has both, inside a .logo-header
with the whale and a .ddc-title holding the neon text, and _base.html gives
that text a flicker - it goes dark for a fraction of a second every five to ten
seconds, like a tube that is on its way out.

NOTHING HAD TO BE BUILT FOR THE FLICKER. The script is in _base.html, outside
any block, so it runs on every page that extends it - and the login page does.
It looks the element up by id. There simply was no element with that id to
find, so it flickered nothing. Giving the login page the same id is the whole
of it.

THE SIZE IS NOT THE SAME, and that is deliberate. .neon-text-large is 6rem,
chosen against a 200-pixel whale on a full-width page. The login card is 420
pixels wide with a 72-pixel whale, and 6rem there would bury it. A modifier
carries the smaller sizes; the colour, the glow and the flicker are the shared
ones, because those are what make it the same mark.

HOW THIS TEST CAN FAIL: a login page that loses half the mark again, an id the
flicker cannot find, or the compact mark quietly growing to the full size.

COUNTER-CHECK (2026-09-25): red before - the login page had no neon element at
all, and the flicker script found nothing to flicker.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
THEME = PROJECT / "app" / "static" / "css" / "theme.css"
NEON_ID = "neon-ddc"

# The pages that show the mark. A page that greets the operator before he is
# in the panel is exactly where the mark is worth having.
WITH_THE_MARK = ("config.html", "login.html", "discord_bot_setup.html")


@pytest.mark.parametrize("page", WITH_THE_MARK)
def test_the_page_shows_the_whole_mark(page):
    """THE FINDING: the whale without the word is half a logo."""
    markup = (TEMPLATES / page).read_text(encoding="utf-8")

    assert "ddc_web.png" in markup, f"{page} has no whale"
    assert f'id="{NEON_ID}"' in markup, f"{page} has the whale and not the word"
    assert "neon-text-large" in markup, f"{page} does not use the neon styling"


@pytest.mark.parametrize("page", WITH_THE_MARK)
def test_the_id_is_there_exactly_once(page):
    """An id twice on one page is an id the script finds once, and the other
    one never flickers."""
    markup = (TEMPLATES / page).read_text(encoding="utf-8")

    assert markup.count(f'id="{NEON_ID}"') == 1, page


def test_the_flicker_looks_for_that_id():
    """The script and the markup agree, or the flicker silently does nothing -
    which is exactly what it did on the login page."""
    base = (TEMPLATES / "_base.html").read_text(encoding="utf-8")

    assert f"getElementById('{NEON_ID}')" in base, (
        "the flicker no longer looks for the element the pages carry")


def test_the_flicker_reaches_every_page_that_extends_the_base():
    """It sits outside every block on purpose: a page only has to extend the
    base to get it. Inside a block, each page would have to remember."""
    base = (TEMPLATES / "_base.html").read_text(encoding="utf-8")
    at = base.index("setupNeonFlicker")
    before = base[:at]

    assert before.count("{% block") == before.count("{% endblock %}"), (
        "the flicker script sits inside a block - a page that does not "
        "override it loses the flicker")


@pytest.mark.parametrize("page", ["login.html"])
def test_the_compact_mark_is_not_the_full_sized_one(page):
    """6rem was chosen against a 200-pixel whale. The login card is 420 pixels
    wide, and the same size there buries the whale it belongs to."""
    markup = (TEMPLATES / page).read_text(encoding="utf-8")

    assert "logo-header--compact" in markup, (
        f"{page} uses the full-sized mark inside a card")
    css = THEME.read_text(encoding="utf-8")

    assert ".logo-header--compact" in css, "the compact variant has no styling"


def test_the_compact_variant_only_changes_the_size():
    """The colour, the glow and the flicker are what make it the same mark. A
    variant that restyled those would be a second logo, not a smaller one."""
    css = THEME.read_text(encoding="utf-8")
    block = css[css.index(".logo-header--compact"):]
    block = block[:block.index("}", block.index("{"))]

    for forbidden in ("color:", "text-shadow:", "filter:"):
        assert forbidden not in block, (
            f"the compact variant changes {forbidden.strip(':')} - it is meant "
            "to change the size and nothing else")


def test_the_whale_and_the_word_are_in_one_block(page="login.html"):
    """Side by side in the markup, or a card that reflows puts the word
    somewhere the whale is not."""
    markup = (TEMPLATES / page).read_text(encoding="utf-8")
    header = markup[markup.index("logo-header"):]
    header = header[:header.index("</div>", header.index(f'id="{NEON_ID}"'))]

    assert "ddc_web.png" in header, "the whale is outside the logo block"
    assert re.search(r'ddc-title', header), "the word is not in the title block"
