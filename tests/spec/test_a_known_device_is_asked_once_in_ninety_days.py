# -*- coding: utf-8 -*-
"""A device you told the panel to remember is not asked again for 90 days.

THE OPERATOR, 2026-09-25: "when logging in you should have the chance to
remember the current device for 90 days."

WHAT IT SKIPS, AND WHAT IT DOES NOT. It skips the SECOND factor. The panel
password is still asked on every visit exactly as before - a remembered
device is a device that has already proved it holds the phone, not one that
may walk in.

WHAT REVOKES IT, and each of these is a case below:

    90 days pass                 the entry carries its own expiry
    the panel password changes   the entry is bound to the password hash,
                                 the same binding the session marker uses
    2FA is switched off          every entry goes with it
    the cookie is not ours       an unknown token matches nothing

WHY THE TOKEN IS STORED AS A HASH. config/two_factor.json already holds only
sha256 of each recovery code, for the reason that a file readable by anything
running as this user must not BE the credential. A remembered device is a
credential, so it is kept the same way: the browser holds the token, the
panel holds its hash.

THE COOKIE IS HttpOnly, so a script cannot read it, and Secure whenever the
request that set it was - which is always, because the second factor refuses
plain HTTP in the first place.

HOW THIS TEST CAN FAIL: a remembered device that still has to answer, a
forgotten one that does not, or a cookie that outlives the password it was
bound to.

COUNTER-CHECK (2026-09-25): red before - no checkbox, no cookie, no store.
"""

import base64
import time

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "correct horse"
SECURE = "https://localhost"
COOKIE = "ddc_2fa_device"
NINETY_DAYS = 90 * 24 * 60 * 60


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

    # Hashed ONCE: the salt differs per call and the second-factor marker is
    # bound to the hash, so a stub that hashes on every call makes every
    # request look like a different password.
    hashed = {"value": generate_password_hash(PASSWORD)}
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin",
                                 "web_ui_password_hash": hashed["value"]})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @app.route("/__panel")
    def _panel():
        return "panel"

    yield app, TwoFactorStore(tmp_path / "two_factor.json"), hashed

    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _switch_on(store):
    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def _pass_the_second_factor(app, store, remember):
    """A fresh browser that answers the code, with or without the tick."""
    from services.web.two_factor_service import secret_bytes, totp

    client = app.test_client()
    data = {"code": totp(secret_bytes(store.pending_or_active_secret()), time.time()),
            "next": "/__panel"}
    if remember:
        data["remember_device"] = "1"
    client.post("/security/2fa/verify", headers=_basic(), base_url=SECURE, data=data)
    return client


def _a_second_visit(app, client):
    """The same browser, a new session - the cookie is all that is left."""
    fresh = app.test_client()
    for cookie in client.cookie_jar if hasattr(client, "cookie_jar") else []:
        fresh.set_cookie(cookie.name, cookie.value, domain=cookie.domain)
    return fresh


def test_a_remembered_device_is_not_asked_again(panel):
    """THE REQUEST: answer once, then not again for ninety days."""
    app, store, _hash = panel
    _switch_on(store)
    client = _pass_the_second_factor(app, store, remember=True)

    device = client.get_cookie(COOKIE)

    assert device is not None, "nothing was remembered"

    fresh = app.test_client()
    fresh.set_cookie(COOKIE, device.value, domain="localhost")
    answer = fresh.get("/__panel", headers=_basic(), base_url=SECURE)

    assert answer.status_code == 200, (
        f"the remembered device was asked again: {answer.status_code} "
        f"{answer.headers.get('Location')}")


def test_without_the_tick_nothing_is_remembered(panel):
    """Counter-check: the offer is an offer. Whoever leaves the box alone is
    asked again, which is the behaviour everybody had until now."""
    app, store, _hash = panel
    _switch_on(store)
    client = _pass_the_second_factor(app, store, remember=False)

    assert client.get_cookie(COOKIE) is None, "a device was remembered unasked"

    fresh = app.test_client()
    answer = fresh.get("/__panel", headers=_basic(), base_url=SECURE)

    assert answer.status_code == 302, answer.status_code


