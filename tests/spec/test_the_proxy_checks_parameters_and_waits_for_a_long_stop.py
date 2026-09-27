# -*- coding: utf-8 -*-
"""The proxy checks query parameters, waits as long as a stop may take, and is bounded.

THREE FINDINGS of the adversarial review of 2026-09-27:

1. A STOP THAT TAKES LONGER THAN 120 S CAME BACK AS 502. The proxy read the
   daemon with a 120 s timeout, and dockerd answers a stop only when the
   container is down. DDC passes a container's own StopTimeout as ``t``
   (docker_action_service.py), so a database with StopTimeout=180 was
   reported as failed while it was still stopping - the bug
   group_actions.py describes, brought back by the proxy.
2. THE QUERY STRING WAS NEVER CHECKED - only the path. ``start?checkpoint=``
   is a restore from a checkpoint on an experimental daemon, and
   ``stop?signal=`` changes what a stop is. Each endpoint now takes exactly the
   parameters docker-py sends for DDC's calls, and nothing else; a ";" (which
   Go and Python split differently) is refused outright.
3. EVERY CONNECTION GOT A THREAD AND A HEAD COULD TRICKLE IN FOREVER. Now the
   concurrent connections are bounded and the request head has a deadline.

COUNTER-CHECK (2026-09-27): red before - the long stop got 502, the
checkpoint and signal parameters passed, the extra connection was served and
the trickling head was held.
"""

import contextlib
import os
import socket
import tempfile
import threading
import time

import pytest

from services.docker_proxy import allowlist_proxy
from services.docker_proxy.allowlist_proxy import is_allowed, serve


@pytest.mark.parametrize("target", [
    "/v1.44/containers/json?all=1&limit=-1&size=0&trunc_cmd=0",
    "/v1.44/containers/json?filters=%7B%22status%22%3A+%5B%22running%22%5D%7D",
    "/v1.44/containers/web/logs?stderr=1&stdout=1&timestamps=0&follow=0&tail=100",
    "/v1.44/containers/web/stats?stream=0&one-shot=0",
    "/v1.44/containers/web/json",
    "/v1.44/version",
])
def test_what_docker_py_sends_for_ddc_still_passes(target):
    assert is_allowed("GET", target), target


@pytest.mark.parametrize("target", [
    "/v1.44/containers/web/stop?t=180",
    "/v1.44/containers/web/restart?t=30",
    "/v1.44/containers/web/start",
])
def test_the_actions_with_their_own_parameters_pass(target):
    assert is_allowed("POST", target), target


@pytest.mark.parametrize("method, target", [
    ("POST", "/v1.44/containers/web/start?checkpoint=x&checkpoint-dir=/tmp"),
    ("POST", "/v1.44/containers/web/start?detachKeys=ctrl-p"),
    ("POST", "/v1.44/containers/web/stop?signal=SIGKILL"),
    ("GET", "/v1.44/containers/json?all=1;size=1"),
    ("GET", "/v1.44/containers/web/json?size=1&unknown=1"),
    ("GET", "/v1.44/images/nginx:latest/json?anything=1"),
    ("GET", "/_ping?x=1"),
])
def test_a_parameter_an_endpoint_does_not_take_is_refused(method, target):
    assert not is_allowed(method, target), target


@contextlib.contextmanager
def _slow_daemon(delay):
    """Answers a request only after `delay` seconds - like dockerd on a slow stop."""
    workdir = tempfile.mkdtemp()
    path = os.path.join(workdir, "d.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(4)

    def answer(conn):
        conn.recv(65536)
        time.sleep(delay)
        conn.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
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
def _proxy(upstream):
    proxy_path = os.path.join(tempfile.mkdtemp(), "p.sock")
    proxy = serve(proxy_path, upstream)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        yield proxy_path
    finally:
        proxy.shutdown()
        proxy.server_close()


def _ask(proxy_path, request, timeout=10):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    conn.connect(proxy_path)
    conn.sendall(request)
    data = b""
    try:
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
    except OSError:
        pass
    conn.close()
    return data


def test_a_stop_longer_than_the_idle_timeout_is_waited_for(monkeypatch):
    monkeypatch.setattr(allowlist_proxy, "IDLE_TIMEOUT_SECONDS", 1)
    with _slow_daemon(2.5) as daemon, _proxy(daemon) as proxy:
        answer = _ask(proxy, b"POST /v1.44/containers/db/stop?t=3 HTTP/1.1\r\nHost: d\r\n"
                             b"Content-Length: 0\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 204"), f"the long stop came back as {answer[:40]!r}"


def test_a_read_still_times_out(monkeypatch):
    """The long wait is for stop and restart only - a hanging read is still cut."""
    monkeypatch.setattr(allowlist_proxy, "IDLE_TIMEOUT_SECONDS", 1)
    with _slow_daemon(2.5) as daemon, _proxy(daemon) as proxy:
        answer = _ask(proxy, b"GET /v1.44/containers/json HTTP/1.1\r\nHost: d\r\n\r\n")
    assert answer.startswith(b"HTTP/1.1 502"), answer[:40]


def test_connections_are_bounded(monkeypatch):
    monkeypatch.setattr(allowlist_proxy, "MAX_CONNECTIONS", 2)
    with _slow_daemon(0) as daemon, _proxy(daemon) as proxy:
        holders = []
        for _ in range(2):
            held = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            held.connect(proxy)
            held.sendall(b"GET /v1.44/containers/json HTTP/1.1\r\n")  # a head that never ends
            holders.append(held)
        time.sleep(0.3)
        answer = _ask(proxy, b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n", timeout=5)
        for held in holders:
            held.close()
    assert answer.startswith(b"HTTP/1.1 503"), f"a third connection was served: {answer[:40]!r}"


def test_a_trickling_head_is_cut_off(monkeypatch):
    monkeypatch.setattr(allowlist_proxy, "HEAD_DEADLINE_SECONDS", 1)
    with _slow_daemon(0) as daemon, _proxy(daemon) as proxy:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(5)
        conn.connect(proxy)
        started = time.monotonic()
        closed = False
        for byte in b"GET /v1.44/containers/json HTTP/1.1\r\nHost: d\r\nX-Slow: yes\r\n\r\n":
            try:
                conn.sendall(bytes([byte]))
            except OSError:
                closed = True
                break
            time.sleep(0.1)
            if time.monotonic() - started > 3:
                break
        try:
            rest = conn.recv(65536)
        except OSError:
            rest = b""
        conn.close()
    assert closed or not rest.startswith(b"HTTP/1.1 200"), "a head trickled in for seconds and was served"
