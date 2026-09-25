# -*- coding: utf-8 -*-
"""The second factor is settled without leaving the panel.

THE OPERATOR, 2026-09-25: "can we show this as a modal? because when I click
'Back to the panel' I am logged out, and a modal also looks nicer."

HE IS RIGHT TWICE. The three buttons beside it - spam protection, advanced
settings, diagnostics - are all dialogs, so the one that left the panel was
the odd one out. And leaving the panel was what cost him the session: the way
back carried an HTTP Basic challenge on a redirect, which a browser answers
instead of following, leaving it logged in for one path only (fixed
separately, app/web/security.py).

THE PAGE STAYS, AND THE BUTTON STILL LEADS TO IT. Bootstrap's modal data-api
calls preventDefault() for an <a> (v5.3.6, verified in the bundled file), so
with the script loaded the link opens the dialog and without it the browser
follows the href. A button that does nothing when JavaScript is off would be
the very defect this week has been spent removing.

WHAT IS NOT IN THE DIALOG, on purpose: typing a code happens BEFORE the
operator is in the panel, so there is no panel to put it on; setting up
carries a QR and its own HTTPS rule; and the recovery codes are shown exactly
once, which a dialog that closes on a click outside it is the wrong place for.

HOW THIS TEST CAN FAIL: a panel with no dialog, a dialog that does not carry
the state, a button that is dead without JavaScript, a form nested inside the
settings form, or the code screen turned into a dialog too.

COUNTER-CHECK (2026-09-26): red before - there was no dialog at all.
"""

import re
import time

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "correct horse"
SECURE = "https://localhost"


@pytest.fixture
def panel(monkeypatch, tmp_path):
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


def _switch_on(store):
    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def _the_panel(app, store, enabled):
    """The settings page as the operator sees it, past both factors."""
    from services.web.two_factor_service import secret_bytes, totp

    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": PASSWORD},
                base_url=SECURE, follow_redirects=True)
    if enabled:
        client.post("/security/2fa/verify", base_url=SECURE,
                    data={"code": totp(secret_bytes(store.pending_or_active_secret()),
                                       time.time())})
    return client, client.get("/", base_url=SECURE,
                              follow_redirects=True).get_data(as_text=True)


def _the_dialog(html):
    """Just that dialog. _i18n.html ships the whole catalogue to the browser,
    so searching the page for a word finds it in the bundle whether it is
    displayed or not."""
    where = html.index('id="twoFactorModal"')
    return html[where:html.index("</div>\n</div>", where)]


def test_the_panel_carries_the_dialog(panel):
    """THE REQUEST."""
    app, store = panel
    _switch_on(store)
    _client, html = _the_panel(app, store, enabled=True)

    assert 'id="twoFactorModal"' in html, "the panel has no second-factor dialog"


def test_the_dialog_carries_the_state(panel):
    """A dialog that only said "second factor" would be the same empty door
    the button was before the state line was written beside it."""
    app, store = panel
    _switch_on(store)
    _client, html = _the_panel(app, store, enabled=True)
    dialog = _the_dialog(html)

    assert "10" in dialog, f"the dialog does not say how many codes are left: {dialog[:400]}"
    assert 'name="remember_devices_allowed"' in dialog, "no device switch in the dialog"
    assert "/security/2fa/disable" in dialog, "no way to switch the second factor off"


def test_the_button_still_works_without_javascript(panel):
    """Bootstrap prevents the default for an <a>, so the same element is a
    dialog with the script and a link without it. A <button> here would be a
    dead control in a browser with JavaScript off - which is the shape this
    week was spent removing."""
    app, store = panel
    _switch_on(store)
    _client, html = _the_panel(app, store, enabled=True)
    tag = next(t for t in re.findall(r"<a\b[^>]*>", html, re.S)
               if 'data-bs-target="#twoFactorModal"' in t)

    assert re.search(r'href="[^"]*security/2fa"', tag), (
        f"the dialog's button leads nowhere without a script: {tag}")


def test_the_dialogs_forms_are_not_inside_the_settings_form(panel):
    """A form inside a form is not valid HTML and browsers drop the inner
    one, which would make the switch and the disable field do nothing - alive
    to look at, dead to use."""
    app, store = panel
    _switch_on(store)
    _client, html = _the_panel(app, store, enabled=True)

    end_of_settings_form = html.index("</form>", html.index('id="config-form"'))
    where = html.index('id="twoFactorModal"')

    assert where > end_of_settings_form, (
        "the second-factor dialog is inside <form id=\"config-form\">, so its "
        "own forms are nested and the browser will drop them")


def test_the_dialog_comes_back_to_the_panel(panel):
    """The point of the dialog: what is changed in it does not end on
    another page."""
    app, store = panel
    _switch_on(store)
    client, html = _the_panel(app, store, enabled=True)
    dialog = _the_dialog(html)
    back = re.search(r'name="next" value="([^"]*)"', dialog).group(1)

    assert back.startswith("/"), back

    answer = client.post("/security/2fa/devices", base_url=SECURE,
                         data={"next": back})

    assert answer.status_code == 302
    assert answer.headers["Location"] == back, answer.headers["Location"]
    assert store.remembering_devices_allowed() is False, "the form did not act"


def test_without_a_next_the_page_is_still_where_it_goes(panel):
    """THE OPPOSITE MISTAKE. The page's own copy of these forms sends no
    next, and it must still land where it always did."""
    app, store = panel
    _switch_on(store)
    client, _html = _the_panel(app, store, enabled=True)

    answer = client.post("/security/2fa/devices", base_url=SECURE, data={})

    assert answer.status_code == 302
    assert answer.headers["Location"].endswith("/security/2fa"), answer.headers["Location"]


def test_the_code_screen_is_not_a_dialog(panel):
    """It is asked BEFORE the operator is in the panel, so there is no panel
    to put it on. A dialog there would have nothing behind it."""
    app, store = panel
    _switch_on(store)

    page = app.test_client()
    page.post("/login", data={"username": "admin", "password": PASSWORD},
              base_url=SECURE, follow_redirects=True)
    html = page.get("/security/2fa/verify", base_url=SECURE).get_data(as_text=True)

    assert 'name="code"' in html, "the code screen does not ask for a code"
    assert "twoFactorModal" not in html, "the code screen was turned into a dialog"


def test_with_the_second_factor_off_the_dialog_offers_to_set_it_up(panel):
    """The other state, and it must not show a field for a code nobody
    has."""
    app, store = panel
    _client, html = _the_panel(app, store, enabled=False)
    dialog = _the_dialog(html)

    assert "/security/2fa/setup" in dialog, dialog[:400]
    assert "/security/2fa/disable" not in dialog, (
        "the dialog offers to switch off a second factor that is off")
