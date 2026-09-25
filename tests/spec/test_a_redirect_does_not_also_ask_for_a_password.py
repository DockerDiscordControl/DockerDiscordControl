# -*- coding: utf-8 -*-
"""The way to the login form must not also be an HTTP Basic challenge.

THE OPERATOR, 2026-09-25: "when I click 'Back to the panel' I am logged out."

WHAT THE PANEL ACTUALLY ANSWERED, measured on the running container::

    $ curl -skI https://localhost:9374/security/2fa
    HTTP/1.1 302 FOUND
    Location: /login?next=/security/2fa
    WWW-Authenticate: Basic realm="Authentication Required"

TWO ANSWERS IN ONE RESPONSE, and they say different things. "Go to the form"
and "send me a password the browser's own way" cannot both be followed, so the
browser picks - and a browser that has Basic credentials for this host picks
Basic every time. It never reaches the form.

THAT IS WHERE THE LOGOUT COMES FROM. Credentials answered to a challenge are
replayed only for paths at or below the one that asked. His came from
``/security/2fa``, so they were sent for the second-factor pages and for
nothing else: he was logged in on that page and logged out the moment he
clicked back to ``/``. The live log of 26/Sep 00:13 has the whole shape - a
401 on /security/2fa, then the same path again with credentials, then ``GET /``
with an empty user name and off to the login form.

WHERE IT COMES FROM: flask_httpauth adds WWW-Authenticate to whatever its error
handler returns, unless the header is already there (HTTPAuth.error_handler).
DDC's handler answers a browser with a redirect, and the header was put on top
of it. Nobody wrote the line; it was inherited.

A CHALLENGE IS STILL RIGHT WHERE IT IS AN ANSWER: the 401 that a fetch() or a
script gets, and the fresh realm /logout uses to make a browser drop what it
cached, both keep theirs. Only a redirect - which is already a complete
instruction - stops carrying one.

HOW THIS TEST CAN FAIL: a 3xx answer that also asks for HTTP Basic.

COUNTER-CHECK (2026-09-26): red before - the 302 carried the challenge.
"""

import base64

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
    from app.auth import auth, auth_limiter, clear_credential_cache, setup_limiter
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD)
    stubbed = {"web_ui_user": "admin", "web_ui_password_hash": hashed}
    # BOTH NAMES. auth.py binds load_config at import; auth_error imports it
    # again inside the function, so a stub on one of them leaves the other
    # reading the empty temporary config - and the handler then answers "First
    # Time Setup Required", which is not the answer this file is about.
    monkeypatch.setattr(auth_module, "load_config", lambda: dict(stubbed))
    monkeypatch.setattr("services.config.config_service.load_config",
                        lambda *a, **k: dict(stubbed))
    for limiter in (auth_limiter, setup_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    @app.route("/__panel")
    @auth.login_required
    def _panel():
        return "panel"

    @app.route("/api/__thing")
    @auth.login_required
    def _thing():
        return {"ok": True}

    yield app

    for limiter in (auth_limiter, setup_limiter):
        limiter.ip_dict.clear()


def test_the_way_to_the_login_form_does_not_also_ask_for_basic(panel):
    """THE FINDING: one response, two answers, and the browser takes the one
    that leaves it logged in for a single path."""
    answer = panel.test_client().get("/__panel", base_url=SECURE)

    assert answer.status_code == 302, answer.status_code
    assert "/login" in answer.headers["Location"], answer.headers["Location"]
    assert "WWW-Authenticate" not in answer.headers, (
        "the redirect to the login form also challenges for HTTP Basic, so a "
        "browser holding credentials answers that instead of following it - "
        f"{answer.headers['WWW-Authenticate']}")


def test_a_caller_that_reads_json_still_gets_the_challenge(panel):
    """THE OPPOSITE MISTAKE. A 401 is where a challenge belongs: it is the
    whole answer, and a script has nothing else to go on."""
    answer = panel.test_client().get("/api/__thing", base_url=SECURE)

    assert answer.status_code == 401, answer.status_code
    assert "WWW-Authenticate" in answer.headers, (
        "a JSON caller was refused with no way to say who it is")


def test_the_way_out_still_makes_a_browser_drop_what_it_cached(panel):
    """/logout answers a Basic caller with 401 and a FRESH realm on purpose -
    the only portable way to make a browser forget. It is a 401, so nothing
    here touches it."""
    token = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
    answer = panel.test_client().get("/logout", base_url=SECURE,
                                     headers={"Authorization": f"Basic {token}"})

    assert answer.status_code == 401, answer.status_code
    assert "DDC-logout-" in answer.headers.get("WWW-Authenticate", ""), \
        answer.headers.get("WWW-Authenticate")


def test_a_page_that_is_open_is_not_touched(panel):
    """The counter-check that the rule was aimed and not sprayed: an ordinary
    answer carries no challenge either way, and must still be an answer."""
    answer = panel.test_client().get("/login", base_url=SECURE)

    assert answer.status_code == 200
    assert "WWW-Authenticate" not in answer.headers


def test_a_correct_login_is_still_redirected(panel):
    """And the ordinary redirect - the one a finished login produces - goes
    on working."""
    client = panel.test_client()
    answer = client.post("/login", base_url=SECURE,
                         data={"username": "admin", "password": PASSWORD, "next": "/__panel"})

    assert answer.status_code == 302
    assert answer.headers["Location"] == "/__panel"
    assert client.get("/__panel", base_url=SECURE).status_code == 200
