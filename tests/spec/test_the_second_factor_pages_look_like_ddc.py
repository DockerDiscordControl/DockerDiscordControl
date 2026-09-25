# -*- coding: utf-8 -*-
"""The second-factor pages wear the panel's own clothes.

THE OPERATOR, 2026-09-25, with two screenshots: "can we do the 2FA setup in
the DDC look as well?" The pages came out white, in the browser's own font,
with none of the panel around them.

THE CAUSE, and it is one line. Every other page of the panel is built on the
shared shell - ``{% extends '_base.html' %}`` - which brings theme.css, the
navigation and the footer. ``two_factor.html`` was written as a standalone
document with its own ``<!doctype html>``, loading Bootstrap and nothing
else, on ``<body class="bg-light">``. The login page, which is the closest
thing to it, uses the shell and looks right.

NOTHING STOOD IN THE WAY, which is worth writing down because the file said
otherwise: its header notes "No script: plain forms work under the CSP", and
the shell does load scripts. But the policy is set once for the whole
application (app/web/security.py, one after_request), the login page runs
under exactly the same one, and the 2FA forms are still plain forms - the
note was about what the page needs, not about what it may have.

WHAT ALSO HAD TO GO: ``bg-white`` on the recovery-code block. A light-theme
leftover is invisible while the whole page is light and becomes a white slab
the moment it is not.

WHY THE PAGES ARE RENDERED HERE rather than read as text: a template can
inherit the shell and still lose the theme, and only what the browser is
actually sent can say otherwise. All six views are asked, because the one
the operator photographed is a single branch of a file that has six.

HOW THIS TEST CAN FAIL: a second-factor page that does not come through the
shared shell, or one that carries a light-theme class.

COUNTER-CHECK (2026-09-25): red before - a standalone document, no theme.css
in any of the six.
"""

import base64
import re
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT / "app" / "templates" / "two_factor.html"

PASSWORD = "correct horse"
SECURE = "https://localhost"

# Classes that paint a light surface. They were invisible while the page was
# light; on the panel's own background they are a white slab.
A_LIGHT_SURFACE = re.compile(r'class="[^"]*\b(bg-light|bg-white)\b')


def _markup_only():
    """The template with its Jinja comments taken out.

    THE SEVENTH TIME TODAY one of my own explanations tripped one of my own
    scans. The new header has to SAY what used to be there - a document of
    its own, on ``bg-light`` - and a scan reading the file as one lump finds
    those words and calls the page unfixed. A correction must stay writable,
    so the comments come out before the markup is asked anything.
    """
    import re as _re
    return _re.sub(r"\{#.*?#\}", "", TEMPLATE.read_text(encoding="utf-8"), flags=_re.S)


def _basic(user="admin", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    """The same harness the other second-factor cases use."""
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import (auth_limiter, clear_credential_cache, setup_limiter,
                          two_factor_limiter)
    from app.web import create_app
    from services.web.two_factor_service import TwoFactorStore

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}), \
        TwoFactorStore(tmp_path / "two_factor.json")

    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _pages(panel):
    """Every second-factor page the operator can reach, as HTML.

    LOGGED IN THROUGH THE FORM, not through Basic auth, and that distinction
    is the whole reason one of the cases below can fail at all. The shell's
    notice is decided by a context processor that asks ``session_user()``;
    with Basic auth there is no session, the banner never renders, and a case
    looking for it would be green while the operator watches it sit on top of
    his page. A harness that cannot reproduce the failure is not a test.
    """
    app, store = panel
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": PASSWORD},
                base_url=SECURE, follow_redirects=True)
    seen = {}

    seen["status (off)"] = client.get("/security/2fa", headers=_basic(),
                                      base_url=SECURE).get_data(as_text=True)
    seen["setup"] = client.post("/security/2fa/setup", headers=_basic(),
                                base_url=SECURE).get_data(as_text=True)
    seen["needs_tls"] = client.post("/security/2fa/setup", headers=_basic(),
                                    base_url="http://localhost").get_data(as_text=True)

    import time

    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)
    # follow_redirects: with 2FA on and this session not yet verified, the
    # status page sends the browser to the verify page first. Reading the
    # redirect body instead would check an empty shell.
    seen["status (on)"] = client.get("/security/2fa", headers=_basic(), base_url=SECURE,
                                     follow_redirects=True).get_data(as_text=True)
    seen["verify"] = client.get("/security/2fa/verify", headers=_basic(), base_url=SECURE,
                                follow_redirects=True).get_data(as_text=True)
    return seen


def test_every_second_factor_page_comes_through_the_shared_shell(panel):
    """THE FINDING: white pages in the browser's own font."""
    bare = [where for where, html in _pages(panel).items()
            if "css/theme.css" not in html]

    assert bare == [], f"these are served without the panel's stylesheet: {bare}"


def test_the_scan_has_pages_to_look_at(panel):
    """The counter-check eleven sabotages have walked past: a helper that
    returns nothing passes the case above while proving nothing."""
    pages = _pages(panel)

    assert len(pages) >= 5, sorted(pages)
    for where, html in pages.items():
        assert "<form" in html or "alert" in html, (where, html[:200])


