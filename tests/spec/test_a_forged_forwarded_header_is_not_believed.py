# -*- coding: utf-8 -*-
"""A forwarded header is believed only when a configured proxy sent it.

THE FINDING (independent review 2026-09-22, Befund 3): ``app/web/extensions.py``
wrapped the app in ``ProxyFix(x_for=1, x_proto=1, x_host=1, x_port=1)``
unconditionally. ProxyFix does not check WHO sends the headers; it believes
the first hop. The login and setup rate limiters (``app/auth.py``) count by
``request.remote_addr``, which ProxyFix had already replaced with the
client's own ``X-Forwarded-For``. Anyone who reaches port 9374 directly
rotates that header and is never braked - 5 setup attempts per minute become
unlimited, during exactly the window in which ``admin/setup`` is the
bootstrap credential. The action log recorded the forged address too.

THE RULE NOW: the headers count only when the direct peer is on
``DDC_TRUSTED_PROXIES`` (comma-separated addresses or CIDR ranges). Without
the variable, no forwarded header is believed at all.

Checked through the real app and the real limiter, not through ProxyFix in
isolation - the defect was in the wiring (stage-3 check c: the call site).

COUNTER-CHECK (2026-09-22): written before the change. Red for the untrusted
cases (the probe saw the forged address and https; six setup attempts with
rotating headers were never refused), the trusted cases green already -
ProxyFix did that part. After the change all green. The trusted cases were then
checked by breaking them on purpose: a trust list that is parsed but never
consulted turned them red.
"""

import pytest
from flask import jsonify, request

PEER = "203.0.113.5"        # a client that reaches port 9374 directly
PROXY = "10.0.0.2"          # the operator's reverse proxy
CLIENT = "198.51.100.7"     # the real client behind that proxy


@pytest.fixture
def make_app(monkeypatch):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")

    def _make(trusted=None):
        if trusted is None:
            monkeypatch.delenv("DDC_TRUSTED_PROXIES", raising=False)
        else:
            monkeypatch.setenv("DDC_TRUSTED_PROXIES", trusted)

        from app.auth import setup_limiter
        from app.web import create_app

        setup_limiter.ip_dict.clear()
        app = create_app({"TESTING": True})

        @app.route("/__whoami")
        def _whoami():
            return jsonify(addr=request.remote_addr, scheme=request.scheme)

        return app

    yield _make

    from app.auth import setup_limiter
    setup_limiter.ip_dict.clear()


def _whoami(app, peer, **headers):
    response = app.test_client().get("/__whoami", headers=headers, environ_base={"REMOTE_ADDR": peer})
    return response.get_json()


def test_without_a_list_a_forged_address_is_not_believed(make_app):
    seen = _whoami(make_app(), PEER, **{"X-Forwarded-For": "192.0.2.99"})
    assert seen["addr"] == PEER


def test_without_a_list_a_forged_https_is_not_believed(make_app):
    seen = _whoami(make_app(), PEER, **{"X-Forwarded-Proto": "https"})
    assert seen["scheme"] == "http"


def test_a_peer_not_on_the_list_is_not_believed(make_app):
    seen = _whoami(make_app(trusted=PROXY), PEER, **{"X-Forwarded-For": "192.0.2.99"})
    assert seen["addr"] == PEER


def test_rotating_the_header_does_not_escape_the_setup_brake(make_app):
    """The limiter allows 5 setup requests per minute and address. A direct
    client that invents a new X-Forwarded-For each time must still be refused
    on the sixth."""
    client = make_app().test_client()
    codes = [
        client.get(
            "/setup",
            headers={"X-Forwarded-For": f"192.0.2.{n}"},
            environ_base={"REMOTE_ADDR": PEER},
        ).status_code
        for n in range(1, 7)
    ]
    assert codes[-1] == 429, codes


def test_the_configured_proxy_is_believed(make_app):
    seen = _whoami(
        make_app(trusted=PROXY), PROXY,
        **{"X-Forwarded-For": CLIENT, "X-Forwarded-Proto": "https"},
    )
    assert seen == {"addr": CLIENT, "scheme": "https"}


def test_a_proxy_inside_a_configured_range_is_believed(make_app):
    seen = _whoami(make_app(trusted="172.16.0.0/12, 10.9.9.9"), "172.18.0.4", **{"X-Forwarded-For": CLIENT})
    assert seen["addr"] == CLIENT


def test_an_unreadable_entry_is_reported_not_trusted(make_app, caplog):
    """A typo in the list must not widen trust, and must not pass in silence."""
    app = make_app(trusted="not-an-address, " + PROXY)
    assert "not-an-address" in caplog.text
    assert _whoami(app, PROXY, **{"X-Forwarded-For": CLIENT})["addr"] == CLIENT
    assert _whoami(app, PEER, **{"X-Forwarded-For": CLIENT})["addr"] == PEER
