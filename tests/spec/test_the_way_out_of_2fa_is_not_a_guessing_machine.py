# -*- coding: utf-8 -*-
"""Switching the second factor off takes a code, and codes cannot be guessed there.

THE FINDING (audit 2026-09-26). `/security/2fa/verify` has been braked at five
attempts per minute and address since the factor was written. The way OUT,
`/security/2fa/disable`, checks the same six digits through the same store -
and had no brake at all. It is exempt from the passed second factor on purpose
(it exists for somebody who cannot pass one), so whoever holds only the panel
password could post codes there as fast as the server answered: three valid
codes in a million, ~330,000 guesses on average, a matter of hours. A hit
switches the factor off for good and forgets every recovery code and device.
The Basic-auth limiter did not help either: a form-login session sends no
Authorization header, and that limiter only looks at requests that do.

THE CONTRACT: every route that checks a second-factor code shares ONE brake.
Five wrong codes from an address and the sixth attempt is refused - even when
it carries the right code - and the factor stays on.

HOW THIS TEST CAN FAIL: a way to test codes against the store that does not
count against the brake.

COUNTER-CHECK (2026-09-26): red before the fix - the sixth post with the right
code switched the factor off (status 302, store.enabled False). Green after.
"""

import base64

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"
SECURE = "https://panel.test"


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

    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}), TwoFactorStore(tmp_path / "two_factor.json")
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _enable(store):
    import time

    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def _current_code(store):
    import time

    from services.web.two_factor_service import secret_bytes, totp

    return totp(secret_bytes(store.pending_or_active_secret()), time.time())


def _wrong_code(store):
    right = _current_code(store)
    return "000000" if right != "000000" else "111111"


def test_guessing_at_the_way_out_is_braked(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()
    for _ in range(5):
        client.post("/security/2fa/disable", data={"code": _wrong_code(store)},
                    headers=_basic(), base_url=SECURE)

    answer = client.post("/security/2fa/disable", data={"code": _current_code(store)},
                         headers=_basic(), base_url=SECURE)

    assert answer.status_code == 429
    assert store.enabled is True


def test_the_brake_is_shared_with_the_code_page(panel):
    """One brake, not one per door: guesses spent on the code page count at
    the way out, or an attacker would simply alternate between the two."""
    app, store = panel
    _enable(store)
    client = app.test_client()
    for _ in range(5):
        client.post("/security/2fa/verify", data={"code": _wrong_code(store)},
                    headers=_basic(), base_url=SECURE)

    answer = client.post("/security/2fa/disable", data={"code": _current_code(store)},
                         headers=_basic(), base_url=SECURE)

    assert answer.status_code == 429
    assert store.enabled is True


def test_one_right_code_still_switches_it_off(panel):
    """Counter-case: the brake must not close the way out for the operator
    who types the right code on the first try."""
    app, store = panel
    _enable(store)

    app.test_client().post("/security/2fa/disable", data={"code": _current_code(store)},
                           headers=_basic(), base_url=SECURE)

    assert store.enabled is False
