# -*- coding: utf-8 -*-
"""With 2FA on, a form login is asked for the code too - it was not.

THE OPERATOR, 2026-09-25: "when I click 'Back to the panel' I am logged out."
The live log of 26/Sep 00:13 tells the whole story, and the last two lines are
not about being logged out at all::

    00:13:33  GET  /security/2fa            401   (no session, no credentials)
    00:13:33  GET  /security/2fa            302   (browser replays Basic -> verify)
    00:13:48  POST /security/2fa/verify     302   (he answers the code)
    00:13:53  GET  /security/2fa            200
    00:13:54  WARNING Failed login attempt for user:        <- empty name
    00:13:54  GET  /                        302   -> /login?next=/
    00:14:06  INFO Panel login: admin
    00:14:06  GET  /                        200   <- AND NO CODE WAS ASKED FOR

THE LOGOUT is a browser rule: HTTP Basic credentials are replayed only for
paths at or below the one that asked for them, so the pair he typed for
``/security/2fa`` was not sent for ``/``. With no session either, the panel had
nothing to go on and sent him to the form. That is the symptom.

THE DEFECT IS THE LAST LINE. He logged in with the form and walked straight
into the panel, with the second factor switched ON and never asked. The gate
reads::

    credentials = request.authorization
    if credentials is None or credentials.type != "basic":
        return None                 # <- every form login, every time

The check was written in a panel that only had HTTP Basic. The login form
arrived on 2026-09-23 and became the normal way in; the gate was never told.
So since that day the second factor has stood in front of curl and the Unraid
integrations - and in front of nobody who uses the panel.

IT IS THE DAY'S OWN SHAPE ONE MORE TIME: a statement the code makes that is not
true. The module docstring says "every authenticated request needs a session
that has also passed a code", the panel prints "Two-factor authentication is
on", and for the operator's own browser neither was so.

WHAT THIS CHANGES FOR THE OPERATOR: after a form login he is asked for the six
digits, once per session - which is what switching 2FA on was supposed to mean.

HOW THIS TEST CAN FAIL: a form session reaching an authenticated page while the
second factor is on and unanswered.

COUNTER-CHECK (2026-09-26): red before - the form session got 200.
"""

import base64
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
    from app.auth import (auth, auth_limiter, clear_credential_cache, setup_limiter,
                          two_factor_limiter)
    from app.web import create_app
    from services.web.two_factor_service import TwoFactorStore

    # Hashed ONCE: the salt differs per call and both the session marker and
    # the second-factor marker are bound to the hash, so a stub that hashes on
    # every call makes every request look like a different password.
    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    # A page of the panel's own kind: authenticated, HTML, nothing else on it.
    # The real "/" pulls in the configuration page service and 37 containers,
    # which has nothing to do with the question this file asks.
    @app.route("/__panel")
    @auth.login_required
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


def _logged_in_with_the_form(app):
    client = app.test_client()
    answer = client.post("/login", base_url=SECURE,
                         data={"username": "admin", "password": PASSWORD, "next": "/__panel"})

    assert answer.status_code == 302, f"the form login itself failed: {answer.status_code}"
    return client


def _answer_the_code(client, store, when=None):
    from services.web.two_factor_service import secret_bytes, totp

    return client.post("/security/2fa/verify", base_url=SECURE, data={
        "code": totp(secret_bytes(store.pending_or_active_secret()), when or time.time()),
        "next": "/__panel"})


def test_a_form_session_is_asked_for_the_code(panel):
    """THE FINDING. He logged in with the form at 00:14:06 and was in the
    panel at 00:14:06, with the second factor on."""
    app, store = panel
    _switch_on(store)
    client = _logged_in_with_the_form(app)

    answer = client.get("/__panel", base_url=SECURE)

    assert answer.status_code == 302, (
        "a form login walked past the second factor - it stands in front of "
        "HTTP Basic only, and the form has been the normal way in since "
        "2026-09-23")
    assert "/security/2fa/verify" in answer.headers["Location"], answer.headers["Location"]


def test_and_is_let_through_once_it_is_answered(panel):
    """The other half: asked ONCE, not on every request."""
    app, store = panel
    _switch_on(store)
    client = _logged_in_with_the_form(app)

    _answer_the_code(client, store)

    assert client.get("/__panel", base_url=SECURE).status_code == 200, \
        "the code was answered and the panel still asks"


def test_the_form_login_alone_is_not_enough(panel):
    """THE SAME THING SAID FROM THE OTHER SIDE, because the case above could
    pass on a gate that asks everybody including the unauthenticated: the
    session IS logged in - session_user() returns admin - and is still sent to
    the code page."""
    from app.auth import SESSION_AUTH_KEY

    app, store = panel
    _switch_on(store)
    client = _logged_in_with_the_form(app)

    with client.session_transaction() as session:
        assert session.get(SESSION_AUTH_KEY), "the form login wrote no session marker"

    assert client.get("/__panel", base_url=SECURE).status_code == 302


def test_a_basic_request_is_still_asked(panel):
    """The behaviour that always worked must go on working: curl and the
    Unraid integrations are a fallback by operator decision, not a way
    round."""
    app, store = panel
    _switch_on(store)

    answer = app.test_client().get("/__panel", headers=_basic(), base_url=SECURE)

    assert answer.status_code == 302, answer.status_code


def test_nothing_is_asked_while_the_second_factor_is_off(panel):
    """THE OPPOSITE MISTAKE: a gate that asks when 2FA is off would lock the
    panel behind a code nobody has."""
    app, _store = panel
    client = _logged_in_with_the_form(app)

    assert client.get("/__panel", base_url=SECURE).status_code == 200


def test_somebody_with_no_login_is_not_sent_to_the_code_page(panel):
    """A visitor holding neither password nor code must not be sent to the
    code page: it is login_required itself, so they would bounce straight
    back with nothing to type. Whether the answer is the login form or a 401
    is the LOGIN's question, not this gate's - and in this harness it is a
    401, because auth_error re-imports load_config and so reads the empty
    temporary config rather than the stub.
    """
    app, store = panel
    _switch_on(store)

    answer = app.test_client().get("/__panel", base_url=SECURE)

    assert answer.status_code != 200, "an unauthenticated request reached the panel"
    assert "security/2fa/verify" not in answer.headers.get("Location", ""), \
        answer.headers.get("Location")


def test_the_login_form_stays_reachable(panel):
    """The door a form user is sent to cannot be behind the gate, or the
    redirect above is a loop."""
    app, store = panel
    _switch_on(store)

    assert app.test_client().get("/login", base_url=SECURE).status_code == 200


def test_the_code_page_stays_reachable_for_a_form_session(panel):
    """And the page that ASKS for the code cannot need one."""
    app, store = panel
    _switch_on(store)
    client = _logged_in_with_the_form(app)

    assert client.get("/security/2fa/verify", base_url=SECURE).status_code == 200


def test_a_wrong_password_is_not_let_in_by_the_gate(panel):
    """The gate returns None for anybody it does not recognise, so that the
    route's own login check answers. That must not become a way in: a
    request with a wrong password ends at the login, not at the panel."""
    app, store = panel
    _switch_on(store)

    answer = app.test_client().get("/__panel", headers=_basic("admin", "wrong"),
                                   base_url=SECURE)

    assert answer.status_code in (302, 401), answer.status_code
    # A redirect must go to the login, not to the code page: the code page
    # would mean the gate took the wrong password for a right one (audit
    # 2026-09-26 - the status alone let that pass).
    assert "/security/2fa/verify" not in answer.headers.get("Location", "")
