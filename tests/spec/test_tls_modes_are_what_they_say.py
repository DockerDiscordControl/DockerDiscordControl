# -*- coding: utf-8 -*-
"""The TLS mode the operator chose is the one DDC runs (v3.0 step 8, V3 §5.1).

Operator decision 2026-09-22: TLS both ways - a reverse proxy is the
recommended way, a self-signed certificate the fallback - and 2FA only over
TLS. ``DDC_TLS_MODE`` selects it:

* ``off`` (default) - plain HTTP on the LAN, exactly as before v3.0; the
  session cookie is not ``Secure`` (a Secure cookie is never sent over HTTP).
* ``proxy`` - TLS ends at the operator's reverse proxy. The cookie is
  ``Secure``, and a request that did not come through a trusted proxy over
  HTTPS is refused - otherwise the proxy would be optional and "2FA only over
  TLS" would hold only for whoever happens to use it. ``/health`` stays open
  for the container healthcheck.
* ``self-signed`` - DDC serves HTTPS itself with a certificate it creates in
  ``config/tls`` and renews before it expires; the fingerprint is logged for
  the trust step.

An unknown value stops the start with a clear message: silently falling back
to plain HTTP when the operator asked for TLS is the failure nobody notices.

COUNTER-CHECK (2026-09-22): written before app/web/tls.py existed (import
error, no proof on its own). The first real run passed direct plain requests
for a reason that was the test's own: Flask's test client had silently used
https (PREFERRED_URL_SCHEME). With the scheme stated, the guard was checked by
breaking it - reading X-Forwarded-Proto itself instead of the trust-list
result lets the forged header through, and that test went red.
"""

import datetime
import os
import ssl
import threading
import urllib.request

import pytest
from flask import Flask


def test_off_is_the_default_and_changes_nothing():
    from app.web.tls import tls_mode

    assert tls_mode({}) == "off"
    assert tls_mode({"DDC_TLS_MODE": " Proxy "}) == "proxy"


def test_an_unknown_mode_stops_the_start():
    from app.web.tls import tls_mode

    with pytest.raises(ValueError, match="DDC_TLS_MODE"):
        tls_mode({"DDC_TLS_MODE": "https"})


def _app(mode, monkeypatch, trusted=None):
    from app.web.extensions import configure_proxy
    from app.web.tls import apply_tls_mode

    if trusted:
        monkeypatch.setenv("DDC_TRUSTED_PROXIES", trusted)
    else:
        monkeypatch.delenv("DDC_TRUSTED_PROXIES", raising=False)
    app = Flask("t")
    configure_proxy(app)
    apply_tls_mode(app, mode)

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/")
    def index():
        return "panel"

    return app


def test_off_keeps_the_cookie_plain(monkeypatch):
    app = _app("off", monkeypatch)
    assert app.config.get("SESSION_COOKIE_SECURE") in (None, False)
    assert app.test_client().get("/").status_code == 200


def test_proxy_mode_makes_the_cookie_secure(monkeypatch):
    app = _app("proxy", monkeypatch, trusted="10.0.0.2")
    assert app.config["SESSION_COOKIE_SECURE"] is True


# Every request below states base_url=PLAIN: Flask's test client builds its
# URLs from PREFERRED_URL_SCHEME, which the proxy mode sets to https - the
# first run of these tests sent https without saying so and passed a direct
# plain request that a real server would have delivered as http.
PLAIN = "http://localhost"


def test_proxy_mode_refuses_plain_direct_access_but_not_health(monkeypatch):
    client = _app("proxy", monkeypatch, trusted="10.0.0.2").test_client()
    direct = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.get("/", base_url=PLAIN, environ_base=direct).status_code == 403
    assert client.get("/health", base_url=PLAIN, environ_base=direct).status_code == 200


def test_proxy_mode_does_not_believe_a_forged_https_header(monkeypatch):
    client = _app("proxy", monkeypatch, trusted="10.0.0.2").test_client()
    forged = client.get("/", base_url=PLAIN, headers={"X-Forwarded-Proto": "https"}, environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert forged.status_code == 403


def test_proxy_mode_serves_what_came_through_the_proxy_over_https(monkeypatch):
    client = _app("proxy", monkeypatch, trusted="10.0.0.2").test_client()
    via_proxy = client.get(
        "/", base_url=PLAIN, headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "192.168.1.50"},
        environ_base={"REMOTE_ADDR": "10.0.0.2"},
    )
    assert via_proxy.status_code == 200


def test_the_certificate_is_created_once_and_kept(tmp_path):
    from app.web.tls import ensure_self_signed_certificate

    first = ensure_self_signed_certificate(tmp_path)
    assert first.created and first.cert_path.is_file() and first.key_path.is_file()
    assert oct(os.stat(first.key_path).st_mode & 0o777) == "0o600"
    second = ensure_self_signed_certificate(tmp_path)
    assert not second.created and second.fingerprint == first.fingerprint


def test_a_certificate_close_to_expiry_is_renewed(tmp_path):
    from app.web.tls import ensure_self_signed_certificate

    first = ensure_self_signed_certificate(tmp_path)
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=800)
    renewed = ensure_self_signed_certificate(tmp_path, now=later)
    assert renewed.created and renewed.fingerprint != first.fingerprint


