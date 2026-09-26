# -*- coding: utf-8 -*-
"""Switching the second factor off gives plain HTTP back, and the way out works.

TWO FINDINGS (audit 2026-09-26), both only visible with CSRF switched ON - the
other second-factor files build their app with WTF_CSRF_ENABLED False, which is
why they stayed green:

1. THE SECURE FLAG OUTLIVED THE FACTOR. While 2FA was on, the gate wrote
   `app.config["SESSION_COOKIE_SECURE"] = True` - into the app's global config,
   the very pattern app/web/security.py warns against. Nothing ever set it
   back. After switching 2FA off on a plain-HTTP install, every response still
   set a Secure cookie that the browser drops over HTTP, the login form's CSRF
   token never came back, and `POST /login` failed with "session_missing" -
   the panel was unusable until the container restarted.

2. THE PLAIN-HTTP WAY OUT COULD NOT BE WALKED. It is exempt from the HTTPS
   rule so that whoever switches TLS off is not locked into a factor he can no
   longer confirm. But CSRFProtect runs first, and over plain HTTP with 2FA on
   no page hands out a token (they all answer 403). Every attempt ended in a
   CSRF 400. The request carries its own proof against forgery - a current
   code, which no other site can know - so the way out is exempt from the
   token, and only it.

HOW THIS TEST CAN FAIL: a Secure cookie after 2FA is off, a way out that
needs a token nobody can get, or a CSRF exemption wider than the way out.

COUNTER-CHECK (2026-09-26): red before - the login page answered with a
Secure cookie after the factor was switched off, and the plain-HTTP disable
returned 400 (CSRF). The last case was green before and after: the exemption
reaches no other route.
"""

import base64
import time

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"
SECURE = "https://panel.test"
PLAIN = "http://panel.test"


def _basic():
    token = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache, setup_limiter, two_factor_limiter
    from app.web import create_app
    from services.web.two_factor_service import TwoFactorStore

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    # CSRF ON: the production setting, and the one both findings hide behind.
    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": True}), TwoFactorStore(tmp_path / "two_factor.json")
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _enable(store):
    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def _current_code(store):
    from services.web.two_factor_service import secret_bytes, totp

    return totp(secret_bytes(store.pending_or_active_secret()), time.time())


def _set_cookies(answer):
    return [value for name, value in answer.headers if name == "Set-Cookie"]


def test_after_2fa_is_off_the_cookie_travels_over_plain_http_again(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()
    # 2FA on: a request over HTTPS passes the gate while the factor is on
    client.get("/login", base_url=SECURE)
    store.disable(_current_code(store))
    assert store.enabled is False

    answer = app.test_client().get("/login", base_url=PLAIN)

    cookies = _set_cookies(answer)
    assert cookies, "the login page set no session cookie - then this proves nothing"
    assert not any("Secure" in cookie for cookie in cookies), cookies


def test_the_cookie_is_still_secure_while_2fa_is_on(panel):
    """Counter-case: the flag must still be there while the factor is."""
    app, store = panel
    _enable(store)

    answer = app.test_client().get("/login", base_url=SECURE)

    cookies = _set_cookies(answer)
    assert cookies and all("Secure" in cookie for cookie in cookies), cookies


def test_the_plain_http_way_out_works_with_csrf_on(panel):
    app, store = panel
    _enable(store)

    answer = app.test_client().post("/security/2fa/disable", data={"code": _current_code(store)},
                                    headers=_basic(), base_url=PLAIN)

    assert answer.status_code != 400, answer.get_data(as_text=True)[:300]
    assert store.enabled is False


def test_no_other_second_factor_route_is_exempt_from_the_token(panel):
    """The exemption is the way out alone: the setting that forgets devices,
    for one, still needs the token."""
    app, store = panel

    answer = app.test_client().post("/security/2fa/devices", data={},
                                    headers=_basic(), base_url=SECURE)

    assert answer.status_code == 400, answer.status_code
