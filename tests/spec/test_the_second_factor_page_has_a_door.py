# -*- coding: utf-8 -*-
"""The second-factor page can be reached from the panel, on or off.

THE OPERATOR, 2026-09-25, after switching 2FA on and reloading: "still no 2FA
switch." He was looking in the right place - System, Web UI authentication -
and it was not there. Nor was anything else.

THE PAGE HAD EXACTLY TWO DOORS, both of them in ``_two_factor_notice.html``,
and that notice renders only while ``two_factor.show`` is true - which is
``not enabled``. So switching the second factor ON took the only way to reach
it away:

    the remaining recovery codes   not visible
    the device-memory switch       not reachable
    switching 2FA back off         not reachable

...unless you know the URL. The feature closed the door behind itself.

IT IS THE DAY'S OWN DEFECT, one more time: a thing that exists and cannot be
got at. The mech panel had it, the close button had it, and this is the same
shape - except here the unreachable thing is how you turn the second factor
off again.

THE DOOR GOES WHERE HE LOOKED. Web UI authentication is where the panel's
password lives, and the second factor is the other half of that. It stands
beside the three buttons already there.

HOW THIS TEST CAN FAIL: a panel with no way to the second-factor page, in
either state.

COUNTER-CHECK (2026-09-25): red before - no link at all once 2FA was on.
"""

import base64
import re
import time

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "correct horse"
SECURE = "https://localhost"


def _basic(user="admin", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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


def _the_settings_page(app, store, verified):
    """The configuration page as the operator sees it."""
    from services.web.two_factor_service import secret_bytes, totp

    client = app.test_client()
    # LOGGED IN THROUGH THE FORM. The notice that used to be the only door is
    # decided by a context processor asking session_user(); with Basic auth
    # there is no session and it never renders - so a case looking for it
    # would be red for the wrong reason, which is how the first run of this
    # file behaved.
    client.post("/login", data={"username": "admin", "password": PASSWORD},
                base_url=SECURE, follow_redirects=True)
    if verified:
        client.post("/security/2fa/verify", headers=_basic(), base_url=SECURE,
                    data={"code": totp(secret_bytes(store.pending_or_active_secret()),
                                       time.time())})
    return client.get("/", headers=_basic(), base_url=SECURE,
                      follow_redirects=True).get_data(as_text=True)


def _doors_in(html):
    return re.findall(r'href="([^"]*security/2fa[^"]*)"', html)


def test_the_panel_leads_there_while_the_second_factor_is_off(panel):
    """The state he started in, and it worked - through the notice."""
    app, store = panel

    assert _doors_in(_the_settings_page(app, store, verified=False)), \
        "no way to the second factor from the panel"


def test_and_still_leads_there_once_it_is_on(panel):
    """THE FINDING: switching it on took the only way to reach it away, so
    the codes, the device switch and switching it off again all went with
    it."""
    app, store = panel
    _switch_on(store)

    html = _the_settings_page(app, store, verified=True)

    assert _doors_in(html), (
        "with the second factor ON the panel offers no way back to its page - "
        "the recovery codes, the device switch and switching it off are all "
        "out of reach")


def test_the_door_is_where_the_panel_password_is(panel):
    """Not just anywhere. The second factor is the other half of the panel
    password, and that is where he looked for it."""
    app, store = panel
    _switch_on(store)
    html = _the_settings_page(app, store, verified=True)
    where = html.index('id="auth-settings"') if 'id="auth-settings"' in html else 0
    nearby = html[where:where + 6000]

    assert _doors_in(nearby), (
        "the way to the second factor is not in the Web UI authentication "
        "section, which is where the panel password lives")


def test_the_notice_is_still_the_door_while_it_is_off(panel):
    """The opposite mistake: the notice earned its place - it is what told
    him the second factor existed at all. Adding a door elsewhere must not
    take that one away."""
    app, store = panel
    html = _the_settings_page(app, store, verified=False)

    assert "data-two-factor" in html, "the notice that offers 2FA is gone"
