# -*- coding: utf-8 -*-
"""One silent connection does not stop the self-signed panel from answering.

THE FINDING (audit 2026-09-26). In DDC_TLS_MODE=self-signed the server looks at
each new connection first - peek one byte, then TLS handshake or a redirect -
and it did that inside `get_request`, which socketserver runs on its ONE
accepting thread. Only the request after it got a thread of its own. The peek
had no timeout, so a client that opened a TCP connection and sent nothing (or
began a handshake and stalled) held the accept loop, and no other connection
was accepted: the panel was down for everyone until that socket closed.

THE CONTRACT: the look at a connection happens on that connection's own
thread, under a timeout. A silent client costs one thread, not the panel.

HOW THIS TEST CAN FAIL: a real HTTPS request that does not get its answer
while another client sits silent on the port.

COUNTER-CHECK (2026-09-26): red before the fix - the HTTPS request timed out
after 5 s behind the silent connection. Green after, and the plain-HTTP
redirect (test_plain_http_is_sent_on_to_https.py) still holds.
"""

import socket
import ssl
import threading
import urllib.request

import pytest


@pytest.fixture
def running_panel(tmp_path):
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


def _https_health(port):
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(f"https://127.0.0.1:{port}/health",
                                context=context, timeout=5) as answer:
        return answer.status, answer.read()


def test_a_silent_client_does_not_hold_the_door(running_panel):
    silent = socket.create_connection(("127.0.0.1", running_panel), timeout=30)
    try:
        assert _https_health(running_panel) == (200, b"ok")
    finally:
        silent.close()


def test_a_stalled_handshake_does_not_hold_the_door(running_panel):
    """The first byte of a TLS record (0x16) and then nothing: the server
    starts a handshake that never completes."""
    stalled = socket.create_connection(("127.0.0.1", running_panel), timeout=30)
    stalled.sendall(b"\x16")
    try:
        assert _https_health(running_panel) == (200, b"ok")
    finally:
        stalled.close()
