# -*- coding: utf-8 -*-
"""The idle timeout says what it does, and does not promise a login it cannot ask for.

THE FINDING (independent review of the web panel, 2026-09-23): after
DDC_SESSION_IDLE_TIMEOUT the handler clears the session and answers 401 with
``WWW-Authenticate: Basic realm="DDC"`` and the message

    "Session expired due to inactivity. Please re-authenticate."

The panel's authentication is HTTP Basic. A browser replays Basic credentials
for the same realm by itself, without asking anybody - and ``session.clear()``
has just removed ``last_activity``, the one value that would have noticed. So
the next request finds no last activity, sets it to now, and sails through.
Without 2FA the control costs exactly one 401 and lets the operator straight
back in.

MEASURED, and this is the part worth keeping: with 2FA switched ON it DOES
work. session.clear() also removes ``two_factor_ok``, and the 2FA guard then
sends the operator to /security/2fa/verify for a fresh code. The control is
real in the configuration where it is optional and inert in the one where it
is the only thing there is.

This cannot be closed inside the handler: with HTTP Basic there is no way for a
server to make a browser ask again. What can be fixed is the CLAIM. Telling the
operator they have been logged out when they have not is the same fault as
reporting a save that did not happen - it is just pointed at a security
control, where believing it is worse. Whether the panel should get a real form
login instead is an operator decision and is written down as one.

REVISITED 2026-09-23: the operator decided on the form login, and it is built.
The world this file described has changed in half: session.clear() now also
drops the auth marker, so for a FORM user the idle timeout really does log
them out and the next page is /login. For a browser that came in with HTTP
Basic - still a fallback by operator decision - nothing changed: it replays
its credentials by itself and no server can stop it.

So the rule is no longer "never promise a login". It is: promise one only
while also naming the case where it does not hold. A message that promises
and stays silent about Basic is the same overclaim as before, and the first
wording written for the form login did exactly that - it was caught here.

HOW THIS TEST CAN FAIL: it reads the answer with 2FA off. A promise of
re-authentication that does not also name HTTP Basic is red.

COUNTER-CHECK (2026-09-23): red before - "Please re-authenticate." The other
tests keep what is real: with 2FA the second factor is cleared, the CSRF token
survives either way, and an active session is not touched.
"""

import time

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DDC_SESSION_IDLE_TIMEOUT", "60")
    import importlib

    import app.web.security as security
    importlib.reload(security)

    from flask import Flask, jsonify

    app = Flask(__name__)
    app.secret_key = "test"
    security.install_security_handlers(app)

    @app.route("/anywhere")
    def anywhere():
        return jsonify({"ok": True})

    return app.test_client()


def _go_idle(client):
    """One request, then the session's last activity moved into the past."""
    client.get("/anywhere")
    with client.session_transaction() as session:
        session["last_activity"] = time.time() - 10_000
        session["csrf_token"] = "keep-me"
        session["two_factor_ok"] = "a-binding"


def test_the_answer_does_not_promise_a_login_it_cannot_ask_for(client):
    """THE FINDING, and what is left of it: a form user IS logged out now, a
    Basic browser is not. The message may say the first only if it says the
    second too."""
    _go_idle(client)

    response = client.get("/anywhere")
    message = response.get_json()["message"].lower()

    assert response.status_code == 401
    promises_a_login = "re-authenticate" in message or "log in again" in message
    if promises_a_login:
        assert "basic" in message, (
            f"the panel promises a login that a browser holding HTTP Basic "
            f"credentials will not be asked for, and does not say so: {message!r}")


def test_the_idle_timeout_really_drops_a_form_login(client):
    """The half that became real on 2026-09-23: the auth marker goes with the
    rest of the session, so the next page is the form."""
    from app.auth import SESSION_AUTH_KEY

    client.get("/anywhere")
    with client.session_transaction() as session:
        session["last_activity"] = time.time() - 10_000
        session[SESSION_AUTH_KEY] = "a-binding"

    client.get("/anywhere")

    with client.session_transaction() as session:
        assert SESSION_AUTH_KEY not in session, (
            "a form login survived the idle timeout - then the timeout is "
            "inert for the way most operators get in")


def test_the_answer_still_says_the_session_went_idle(client):
    """Saying less must not become saying nothing."""
    _go_idle(client)

    body = client.get("/anywhere").get_json()

    assert body["error"] == "session_idle_timeout"
    assert "idle" in body["message"].lower() or "inactiv" in body["message"].lower()


def test_the_second_factor_is_cleared(client):
    """The part that IS real: with 2FA on, a fresh code is required."""
    _go_idle(client)

    client.get("/anywhere")
    with client.session_transaction() as session:
        assert "two_factor_ok" not in session, (
            "the second factor survived the idle timeout, so 2FA would not ask again")


def test_the_csrf_token_survives(client):
    """Counter-check: the open page still carries it; dropping it breaks saves."""
    _go_idle(client)

    client.get("/anywhere")
    with client.session_transaction() as session:
        assert session.get("csrf_token") == "keep-me"


def test_an_active_session_is_not_touched(client):
    """Counter-check: the everyday request."""
    client.get("/anywhere")

    response = client.get("/anywhere")

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session.get("last_activity") is not None
