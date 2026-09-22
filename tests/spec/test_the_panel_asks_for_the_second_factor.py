# -*- coding: utf-8 -*-
"""With 2FA on, the panel password alone does not open the panel (v3.0 step 9, door B).

V3 §1: door B is the web panel, reached by whoever has the panel password -
reused, leaked or guessed. The second factor closes it; the proxy does not.
Operator decision 2026-09-22: offered and strongly recommended, never forced,
set up only over TLS, with recovery codes and a host break-glass.

Through the real app (create_app), the real Basic-Auth check and a real
two_factor.json in the test's config directory:

* password right, second factor not given -> the panel is closed (redirect
  to the code page for a browser, 401 for an API call);
* a current code or a recovery code opens it for the session;
* guessing codes is braked like guessing passwords;
* setup is refused over plain HTTP - a code typed over HTTP is readable on
  the LAN and replayable within its window (V3 §5.1);
* an unreadable two_factor.json closes the panel instead of opening it;
* while 2FA is off the panel says so, first as a setup dialog with "Later",
  then as a notice that stays.

COUNTER-CHECK (2026-09-22): written before the routes existed. Afterwards the
enforcement step was taken out of create_app: the "password alone" tests went
red and the setup-step wiring test named the missing step.
"""

import base64

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "correct horse"
PLAIN = "http://localhost"
SECURE = "https://localhost"


def _basic(user="admin", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    """(app, store) with a configured password and 2FA state in tmp_path."""
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, setup_limiter, two_factor_limiter, clear_credential_cache
    from app.web import create_app
    from services.web.two_factor_service import TwoFactorStore

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @app.route("/__panel")
    @auth_module.auth.login_required
    def _panel():
        return "panel"

    yield app, TwoFactorStore(tmp_path / "two_factor.json")
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _enable(store):
    import time

    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    codes = store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)
    return codes


def _current_code(store):
    import time

    from services.web.two_factor_service import secret_bytes, totp

    return totp(secret_bytes(store.pending_or_active_secret()), time.time())


def test_without_2fa_the_password_is_enough(panel):
    app, _ = panel
    assert app.test_client().get("/__panel", headers=_basic()).status_code == 200


# The five tests below speak https: with 2FA switched on DDC answers only over
# HTTPS now (the session marker IS the passed second factor - see
# tests/spec/test_the_second_factor_never_travels_in_the_clear.py). They are
# about the gate, not about the transport, and used the client's default
# http://localhost before.
def test_the_password_alone_does_not_open_the_panel(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()
    page = client.get("/__panel", headers=_basic(), base_url=SECURE)
    assert page.status_code == 302 and "/security/2fa/verify" in page.headers["Location"]
    api = client.get("/__panel", headers={**_basic(), "Accept": "application/json"}, base_url=SECURE)
    assert api.status_code == 401


def test_a_wrong_password_still_gets_the_plain_401(panel):
    app, store = panel
    _enable(store)
    assert app.test_client().get("/__panel", headers=_basic(password="wrong"), base_url=SECURE).status_code == 401


def test_a_current_code_opens_the_panel_for_the_session(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()
    answer = client.post("/security/2fa/verify", data={"code": _current_code(store)}, headers=_basic(), base_url=SECURE)
    assert answer.status_code == 302
    assert client.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 200


def test_a_recovery_code_opens_it_once(panel):
    app, store = panel
    codes = _enable(store)
    first = app.test_client()
    first.post("/security/2fa/verify", data={"code": codes[0]}, headers=_basic(), base_url=SECURE)
    assert first.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 200
    second = app.test_client()
    second.post("/security/2fa/verify", data={"code": codes[0]}, headers=_basic(), base_url=SECURE)
    assert second.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 302


def test_guessing_codes_is_braked(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()
    statuses = [client.post("/security/2fa/verify", data={"code": "000000"}, headers=_basic(), base_url=SECURE).status_code
                for _ in range(6)]
    assert statuses[-1] == 429, statuses


def test_setup_is_refused_over_plain_http(panel):
    app, store = panel
    answer = app.test_client().post("/security/2fa/setup", headers=_basic(), base_url=PLAIN)
    assert answer.status_code == 403
    assert store.pending_or_active_secret() is None


def test_setup_over_https_shows_a_qr_code_and_confirming_turns_it_on(panel):
    app, store = panel
    client = app.test_client()
    page = client.post("/security/2fa/setup", headers=_basic(), base_url=SECURE)
    assert page.status_code == 200 and b"<svg" in page.data
    done = client.post("/security/2fa/confirm", data={"code": _current_code(store)},
                       headers=_basic(), base_url=SECURE)
    assert done.status_code == 200 and store.enabled
    assert store.remaining_recovery_codes() == 10


def test_an_unreadable_state_file_closes_the_panel(panel, tmp_path):
    app, _ = panel
    (tmp_path / "two_factor.json").write_text("{broken")
    client = app.test_client()
    assert client.get("/__panel", headers=_basic()).status_code == 503
    assert client.get("/health").status_code in (200, 500)  # /health is not behind 2FA


@pytest.mark.parametrize("path,method", [("/security/2fa", "get"), ("/security/2fa/verify", "get"),
                                         ("/security/2fa/verify", "post"), ("/security/2fa/disable", "post")])
def test_an_unreadable_state_file_closes_the_2fa_pages_too(panel, tmp_path, path, method):
    """The 2FA pages themselves are exempt from the gate - they must still answer
    the deliberate 503 rather than raising a 500 out of TwoFactorStore."""
    app, _ = panel
    (tmp_path / "two_factor.json").write_text("{broken")

    answer = getattr(app.test_client(), method)(path, headers=_basic(), data={"code": "000000"})

    assert answer.status_code == 503, answer.status_code


def test_the_panel_offers_setup_until_later_then_keeps_a_notice(panel):
    app, store = panel
    from flask import render_template_string

    with app.test_request_context("/", base_url=SECURE):
        dialog = render_template_string("{% include '_two_factor_notice.html' %}")
    assert 'data-two-factor="prompt"' in dialog
    store.dismiss_prompt()
    with app.test_request_context("/", base_url=SECURE):
        notice = render_template_string("{% include '_two_factor_notice.html' %}")
    assert 'data-two-factor="notice"' in notice and 'data-two-factor="prompt"' not in notice
    _enable(store)
    with app.test_request_context("/", base_url=SECURE):
        quiet = render_template_string("{% include '_two_factor_notice.html' %}")
    assert "data-two-factor" not in quiet


def test_the_notice_is_part_of_every_panel_page():
    from pathlib import Path

    base = (Path(__file__).resolve().parents[2] / "app" / "templates" / "_base.html").read_text(encoding="utf-8")
    assert "{% include '_two_factor_notice.html' %}" in base
