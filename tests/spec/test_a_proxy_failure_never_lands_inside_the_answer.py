# -*- coding: utf-8 -*-
"""A proxy failure never lands inside an answer that is already running.

Three in the allowlist proxy's failure handling:

* the relay loop wrote a complete "HTTP/1.1 502 Bad Gateway" response into
  the BODY of a response it had already started, when the daemon went quiet
  or the client went away in the middle. What the client reads is then one
  answer with a second answer glued inside it. The 502 belongs to a request
  that produced nothing yet;
* Content-Length was read with Python's int(), which accepts "-1", "+5" and
  "1_0" while Go's parser accepts none of them. With "-1" the size check
  passed, the read loop was skipped and the last byte was cut off the body -
  the proxy and the daemon disagreeing about a request, which is exactly what
  this file's smuggling tests exist to prevent;
* a client that announced a body and then went away raised out of the
  handler, so the container log got a socketserver traceback instead of a
  line saying what happened.

COUNTER-CHECK (2026-09-22): red before - the client saw "HTTP/1.1 502" after
the first bytes of a 200, "-1" was forwarded to the daemon, and the dead
client printed a traceback. The last test keeps the 502 for the case it is
for: nothing relayed yet.
"""

import contextlib
import os
import socket
import tempfile
import threading

import pytest

from services.docker_proxy import allowlist_proxy
from services.docker_proxy.allowlist_proxy import serve

REQUEST = b"GET /v1.44/containers/json HTTP/1.1\r\nHost: d\r\n\r\n"


@contextlib.contextmanager
def _upstream(behaviour):
    """A stand-in daemon that behaves badly in one particular way."""
    workdir = tempfile.mkdtemp()
    path = os.path.join(workdir, "d.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(4)
    seen = []

    def run():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=behaviour, args=(conn, seen), daemon=True).start()

    threading.Thread(target=run, daemon=True).start()
    try:
        yield path, seen
    finally:
        server.close()


@contextlib.contextmanager
def _proxy(upstream_path):
    workdir = tempfile.mkdtemp()
    proxy_path = os.path.join(workdir, "p.sock")
    proxy = serve(proxy_path, upstream_path)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        yield proxy_path
    finally:
        proxy.shutdown()
        proxy.server_close()


def _talk(proxy_path, request=REQUEST):
    with _connect(proxy_path) as conn:
        conn.sendall(request)
        answer = b""
        with contextlib.suppress(OSError):
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                answer += chunk
    return answer


def _connect(proxy_path):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(10)
    conn.connect(proxy_path)
    return conn


def test_a_daemon_that_stalls_mid_answer_does_not_get_a_second_answer(monkeypatch):
    monkeypatch.setattr(allowlist_proxy, "IDLE_TIMEOUT_SECONDS", 1)

    def stalls(conn, seen):
        seen.append(conn.recv(65536))
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n[{\"Id\":")
        import time

        time.sleep(3)  # longer than the idle timeout: the proxy's recv raises
        conn.close()

    with _upstream(stalls) as (daemon_path, _seen), _proxy(daemon_path) as proxy_path:
        with _connect(proxy_path) as conn:
            conn.sendall(REQUEST)
            answer = b""
            with contextlib.suppress(OSError):
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    answer += chunk

    assert answer.startswith(b"HTTP/1.1 200 OK"), answer[:40]
    assert b"502" not in answer, (
        f"a second answer was written into the first: {answer!r}")
    assert answer.count(b"HTTP/1.1") == 1, answer


# Not in this list: b" 5". Leading whitespace in a header value is legal HTTP
# (optional whitespace, trimmed by every reader including Go), so refusing it
# would break real clients.
# The last one is an Arabic-Indic "12": str.isdigit() says yes, Go says no.
@pytest.mark.parametrize("value", [b"-1", b"+5", b"1_0", b"0x5", b"5.0", "١٢".encode("utf-8")])
def test_a_content_length_go_would_refuse_is_refused_here(value):
    def answers(conn, seen):
        seen.append(conn.recv(65536))
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        conn.close()

    request = (b"POST /v1.44/containers/web/start HTTP/1.1\r\nHost: d\r\nContent-Length: "
               + value + b"\r\n\r\nXYZ")
    with _upstream(answers) as (daemon_path, seen), _proxy(daemon_path) as proxy_path:
        answer = _talk(proxy_path, request)

    assert answer.startswith(b"HTTP/1.1 400"), answer[:60]
    assert seen == [], f"the daemon saw the request anyway: {seen}"


def test_a_client_that_stops_mid_body_leaves_no_traceback(capfd, monkeypatch):
    monkeypatch.setattr(allowlist_proxy, "IDLE_TIMEOUT_SECONDS", 1)

    def answers(conn, seen):
        seen.append(conn.recv(65536))
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        conn.close()

    with _upstream(answers) as (daemon_path, _seen), _proxy(daemon_path) as proxy_path:
        conn = _connect(proxy_path)
        conn.sendall(b"POST /v1.44/containers/web/start HTTP/1.1\r\nHost: d\r\n"
                     b"Content-Length: 100\r\n\r\nonly-a-few")
        import time

        time.sleep(2)                     # promised 100 bytes, sends nothing more
        conn.close()
        # the proxy still serves the next client
        assert _talk(proxy_path, REQUEST).startswith(b"HTTP/1.1 200")

    assert "Traceback" not in capfd.readouterr().err


def test_an_unreachable_daemon_still_gets_its_502():
    """Counter-check: the 502 is right when nothing has been relayed."""
    workdir = tempfile.mkdtemp()
    with _proxy(os.path.join(workdir, "nothing.sock")) as proxy_path:
        answer = _talk(proxy_path, REQUEST)

    assert answer.startswith(b"HTTP/1.1 502"), answer[:60]