def test_the_offer_is_on_the_screen_that_asks(panel):
    """A feature with no control is not offered. The box belongs on the
    verify screen, which is where the operator is when he wants it."""
    app, store, _hash = panel
    _switch_on(store)

    page = app.test_client().get("/security/2fa/verify", headers=_basic(),
                                 base_url=SECURE).get_data(as_text=True)

    assert 'name="remember_device"' in page, "no way to ask for it"
    assert "90" in page, "the page does not say how long it lasts"


def test_ninety_days_later_it_is_asked_again(panel):
    """The whole promise is ninety DAYS, not for ever."""
    app, store, _hash = panel
    _switch_on(store)
    client = _pass_the_second_factor(app, store, remember=True)
    device = client.get_cookie(COOKIE)

    store.forget_expired_devices(now=time.time() + NINETY_DAYS + 60)

    fresh = app.test_client()
    fresh.set_cookie(COOKIE, device.value, domain="localhost")

    assert fresh.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 302


def test_a_cookie_we_never_issued_is_nothing(panel):
    """The obvious attack: bring your own cookie."""
    app, store, _hash = panel
    _switch_on(store)

    fresh = app.test_client()
    fresh.set_cookie(COOKIE, "a" * 43, domain="localhost")

    assert fresh.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 302


def test_a_new_password_forgets_every_device(panel):
    """The same rule the session marker follows: a changed password asks for
    the code again. A remembered device that survived it would be a way past
    the second factor held by whoever had the old one."""
    app, store, hashed = panel
    _switch_on(store)
    client = _pass_the_second_factor(app, store, remember=True)
    device = client.get_cookie(COOKIE)

    from app.auth import clear_credential_cache
    hashed["value"] = generate_password_hash("a different one")
    clear_credential_cache()

    fresh = app.test_client()
    fresh.set_cookie(COOKIE, device.value, domain="localhost")
    answer = fresh.get("/__panel", headers=_basic("admin", "a different one"), base_url=SECURE)

    assert answer.status_code == 302, "the old device still walked past the second factor"


def test_switching_the_second_factor_off_forgets_them_all(panel):
    """Turning it off and on again must not hand the old devices back."""
    app, store, _hash = panel
    _switch_on(store)
    _pass_the_second_factor(app, store, remember=True)

    assert store.remembered_devices() >= 1

    from services.web.two_factor_service import secret_bytes, totp

    # A LATER step, and the result is checked: the code used a moment ago is
    # replay-protected, so reusing it makes disable() refuse - and a case
    # that did not look would have called the refusal a pass.
    later = time.time() + 60
    switched_off = store.disable(
        totp(secret_bytes(store.pending_or_active_secret()), later), now=later)

    assert switched_off, "the second factor was not switched off at all"
    assert store.remembered_devices() == 0, "the devices outlived the second factor"


def test_the_panel_keeps_the_hash_and_the_browser_the_token(panel):
    """A file readable by anything running as this user must not BE the
    credential - the same reason the recovery codes are stored hashed."""
    app, store, _hash = panel
    _switch_on(store)
    client = _pass_the_second_factor(app, store, remember=True)
    device = client.get_cookie(COOKIE)

    on_disk = store.path.read_text(encoding="utf-8")

    assert device.value not in on_disk, "the token itself is in the state file"
    assert "device" in on_disk, "nothing was written down at all"


def test_the_cookie_is_out_of_reach_of_a_script(panel):
    """It is a way past the second factor, so it is HttpOnly - and Secure,
    which costs nothing because 2FA refuses plain HTTP anyway."""
    app, store, _hash = panel
    _switch_on(store)

    from services.web.two_factor_service import secret_bytes, totp

    client = app.test_client()
    answer = client.post("/security/2fa/verify", headers=_basic(), base_url=SECURE,
                         data={"code": totp(secret_bytes(store.pending_or_active_secret()),
                                            time.time()),
                               "remember_device": "1", "next": "/__panel"})
    header = "; ".join(v for k, v in answer.headers if k == "Set-Cookie" and COOKIE in v)

    assert "HttpOnly" in header, header
    assert "Secure" in header, header
    assert "SameSite=Lax" in header, header
