# -*- coding: utf-8 -*-
"""Typing http:// on the HTTPS port lands on the panel, not on an error.

THE OPERATOR ASKED (2026-09-25), right after choosing the self-signed mode:
"set up an automatic redirect from http to https."

WHY IT NEEDS MORE THAN A ROUTE. DDC listens on one port. werkzeug's TLS server
wraps the LISTENING socket, so a plain request dies in the handshake before any
Flask route sees it - the browser shows a connection error, and an operator with
an old bookmark thinks the panel is down. There is no HTTP request to answer
with a redirect, unless somebody looks first.

SO THE FIRST BYTE DECIDES. A TLS connection opens with the record type of a
ClientHello, 0x16 (RFC 8446 §5.1); every HTTP request opens with a method, so
with an ASCII letter. The listening socket stays plain, each connection is
peeked at, a TLS one is wrapped and handed on unchanged, and a plain one gets a
301 to the same address over HTTPS.

THE HOST HEADER IS THE ADDRESS, not a configured name. The panel is reached by
IP, by hostname, through Tailscale, through whatever resolves to it - a
redirect to a name the browser cannot resolve would be worse than none.

HOW THIS TEST CAN FAIL: a plain request getting no answer, a redirect to the
wrong host or scheme, or HTTPS itself breaking because the socket is no longer
wrapped.

COUNTER-CHECK (2026-09-25): red before - there was no redirect at all, and the
end-to-end case below got a connection reset instead of a 301.
"""

import socket
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture
def running_panel(tmp_path):
    """A real HTTPS server on a real port, with a real self-signed certificate."""
    from flask import Flask

    from app.web import tls

    app = Flask(__name__)

    @app.route("/health")
    def health():
        return "ok"

    certificate = tls.ensure_self_signed_certificate(tmp_path / "tls")
    server = tls.make_tls_server(app, "127.0.0.1", 0, certificate)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _plain_request(port, path="/health", host=None, http10=False):
    """Speak HTTP to the port by hand: urllib would refuse the mismatch."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        if http10:
            head = f"GET {path} HTTP/1.0\r\n\r\n"
        else:
            head = (f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host or f'127.0.0.1:{port}'}\r\n"
                    "Connection: close\r\n\r\n")
        sock.sendall(head.encode())
        answer = b""
        while len(answer) < 4096:
            chunk = sock.recv(1024)
            if not chunk:
                break
            answer += chunk
    return answer.decode("latin-1")


def test_https_still_works(running_panel):
    """Counter-check first: the peeking must not have broken the thing it
    protects. Without this, a server that redirected everything would pass
    every case below."""
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(f"https://127.0.0.1:{running_panel}/health",
                                context=context, timeout=10) as answer:

        assert answer.status == 200
        assert answer.read() == b"ok"


def test_a_plain_request_is_sent_on_to_https(running_panel):
    """THE REQUEST: an old http:// bookmark lands on the panel."""
    answer = _plain_request(running_panel)

    assert answer.startswith("HTTP/1.1 301"), answer[:80]
    assert f"Location: https://127.0.0.1:{running_panel}/health" in answer, answer[:200]


def test_the_path_is_kept(running_panel):
    """A link into the panel keeps pointing where it pointed."""
    answer = _plain_request(running_panel, path="/some/page?tab=logs")

    assert f"Location: https://127.0.0.1:{running_panel}/some/page?tab=logs" in answer


def test_the_host_the_browser_used_is_the_host_it_goes_to(running_panel):
    """Reached by name, it must not be sent to an address."""
    answer = _plain_request(running_panel, host=f"ddc.local:{running_panel}")

    assert f"Location: https://ddc.local:{running_panel}/health" in answer, answer[:200]


def test_a_request_without_a_host_is_told_rather_than_guessed_at(running_panel):
    """HTTP/1.0 without a Host: there is nowhere sensible to send it."""
    answer = _plain_request(running_panel, http10=True)

    assert answer.startswith("HTTP/1.1 400"), answer[:80]
    assert "https://" in answer


# --- the parts, without a socket ---------------------------------------------

def test_the_first_byte_tells_the_two_apart():
    from app.web.tls import looks_like_tls

    assert looks_like_tls(b"\x16") is True          # a ClientHello
    assert looks_like_tls(b"G") is False            # GET
    assert looks_like_tls(b"P") is False            # POST
    assert looks_like_tls(b"") is False             # a client that said nothing


@pytest.mark.parametrize("host,expected", [
    (b"192.168.1.249:9374", b"https://192.168.1.249:9374/"),
    (b"192.168.1.249", b"https://192.168.1.249:9374/"),
    (b"ddc.example:8080", b"https://ddc.example:9374/"),
    (b"[2001:db8::1]:9374", b"https://[2001:db8::1]:9374/"),
])
def test_the_port_is_ours_and_the_host_is_theirs(host, expected):
    """A client may send any port in Host - it reached US on ours."""
    from app.web.tls import redirect_to_https

    answer = redirect_to_https(b"GET / HTTP/1.1\r\nHost: " + host + b"\r\n\r\n", 9374)

    assert b"301" in answer
    assert b"Location: " + expected + b"\r\n" in answer, answer


def test_a_nonsense_request_does_not_crash_the_server():
    """Whatever arrives on an open port, the answer is an answer."""
    from app.web.tls import redirect_to_https

    for rubbish in (b"", b"\x00\x01\x02", b"GET", b"GET / HTTP/1.1\r\n\r\n"):
        answer = redirect_to_https(rubbish, 9374)

        assert answer.startswith(b"HTTP/1.1 "), rubbish
