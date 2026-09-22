# -*- coding: utf-8 -*-
"""/health names the path DDC really takes, and reads the answer whole.

Two in the reachability check behind /health:

* whether DDC goes through the proxy was decided by comparing DOCKER_HOST
  with one exact string. "unix://localhost/run/ddc-proxy/docker.sock" - the
  spelling with an (ignored) host part that docker-py accepts - or a trailing
  slash reported "direct", so a dead proxy was called "docker unreachable"
  and sent the operator to the host instead of to DDC. The socket PATH
  decides now;
* the status line was taken from a single recv(64). A daemon that sends the
  line in two pieces gave parts[1] == b"" -> 0 -> "error" for a healthy
  Docker. The line is read until it is complete.

COUNTER-CHECK (2026-09-22): red before - the two spellings said "direct" and
the split answer said "error".
"""

import os
import socket
import tempfile
import threading

import pytest

from services.docker_service.reachability import PROXY_SOCKET, docker_reachability


@pytest.mark.parametrize("host", [
    f"unix://{PROXY_SOCKET}",
    f"unix://localhost{PROXY_SOCKET}",
    f"unix://{PROXY_SOCKET}/",
])
def test_every_spelling_of_the_proxy_socket_is_the_proxy(host):
    assert docker_reachability(host, timeout=0.2)["path"] == "proxy"


def test_another_socket_is_still_direct():
    """Counter-check: the raw socket must not be called the proxy."""
    assert docker_reachability("unix:///var/run/docker.sock", timeout=0.2)["path"] == "direct"


def _serving(reply_chunks):
    workdir = tempfile.mkdtemp()
    path = os.path.join(workdir, "d.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(2)

    def run():
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            conn.recv(4096)
            import time

            for chunk in reply_chunks:
                conn.sendall(chunk)
                time.sleep(0.05)

    threading.Thread(target=run, daemon=True).start()
    return path, server


def test_a_status_line_that_arrives_in_pieces_is_read_whole():
    path, server = _serving([b"HTTP/1.1 ", b"200 OK\r\nContent-Length: 2\r\n\r\nOK"])
    try:
        assert docker_reachability(f"unix://{path}", proxied=False, timeout=2)["state"] == "ok"
    finally:
        server.close()


def test_a_daemon_that_says_500_is_an_error():
    """Counter-check: reading more must not turn every answer into 'ok'."""
    path, server = _serving([b"HTTP/1.1 500 Internal Server Error\r\n\r\n"])
    try:
        assert docker_reachability(f"unix://{path}", proxied=False, timeout=2)["state"] == "error"
    finally:
        server.close()