def test_the_pages_do_not_ask_for_what_they_are_already_doing(panel):
    """THE SECOND HALF OF THE SAME MISTAKE. Putting these pages on the shared
    shell brought the shell's notice with them, so the page where 2FA is set
    up opened with a yellow banner urging the reader to set up 2FA - with a
    "Set up now" link to the page they were on, and a "Later" that dismisses
    the offer they had just accepted.

    THE CONTEXT PROCESSOR HAD LEARNED THIS ONCE ALREADY, earlier the same
    day: it runs for every template, and the banner used to appear on the
    LOGIN page, where both of its buttons led nowhere. The fix then was "only
    to somebody who is logged in". The fix now is the other half: not on the
    pages that do the thing.
    """
    nagging = [where for where, html in _pages(panel).items()
               if "data-two-factor" in html]

    assert nagging == [], (
        "these pages urge the reader to set up the second factor while they "
        f"are setting it up: {nagging}")


def test_the_card_says_what_colour_its_text_is(panel):
    """THE FIRST HALF, and it is why the operator asked whether I was having
    him on: the page was dark and unreadable, heading and text alike.

    theme.css gives .card a background and no colour, so the text falls back
    to Bootstrap's - which is meant for a light page. The panel's own dialogs
    say `bg-dark text-light` for exactly this reason
    (_spam_protection_modal.html). A rendered page is asked here, because the
    template can say `card` and still be served without it.
    """
    for where, html in _pages(panel).items():
        card = html[html.index('class="card'):][:120] if 'class="card' in html else ""

        assert "text-light" in card, (
            f"{where}: the card sets no text colour, so it is dark on dark: {card!r}")


def test_they_carry_the_same_mark_as_the_login_page(panel):
    """THE OPERATOR, once it was readable: "looks very technical - can it be
    a good deal prettier?" It could: it was a bare Bootstrap card with a
    heading, a sentence and a button.

    THESE ARE THE PANEL'S DOORWAY PAGES. The verify page is the second half
    of logging in, and the login page beside it carries the whole mark - the
    whale and the word. Wearing the same one is what makes them feel like the
    same product rather than a form that happens to be dark.

    THE MARK IS NOT COPIED, it is the same classes: logo-header, the compact
    modifier sized for a card, and the neon title. The flicker in _base.html
    finds it by id without knowing about either page.
    """
    login = (PROJECT / "app" / "templates" / "login.html").read_text(encoding="utf-8")
    # Once: _pages walks the whole setup, and calling it again would try to
    # switch the second factor on a second time.
    pages = _pages(panel)
    for piece in ("logo-header logo-header--compact", "neon-text-large", 'id="neon-ddc"'):

        assert piece in login, f"the login page no longer carries {piece!r} - re-read this rule"

        for where, html in pages.items():
            assert piece in html, f"{where} does not carry {piece!r}"


def test_the_way_back_is_quieter_than_the_way_on(panel):
    """A page with two calls of equal weight makes the reader choose; the
    button is the thing to do, and "back to the panel" is the way out. It was
    a full-size blue link under the button, louder than the step it undoes.

    THE FIRST VERSION OF THIS CASE COULD NOT FAIL. It cut a window around a
    translation KEY that never appears in rendered HTML, fell back to the
    whole page, and found ``text-secondary`` in the footer. So it asks the
    tag itself now - the anchor that leads back to the panel - which is the
    twelfth time today a check of mine had to be turned from a word into the
    thing it is about.
    """
    html = _pages(panel)["status (off)"]
    inside_the_card = html[html.index('class="card'):]
    back = re.search(r'<a[^>]*href="/"[^>]*>', inside_the_card)

    assert back is not None, "no way back to the panel at all"

    classes = re.search(r'class="([^"]*)"', back.group(0))

    assert classes is not None, back.group(0)
    assert "text-secondary" in classes.group(1), (
        f"the way back is as loud as the button: {back.group(0)!r}")
    assert "btn-primary" not in classes.group(1), back.group(0)


def test_the_setup_page_still_shows_the_code_to_scan(panel):
    """The opposite mistake: a new shell that drops what the page is FOR.
    The operator's second screenshot is this one - the QR code, the key to
    type by hand, and the field for the six digits."""
    html = _pages(panel)["setup"]

    assert "<svg" in html, "the QR code is gone"
    assert 'name="code"' in html, "nowhere to type the six digits"
    assert "<code" in html, "the key to enter by hand is gone"


def test_no_light_surface_is_left_in_the_template():
    """``bg-light`` and ``bg-white`` were invisible while the page was light.
    On the panel's background they are a white slab."""
    found = A_LIGHT_SURFACE.findall(_markup_only())

    assert found == [], f"light-theme classes left in two_factor.html: {found}"


def test_a_correction_may_describe_what_it_replaced():
    """The other side of the same lesson: the header names ``bg-light`` and
    the old ``<!doctype html>`` on purpose, so the next reader knows why the
    page changed. Stripping the comments is what lets both rules hold."""
    whole = TEMPLATE.read_text(encoding="utf-8")

    assert "bg-light" in whole, "the header no longer says what was wrong"
    assert A_LIGHT_SURFACE.findall(_markup_only()) == []


def test_the_page_is_not_a_document_of_its_own():
    """The cause, pinned: a second ``<!doctype html>`` is how it came to be
    outside the panel in the first place."""
    markup = _markup_only()

    assert "{% extends '_base.html' %}" in markup, markup[:200]
    assert "<!doctype html>" not in markup.lower(), (
        "the page builds its own document again instead of using the shell")
