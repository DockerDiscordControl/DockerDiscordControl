# -*- coding: utf-8 -*-
"""With 2FA on, the panel answers only over HTTPS - the code and the marker too.

THE FINDING: /security/2fa/setup and /confirm refuse a plain HTTP request,
but /verify did not, and the session cookie is marked Secure only for
DDC_TLS_MODE=proxy or self-signed. With the default mode off, a TLS
terminating reverse proxy and DDC_TRUSTED_PROXIES set - no misconfiguration,
just the setup the README describes for the action log - request.is_secure is
True, so 2FA can be switched on; but the browser then also sends the session
cookie over the plain LAN port, and that cookie IS the passed second factor.
Whoever reads it on the LAN is inside, without ever seeing a code. Posting
the code itself over plain HTTP was accepted as well.

So: once 2FA is enabled, every panel request that did not arrive over HTTPS
is refused with a line that says why (the healthcheck and the static files
still answer), and the session cookie is Secure. Nothing changes for an
installation without 2FA - it is offered, never forced.

COUNTER-CHECK (2026-09-22): red before - the plain-HTTP verify was accepted
and the cookie carried no Secure flag; the "without 2FA nothing changes" test
goes red if the refusal is not tied to the enabled state.
"""

from tests.spec.test_the_panel_asks_for_the_second_factor import (  # noqa: F401 - fixtures
    PLAIN, _basic, _current_code, _enable, panel)

SECURE = "https://localhost"


def test_the_panel_over_plain_http_is_refused_once_2fa_is_on(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()

    answer = client.get("/__panel", headers=_basic(), base_url=PLAIN)

    assert answer.status_code == 403
    assert b"HTTPS" in answer.data


def test_the_code_cannot_be_posted_over_plain_http(panel):
    app, store = panel
    _enable(store)
    client = app.test_client()

    answer = client.post("/security/2fa/verify", headers=_basic(), base_url=PLAIN,
                         data={"code": _current_code(store)})

    assert answer.status_code == 403
    assert "two_factor_ok" not in str(answer.headers)


def test_the_session_cookie_is_secure_once_2fa_is_on(panel):
    """The cookie IS the passed second factor, so it must never leave over HTTP."""
    app, store = panel
    _enable(store)
    client = app.test_client()

    answer = client.post("/security/2fa/verify", headers=_basic(), base_url=SECURE,
                         data={"code": _current_code(store)})

    cookies = [value for name, value in answer.headers if name == "Set-Cookie"]
    assert cookies and all("Secure" in cookie for cookie in cookies), cookies


def test_without_2fa_plain_http_is_untouched(panel):
    """Counter-check: 2FA is offered, never forced - and nothing else changes."""
    app, _store = panel

    answer = app.test_client().get("/__panel", headers=_basic(), base_url=PLAIN)

    assert answer.status_code == 200
    assert b"panel" in answer.data


def test_the_healthcheck_still_answers_in_the_clear(panel):
    app, store = panel
    _enable(store)

    assert app.test_client().get("/health", base_url=PLAIN).status_code in (200, 503)


def test_over_https_everything_works_as_before(panel):
    """Counter-check, the other side: the code is accepted over HTTPS."""
    app, store = panel
    _enable(store)
    client = app.test_client()

    answer = client.post("/security/2fa/verify", headers=_basic(), base_url=SECURE,
                         data={"code": _current_code(store)}, follow_redirects=False)

    assert answer.status_code in (302, 303)
    assert client.get("/__panel", headers=_basic(), base_url=SECURE).status_code == 200
