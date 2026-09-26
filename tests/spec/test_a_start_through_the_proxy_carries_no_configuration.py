# -*- coding: utf-8 -*-
"""A start, stop or restart through the proxy carries no configuration.

THE FINDING (audit 2026-09-26). The allowlist let `POST containers/<name>/start`
through with any `v<N>.<M>/` prefix and a body of up to 64 KB. Docker before
25 serves API versions down to 1.12 by default, and below 1.24 its start
handler decodes the body as a HostConfig and applies it to the container:
`{"Privileged": true, "Binds": ["/:/host"]}` on
`POST /v1.23/containers/X/start` is the same host-root escape as
`POST /containers/create`, which V3 §4 says cannot be reached by
construction. The operator's own host runs Docker 29 (minimum API 1.40) and
was never exposed; the plan names Docker older than 25 as an audience on
purpose (the reason the client negotiates its version at all).

THE CONTRACT, two locks, each of which closes it alone:
  * no request through the proxy carries a body - nothing DDC sends has one
    (docker-py posts start/stop/restart with Content-Length: 0);
  * no path names an API version below 1.24, the first one whose start
    ignores a body.

HOW THIS TEST CAN FAIL: a body reaches the daemon, or an old version prefix
passes the allowlist.

COUNTER-CHECK (2026-09-26): red before the fix - the daemon received the
HostConfig body on /v1.23/.../start, and is_allowed said yes to /v1.12/ and
/v1.23/. Green after. The Content-Length: 0 case and a real docker-py client
(test_the_docker_proxy_lets_through_only_what_ddc_needs.py) stay green: DDC's
own requests still pass.
"""

import contextlib
import os
import socket
import tempfile
import threading

import pytest

from services.docker_proxy.allowlist_proxy import is_allowed, serve

HOST_CONFIG = b'{"Privileged":true,"Binds":["/:/host"]}'


@contextlib.contextmanager
def _daemon():
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
            seen.append(conn.recv(65536))
            conn.sendall(b"HTTP/1.1 204 No Content\r\n\r\n")
            conn.close()

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


def _talk(proxy_path, request):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(10)
    conn.connect(proxy_path)
    with conn:
        conn.sendall(request)
        answer = b""
        with contextlib.suppress(OSError):
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                answer += chunk
    return answer


def _post(path, body):
    return (f"POST {path} HTTP/1.1\r\nHost: docker\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode() + body


@pytest.mark.parametrize("path", ["/v1.23/containers/web/start",
                                  "/v1.44/containers/web/start",
                                  "/containers/web/restart"])
def test_a_body_never_reaches_the_daemon(path):
    with _daemon() as (daemon_path, seen), _proxy(daemon_path) as proxy_path:
        answer = _talk(proxy_path, _post(path, HOST_CONFIG))

    assert answer.startswith(b"HTTP/1.1 403"), answer[:60]
    assert not any(b"Privileged" in request for request in seen), seen


def test_ddc_s_own_empty_start_still_passes():
    """Counter-case: docker-py sends Content-Length: 0 on every start."""
    with _daemon() as (daemon_path, seen), _proxy(daemon_path) as proxy_path:
        answer = _talk(proxy_path, _post("/v1.44/containers/web/start", b""))

    assert answer.startswith(b"HTTP/1.1 204"), answer[:60]
    assert len(seen) == 1


@pytest.mark.parametrize("version", ["v1.12", "v1.19", "v1.23", "v0.99"])
def test_an_api_version_that_reads_a_start_body_is_refused(version):
    assert not is_allowed("POST", f"/{version}/containers/web/start")
    assert not is_allowed("GET", f"/{version}/containers/json")


@pytest.mark.parametrize("version", ["v1.24", "v1.40", "v1.43", "v1.44", "v1.54", "v2.0"])
def test_the_versions_ddc_negotiates_still_pass(version):
    assert is_allowed("POST", f"/{version}/containers/web/start")
    assert is_allowed("GET", f"/{version}/containers/json")
