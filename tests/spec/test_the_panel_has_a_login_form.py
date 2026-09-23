# -*- coding: utf-8 -*-
"""The panel is entered through a form, and the session is what carries it.

OPERATOR DECISION (2026-09-23): a real login instead of the browser's HTTP
Basic dialog - and HTTP Basic kept as a fallback, so curl, scripts and the
Unraid integrations that use `-u admin:...` go on working.

WHY IT IS A ONE-LINE HOOK AND NOT 75 EDITS: flask_httpauth's login_required
calls self.authenticate(auth, password) and nothing else. Making THAT method
look at the session first leaves all 75 @auth.login_required decorators
untouched and auth.current_user() working. Measured before building: 75
decorators across 11 files.

WHAT THE SESSION HOLDS: not a flag. It holds a binding - sha256 of the stored
password hash - exactly as the second factor already does. A flag would
outlive a password change, which is the one moment every session must end.
Changing the password already re-derives the bot token key from that same
hash, so the two stay in step by construction.

WHAT DOES NOT CHANGE: the credentials are checked by the same verify_password
as before, so the same 600,000 PBKDF2 rounds, the same verified-credential
cache and the same rate limiter apply. SESSION_COOKIE_SECURE stays False -
there is no TLS here, and a cookie the browser refuses to send is not a
security control, it is a panel that cannot be saved.

HOW THIS TEST CAN FAIL: it puts a session marker on the client and asks a
protected route without any Authorization header. If that is refused, the form
login does nothing. Then it changes the password hash under the same session
and asks again - if that is still let in, a stolen or stale session outlives
the password, which is the whole reason the marker is a binding.

COUNTER-CHECK (2026-09-23): red before - there was no session path at all, no
/login, and /logout only asked the browser to forget its Basic credentials.
"""

import hashlib

import pytest
from flask import Flask, jsonify, session


HASH_ONE = "pbkdf2:sha256:600000$aaa$1111"
HASH_TWO = "pbkdf2:sha256:600000$bbb$2222"


def _binding_for(stored_hash):
    return hashlib.sha256(stored_hash.encode()).hexdigest()[:24]


@pytest.fixture
def app(monkeypatch):
    """A minimal app with the real auth object and one protected route."""
    import app.auth as auth_module

    config = {"web_ui_user": "admin", "web_ui_password_hash": HASH_ONE}
    monkeypatch.setattr(auth_module, "load_config", lambda: config)
    # The password check itself is not what this file is about; the session
    # path must work with the real one behind it, so only the comparison is
    # stubbed - verify_password's own branches keep running.
    monkeypatch.setattr(auth_module, "check_password_hash",
                        lambda stored, given: (stored, given) == (HASH_ONE, "right"))

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-only"

    @flask_app.route("/protected")
    @auth_module.auth.login_required
    def protected():
        return jsonify(user=auth_module.auth.current_user())

    flask_app.config["_ddc_test_config"] = config
    return flask_app


def _with_session(client, value):
    with client.session_transaction() as stored:
        stored[__import__("app.auth", fromlist=["SESSION_AUTH_KEY"]).SESSION_AUTH_KEY] = value


def test_a_session_gets_in_without_any_credentials(app):
    """THE POINT: that is what a form login is."""
    client = app.test_client()
    _with_session(client, _binding_for(HASH_ONE))

    answer = client.get("/protected")

    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert answer.get_json()["user"] == "admin"


def test_a_session_from_before_a_password_change_does_not(app):
    """THE REASON THE MARKER IS A BINDING: a flag would outlive the password."""
    client = app.test_client()
    _with_session(client, _binding_for(HASH_ONE))
    app.config["_ddc_test_config"]["web_ui_password_hash"] = HASH_TWO

    assert client.get("/protected").status_code == 401


def test_no_session_and_no_credentials_is_refused(app):
    """Counter-check: the session must be the thing that decides, not chance."""
    assert app.test_client().get("/protected").status_code == 401