def test_self_signed_mode_really_serves_https(tmp_path, monkeypatch):
    from app.web.tls import ensure_self_signed_certificate, make_tls_server

    app = _app("self-signed", monkeypatch)
    cert = ensure_self_signed_certificate(tmp_path)
    server = make_tls_server(app, "127.0.0.1", 0, cert)
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        context = ssl.create_default_context(cafile=str(cert.cert_path))
        context.check_hostname = False
        with urllib.request.urlopen(f"https://127.0.0.1:{port}/health", context=context, timeout=5) as answer:
            assert answer.read() == b"ok"
    finally:
        server.shutdown()
    assert app.config["SESSION_COOKIE_SECURE"] is True


# The call sites (stage-3 check c): a correct tls module that create_app or
# run.py never calls would leave every installation on plain HTTP.

def test_create_app_applies_the_mode(monkeypatch):
    from app.web import create_app

    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_TLS_MODE", "proxy")
    monkeypatch.setenv("DDC_TRUSTED_PROXIES", "10.0.0.2")
    app = create_app({"TESTING": True})
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.test_client().get("/", base_url=PLAIN, environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 403


def test_create_app_refuses_an_unknown_mode(monkeypatch):
    from app.web import create_app

    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_TLS_MODE", "https")
    with pytest.raises(ValueError, match="DDC_TLS_MODE"):
        create_app({"TESTING": True})


class _FakeServer:
    served = False

    def serve_forever(self):
        _FakeServer.served = True


def test_run_serves_https_in_self_signed_mode(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    import run as run_module
    import app.web.tls as tls

    monkeypatch.setenv("DDC_TLS_MODE", "self-signed")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    waitress = MagicMock()
    monkeypatch.setattr(run_module, "serve", waitress)
    made = MagicMock(return_value=_FakeServer())
    monkeypatch.setattr(tls, "make_tls_server", made)

    # A Flask app, not object(): _serve_web now also installs a before_request
    # hook that teaches the certificate the address each request was aimed at
    # (2026-09-25). A stand-in that cannot do what the real thing does is how a
    # test passes while the code is broken.
    from flask import Flask

    run_module._serve_web(Flask(__name__), 9374, 4)

    waitress.assert_not_called()
    assert made.called and _FakeServer.served
    assert (tmp_path / "tls" / "ddc.crt").is_file()


def test_run_keeps_waitress_when_tls_is_off(monkeypatch):
    from unittest.mock import MagicMock

    import run as run_module

    monkeypatch.delenv("DDC_TLS_MODE", raising=False)
    waitress = MagicMock()
    monkeypatch.setattr(run_module, "serve", waitress)
    # A Flask app, not object(): _serve_web now also installs a before_request
    # hook that teaches the certificate the address each request was aimed at
    # (2026-09-25). A stand-in that cannot do what the real thing does is how a
    # test passes while the code is broken.
    from flask import Flask

    run_module._serve_web(Flask(__name__), 9374, 4)
    assert waitress.call_args.kwargs["port"] == 9374


def test_the_healthcheck_follows_the_tls_mode():
    """In self-signed mode DDC answers only HTTPS; a healthcheck that keeps
    asking http:// would mark every such container unhealthy."""
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    check = dockerfile[dockerfile.index("HEALTHCHECK"):dockerfile.index("ENTRYPOINT")]
    assert "DDC_TLS_MODE" in check and "'https'" in check, check


# --------------------------------------------------------------------------- #
# proxy mode without a trust list: the start stops, instead of a panel that
# refuses every request while the healthcheck reports it healthy
# --------------------------------------------------------------------------- #


def test_proxy_mode_without_a_trust_list_stops_the_start(monkeypatch):
    """THE FINDING: request.scheme can only become https when TrustedProxyFix
    believes a peer, and it believes nobody without DDC_TRUSTED_PROXIES. So
    DDC_TLS_MODE=proxy alone answered 403 to every path but /health - and
    /health kept answering 200, so Docker reported the container healthy while
    the panel was unusable. The operator, who IS coming through their proxy,
    reads "open it through your reverse proxy over HTTPS".

    COUNTER-CHECK (2026-09-22): red before - the app started and the panel
    answered 403; the test below pins that a trust list still starts.
    """
    from app.web.extensions import configure_proxy
    from app.web.tls import apply_tls_mode

    monkeypatch.delenv("DDC_TRUSTED_PROXIES", raising=False)
    app = Flask("t")
    configure_proxy(app)

    with pytest.raises(ValueError, match="DDC_TRUSTED_PROXIES"):
        apply_tls_mode(app, "proxy")


def test_proxy_mode_with_a_trust_list_starts(monkeypatch):
    """Counter-check: the working setup must not be refused."""
    app = _app("proxy", monkeypatch, trusted="10.0.0.2")
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_self_signed_needs_no_trust_list(monkeypatch):
    """Counter-check, the other mode: DDC terminates TLS itself there."""
    app = _app("self-signed", monkeypatch)
    assert app.config["SESSION_COOKIE_SECURE"] is True
