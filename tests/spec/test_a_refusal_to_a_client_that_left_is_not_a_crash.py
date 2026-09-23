# -*- coding: utf-8 -*-
"""Refusing a request whose client already left is not a crash.

THE FINDING (first independent review, carried open until 2026-09-23): the
allowlist proxy answers a request it will not pass on by writing a short JSON
refusal. That write was unprotected. A client that asks for something forbidden
and hangs up without waiting - which is what a script, a timeout or a killed
container does - leaves the socket broken, conn.sendall raises, and the
exception travels out of handle().

socketserver then prints its own traceback. Under supervisord that goes to
stderr, which does not reach the log the operator reads (the same reason the
action logger was moved off stderr), so what is left is: a forbidden call was
made, and nothing in the log says so. The DENIED line is written before the
refusal, so it survives - but the traceback replaced the orderly end of the
request, and every such client produced one.

The 502 path had already been given a try/except for exactly this; the five
refusals in front of it had not. _refuse now swallows a broken pipe itself:
there is no one left to tell, and nothing else to do.

HOW THIS TEST CAN FAIL: it sends a forbidden request and closes the socket at
once, then asks whether the proxy's handler raised. If the refusal is
unprotected, the handler raises and the test is red.

COUNTER-CHECK (2026-09-23): red before - BrokenPipeError out of handle(). The
last two tests keep the refusal itself: a client that DOES wait still gets its
403, and an allowed request is still relayed.
"""

import contextlib
import os
import socket
import tempfile
import threading

import pytest

from services.docker_proxy import allowlist_proxy
from services.docker_proxy.allowlist_proxy import serve

FORBIDDEN = b"POST /v1.44/containers/create HTTP/1.1\r\nHost: d\r\n\r\n"
ALLOWED = b"GET /v1.44/containers/json HTTP/1.1\r\nHost: d\r\n\r\n"


@contextlib.contextmanager
def _upstream():
    """A stand-in daemon that answers anything that reaches it."""
    workdir = tempfile.mkdtemp()
    path = os.path.join(workdir, "d.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(4)

    def answer(conn):
        with contextlib.suppress(OSError):
            conn.recv(65536)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n[]")
        conn.close()

    def run():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=answer, args=(conn,), daemon=True).start()

    threading.Thread(target=run, daemon=True).start()
    try:
        yield path
    finally:
        server.close()


@contextlib.contextmanager
def _proxy(upstream_path):
    """The proxy, with every handler error remembered instead of printed."""
    workdir = tempfile.mkdtemp()
    proxy_path = os.path.join(workdir, "p.sock")
    proxy = serve(proxy_path, upstream_path)
    raised = []
    proxy.handle_error = lambda request, address: raised.append(
        __import__("sys").exc_info()[1])
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        yield proxy_path, raised
    finally:
        proxy.shutdown()
        proxy.server_close()


def _connect(proxy_path):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(10)
    conn.connect(proxy_path)
    return conn


def _settle():
    """Give the handler thread its turn before the assertions."""
    import time

    time.sleep(0.6)


def test_a_forbidden_request_from_a_client_that_left_does_not_raise():
    """The everyday shape of it: a script that asks and does not wait."""
    with _upstream() as daemon_path, _proxy(daemon_path) as (proxy_path, raised):
        conn = _connect(proxy_path)
        conn.sendall(FORBIDDEN)
        # Gone before the refusal can be written. SO_LINGER 0 makes the close a
        # reset, which is what a killed process leaves behind.
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        conn.close()
        _settle()

    assert raised == [], f"the refusal raised out of the handler: {raised}"


def test_a_malformed_request_from_a_client_that_left_does_not_raise():
    """The other unprotected refusal, reached before the allowlist."""
    with _upstream() as daemon_path, _proxy(daemon_path) as (proxy_path, raised):
        conn = _connect(proxy_path)
        conn.sendall(b"NOT-A-REQUEST\r\n\r\n")
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        conn.close()
        _settle()

    assert raised == [], f"the refusal raised out of the handler: {raised}"


def test_a_client_that_waits_still_gets_its_refusal():
    """Counter-check: the refusal is still written, and still says 403."""
    with _upstream() as daemon_path, _proxy(daemon_path) as (proxy_path, raised):
        with _connect(proxy_path) as conn:
            conn.sendall(FORBIDDEN)
            answer = b""
            with contextlib.suppress(OSError):
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    answer += chunk

    assert answer.startswith(b"HTTP/1.1 403 Forbidden"), answer[:60]
    assert b"endpoint not allowed" in answer
    assert raised == []


def test_an_allowed_request_is_still_relayed():
    """Counter-check: nothing about the ordinary path changed."""
    with _upstream() as daemon_path, _proxy(daemon_path) as (proxy_path, raised):
        with _connect(proxy_path) as conn:
            conn.sendall(ALLOWED)
            answer = b""
            with contextlib.suppress(OSError):
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    answer += chunk

    assert answer.startswith(b"HTTP/1.1 200 OK"), answer[:60]
    assert raised == []