def test_a_session_marker_that_is_not_the_binding_is_refused(app):
    """Counter-check: any truthy value must not do - a cookie is client-side."""
    client = app.test_client()
    _with_session(client, "yes")

    assert client.get("/protected").status_code == 401


def test_basic_auth_still_works_without_a_session(app):
    """The operator's decision: curl and the scripts keep working."""
    import base64

    token = base64.b64encode(b"admin:right").decode()
    answer = app.test_client().get("/protected",
                                   headers={"Authorization": f"Basic {token}"})

    assert answer.status_code == 200
    assert answer.get_json()["user"] == "admin"


def test_a_wrong_password_is_still_refused(app):
    """Counter-check: the fallback is a fallback, not a hole."""
    import base64

    token = base64.b64encode(b"admin:wrong").decode()

    assert app.test_client().get("/protected",
                                 headers={"Authorization": f"Basic {token}"}).status_code == 401


# --- The routes that put the marker there and take it away -----------------


def test_the_login_page_is_reachable_without_being_logged_in():
    """A login page behind the login is a locked door with the key inside.

    Read from the syntax tree, not the text: a first version of this test
    failed on the module docstring, which says the file carries no
    login_required. A sentence about a decorator is not a decorator - the same
    trap that caught two other tests today.
    """
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[2] / "app" / "blueprints"
                      / "login_routes.py").read_text(encoding="utf-8"))
    decorators, routes = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            decorators.append(ast.dump(decorator))
            if isinstance(decorator, ast.Call):
                routes.extend(a.value for a in decorator.args if isinstance(a, ast.Constant))

    assert not any("login_required" in d for d in decorators), "the login page demands a login"
    assert "/login" in routes, "there is no /login route"


def test_the_second_factor_lets_the_login_page_through():
    """Counter-check: with 2FA on, the code page and the login page must both
    be reachable, or the operator can reach neither."""
    from app.blueprints.two_factor_routes import EXEMPT_PREFIXES

    assert "/login" in EXEMPT_PREFIXES


def test_the_idle_timeout_lets_the_login_page_through():
    """Counter-check: the same trap one layer down."""
    from app.web.security import _IDLE_EXEMPT_PATHS

    assert "/login" in _IDLE_EXEMPT_PATHS


def test_a_browser_is_sent_to_the_form_and_an_api_call_is_not():
    """The error handler decides which. A redirect answering a fetch() would
    be parsed as JSON and fail with something unrelated."""
    import inspect

    import app.auth as auth_module

    source = inspect.getsource(auth_module.auth_error)

    # The endpoint, not the path: the handler builds the URL with url_for, so
    # the literal "/login" never appears - and a test looking for it would go
    # green the day somebody redirects to the wrong endpoint.
    assert "login.login_page" in source, "a browser is never sent to the form"
    assert "_wants_json" in source or "is_json" in source, (
        "every refusal answers the same way, so either the API or the browser "
        "gets the wrong one")


def test_logging_out_drops_the_session_marker():
    """The form user's way out: the marker goes, the browser gets the form."""
    import inspect

    from app.blueprints import login_routes

    source = inspect.getsource(login_routes.logout)

    assert "session.clear()" in source
    assert "login.login_page" in source, "a form user is not sent back to the form"


def test_logging_out_still_makes_a_basic_browser_forget():
    """THE PART THAT CANNOT BE DROPPED: Basic stays as a fallback (operator
    decision), and a browser replays those credentials by itself. Clearing the
    session would leave such a browser logged in with nothing to show for it.
    The 401 with a fresh realm is still the only portable way to make it stop,
    so it stays - for the requests that actually came with credentials."""
    import inspect

    from app.blueprints import login_routes

    source = inspect.getsource(login_routes.logout)

    assert "WWW-Authenticate" in source
    assert "Authorization" in source, (
        "the same answer is given to both kinds of caller - one of them is wrong")
