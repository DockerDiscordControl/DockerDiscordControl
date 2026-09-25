# -*- coding: utf-8 -*-
"""Remembering a device is an offer the operator can withdraw.

THE OPERATOR, 2026-09-25, on the ninety-day device memory: "that must be
optional."

IT ALREADY WAS, PER LOGIN - an empty checkbox, and nothing is written down
unless it is ticked. He meant the other kind of optional, and he was right to
ask for it: a remembered device skips the second factor for ninety days, so
whoever turns 2FA ON for safety may not want that possibility in the house at
all. "Offered, never forced" is the rule he set for 2FA itself; this is the
same rule one level in.

THE SWITCH LIVES WITH THE SECOND FACTOR, not in the settings form. Everything
else about 2FA - whether it is on, the secret, the recovery hashes, the
remembered devices - is in config/two_factor.json with its own 0600 write, and
splitting one of them into the panel's big save would mean two files answering
one question.

SWITCHING IT OFF FORGETS AT ONCE. A setting that only stopped OFFERING would
leave the browsers already written down walking past the second factor for the
rest of their ninety days, which is the opposite of what he asked for.

AND THE BACK DOOR IS SHUT TOO: with the offer withdrawn, a request that sends
``remember_device`` anyway - the box is gone from the page, not from HTTP -
remembers nothing.

HOW THIS TEST CAN FAIL: an offer that cannot be withdrawn, a withdrawal that
leaves old devices standing, or one that only hides the box.

COUNTER-CHECK (2026-09-25): red before - no switch at all.
"""

import base64
import time

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "correct horse"
SECURE = "https://localhost"
COOKIE = "ddc_2fa_device"


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

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @app.route("/__panel")
    def _panel():
        return "panel"

    yield app, TwoFactorStore(tmp_path / "two_factor.json")

    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _switch_on(store):
    from services.web.two_factor_service import secret_bytes, totp

    store.begin_setup()
    now = time.time()
    store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def _answer_the_code(app, store, remember, when=None):
    from services.web.two_factor_service import secret_bytes, totp

    client = app.test_client()
    data = {"code": totp(secret_bytes(store.pending_or_active_secret()),
                         when or time.time()),
            "next": "/__panel"}
    if remember:
        data["remember_device"] = "1"
    client.post("/security/2fa/verify", headers=_basic(), base_url=SECURE, data=data)
    return client


def test_it_is_offered_until_it_is_withdrawn(panel):
    """The starting point, so the case below is not measuring an empty
    room: DDC offers it, because that is what he asked for first."""
    app, store = panel
    _switch_on(store)

    page = app.test_client().get("/security/2fa/verify", headers=_basic(),
                                 base_url=SECURE).get_data(as_text=True)

    assert 'name="remember_device"' in page
    assert store.remembering_devices_allowed() is True


def test_the_switch_is_with_the_second_factor(panel):
    """A setting with no control is not a setting. It belongs on the page
    that turns 2FA on and off, where everything else about it lives."""
    app, store = panel
    _switch_on(store)
    # Past the second factor first: the status page is behind it, which is
    # where a setting about the second factor belongs.
    client = _answer_the_code(app, store, remember=False)

    page = client.get("/security/2fa", headers=_basic(),
                      base_url=SECURE).get_data(as_text=True)

    assert "remember_devices_allowed" in page, "no way to withdraw the offer"


def test_withdrawing_it_takes_the_box_away(panel):
    """THE REQUEST: with the offer withdrawn, nobody is asked to make it."""
    app, store = panel
    _switch_on(store)
    _answer_the_code(app, store, remember=False)

    store.set_remembering_devices(False)
    page = app.test_client().get("/security/2fa/verify", headers=_basic(),
                                 base_url=SECURE).get_data(as_text=True)

    assert 'name="remember_device"' not in page, "the box is still offered"


def test_a_request_that_asks_anyway_is_not_remembered(panel):
    """The box is gone from the PAGE, not from HTTP. A setting that only
    hid it would be a setting in name."""
    app, store = panel
    _switch_on(store)
    store.set_remembering_devices(False)

    client = _answer_the_code(app, store, remember=True)

    assert client.get_cookie(COOKIE) is None, "it was remembered anyway"
    assert store.remembered_devices() == 0


def test_withdrawing_it_forgets_the_ones_already_known(panel):
    """A switch that only stopped OFFERING would leave the browsers already
    written down walking past the second factor for the rest of their ninety
    days - the opposite of what was asked for."""
    app, store = panel
    _switch_on(store)
    client = _answer_the_code(app, store, remember=True)
    device = client.get_cookie(COOKIE)

    assert device is not None and store.remembered_devices() == 1

    store.set_remembering_devices(False)

    assert store.remembered_devices() == 0, "the old devices are still known"

    fresh = app.test_client()
    fresh.set_cookie(COOKIE, device.value, domain="localhost")

    assert fresh.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 302


def test_turning_it_back_on_does_not_bring_them_back(panel):
    """Forgetting is forgetting. A device that came back after a round trip
    through the switch would make the withdrawal a pause."""
    app, store = panel
    _switch_on(store)
    client = _answer_the_code(app, store, remember=True)
    device = client.get_cookie(COOKIE)

    store.set_remembering_devices(False)
    store.set_remembering_devices(True)

    fresh = app.test_client()
    fresh.set_cookie(COOKIE, device.value, domain="localhost")

    assert fresh.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 302
    assert store.remembering_devices_allowed() is True


def test_the_switch_needs_no_save_button(panel):
    """THE OPERATOR: "I find the Save button unnecessary - can we write the
    state down as soon as it is used?"

    He is right: a switch with one state and a Save beside it asks twice for
    one decision, and the half-done middle - flipped but not saved - is a
    state the panel then has to explain. It posts on change.

    WITHOUT JAVASCRIPT IT STILL WORKS, which is the promise this file's
    template has carried since it was written: the submit button is kept
    inside <noscript>, so a browser that cannot flip it for you still has
    the plain form the rest of the page is built on.
    """
    app, store = panel
    _switch_on(store)
    client = _answer_the_code(app, store, remember=False)
    page = client.get("/security/2fa", headers=_basic(), base_url=SECURE).get_data(as_text=True)

    card = page[page.index("remember_devices_allowed"):][:900]

    assert "this.form.submit()" in card, (
        f"the switch still waits for a Save button: {card[:300]}")
    assert "<noscript>" in card, (
        "with no script left, a browser without JavaScript cannot change it at all")


def test_the_switch_answers_through_the_panel(panel):
    """It is reached by a form on the page, not only from Python."""
    app, store = panel
    _switch_on(store)
    client = _answer_the_code(app, store, remember=False)

    # An absent checkbox is an unticked one: a browser sends nothing for a
    # box it did not tick, so the form's silence has to mean "off".
    client.post("/security/2fa/devices", headers=_basic(), base_url=SECURE, data={})

    assert store.remembering_devices_allowed() is False, "the form did not switch it off"

    client.post("/security/2fa/devices", headers=_basic(), base_url=SECURE,
                data={"remember_devices_allowed": "1"})

    assert store.remembering_devices_allowed() is True, "the form did not switch it back on"
