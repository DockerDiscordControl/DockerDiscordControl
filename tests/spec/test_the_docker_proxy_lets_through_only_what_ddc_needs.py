# -*- coding: utf-8 -*-
"""The Docker proxy lets through exactly what DDC needs, and a real client works through it.

v3.0 claims "DDC's code cannot reach anything but the allowed endpoints". That
claim has two halves, and a test of only one of them is the test that cannot
fail:

* DDC must still WORK behind the proxy. The first draft of the allowlist (V3
  §4.2, before revision) listed the eight endpoints DDC's code calls and
  forgot the ``GET /version`` docker-py 7.1.0 sends on every client
  construction. Every endpoint test would have been green while DDC could not
  build a single client. So the first test here is a REAL ``docker.DockerClient``
  talking through the proxy - it is the only one that turns red when docker-py
  makes a call nobody wrote down.
* Everything else must be refused, and never reach the daemon.

The daemon behind the proxy is a small stand-in that answers every request
plausibly and records it. It is a stand-in on purpose: the test must not
start or stop real containers.

COUNTER-CHECK (2026-09-22): the proxy was first written with the first-draft
allowlist, without ``/version``. The end-to-end test went red at client
construction with docker-py's "Error while fetching server API version"
wrapping the proxy's 403 - exactly the failure V3 predicts. With ``/version``
added: green.
The ambiguous-request cases (bare LF/CR, a second Content-Length, junk after
the protocol version, HTTP/2.0) were red before the proxy validated its input.
The first run was green for the junk-after-version case for the wrong reason:
the stand-in daemon rejected it, not the proxy. The test now demands the
proxy's own refusal, and removing the request-line check turns it red.
"""

import threading

import pytest

from services.docker_proxy.allowlist_proxy import is_allowed, serve
from tests.spec.fake_dockerd import running_fake_dockerd


@pytest.fixture
def proxied():
    """(proxy socket path, list of requests the daemon saw)."""
    with running_fake_dockerd() as (workdir, daemon_path, seen):
        proxy = serve(f"{workdir}/p.sock", daemon_path)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        try:
            yield f"{workdir}/p.sock", seen
        finally:
            proxy.shutdown()
            proxy.server_close()


def test_a_real_docker_client_works_through_the_proxy(proxied):
    import docker

    proxy_path, seen = proxied
    client = docker.DockerClient(base_url=f"unix://{proxy_path}", timeout=5)
    try:
        assert client.ping() is True
        containers = client.containers.list()
        assert [c.name for c in containers] == ["web"]
        web = client.containers.get("web")
        assert b"hello from web" in web.logs(tail=10)
        assert isinstance(web.stats(stream=False), dict)
        web.start()
        web.stop(timeout=1)
        web.restart(timeout=1)
    finally:
        client.close()

    paths = {path.split("?", 1)[0].split("/", 2)[-1] if path.startswith("/v1") else path.split("?", 1)[0]
             for _, path in seen}
    assert "/version" in paths, "docker-py did not negotiate - then this test proves less than it claims"


def test_a_refused_request_never_reaches_the_daemon(proxied):
    import socket

    proxy_path, seen = proxied
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(proxy_path)
        body = b'{"Image": "alpine", "HostConfig": {"Privileged": true, "Binds": ["/:/host"]}}'
        conn.sendall(
            b"POST /v1.44/containers/create HTTP/1.1\r\nHost: docker\r\n"
            b"Content-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        answer = conn.recv(4096)
    assert answer.startswith(b"HTTP/1.1 403"), answer[:60]
    assert seen == [], f"the daemon saw a refused request: {seen}"


ALLOWED = [
    ("GET", "/_ping"), ("HEAD", "/_ping"), ("GET", "/v1.44/_ping"),
    ("GET", "/version"), ("GET", "/v1.44/version"),
    ("GET", "/v1.44/containers/json?all=1"),
    ("GET", "/v1.44/containers/web/json"),
    ("GET", "/v1.44/containers/abc123/logs?stdout=1&stderr=1&tail=10"),
    ("GET", "/v1.44/containers/web/stats?stream=0"),
    ("POST", "/v1.44/containers/web/start"),
    ("POST", "/v1.44/containers/web/stop?t=10"),
    ("POST", "/v1.44/containers/web/restart?t=10"),
    ("GET", "/v1.44/images/lscr.io/linuxserver/plex:latest/json"),
]

DENIED = [
    ("POST", "/v1.44/containers/create"),
    ("POST", "/v1.44/containers/web/exec"),
    ("POST", "/v1.44/exec/abc/start"),
    ("DELETE", "/v1.44/containers/web"),
    ("POST", "/v1.44/containers/web/kill"),
    ("POST", "/v1.44/containers/web/update"),
    ("POST", "/v1.44/containers/web/attach"),
    ("GET", "/v1.44/containers/web/archive?path=/etc"),
    ("PUT", "/v1.44/containers/web/archive?path=/"),
    ("GET", "/v1.44/containers/web/export"),
    ("GET", "/v1.44/info"),
    ("GET", "/v1.44/events"),
    ("POST", "/v1.44/images/create?fromImage=alpine"),
    ("POST", "/v1.44/build"),
    ("POST", "/v1.44/volumes/create"),
    ("GET", "/v1.44/secrets"),
    ("POST", "/v1.44/containers/prune"),
    ("DELETE", "/v1.44/images/web"),
    ("GET", "/v1.44/images/web/json/../../containers/create"),
    # A digest-pinned name. DDC never asks for one - an image reference with a
    # digest cannot change, so the image-update check skips it before it reads
    # the image - and docker-py would send it percent-encoded anyway, which this
    # proxy refuses. An allowlist should not permit what nobody can use.
    ("GET", "/v1.44/images/nginx@sha256:" + "a" * 64 + "/json"),
    ("GET", "/v1.44/containers/../info"),
    ("GET", "/v1.44/containers/%2e%2e/json"),
    ("GET", "//v1.44/containers/json"),
    ("GET", "/v1.44/containers/json\n"),
    ("POST", "/v1.44/containers/web/json"),
    ("GET", "/v1.44/containers/web/start"),
    ("GET", "containers/json"),
]


@pytest.mark.parametrize("method,target", ALLOWED)
def test_each_needed_endpoint_is_allowed(method, target):
    assert is_allowed(method, target)


@pytest.mark.parametrize("method,target", DENIED)
def test_each_other_endpoint_is_refused(method, target):
    assert not is_allowed(method, target)


def _raw(proxy_path, request):
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(proxy_path)
        conn.sendall(request)
        return conn.recv(4096)


SMUGGLING = [
    # A bare LF: the proxy would see one header, dockerd (Go accepts LF line
    # endings) a second one - here a Transfer-Encoding the proxy never checked.
    b"GET /v1.44/containers/json HTTP/1.1\r\nHost: d\r\nX-A: 1\nTransfer-Encoding: chunked\r\n\r\n",
    # A bare CR inside a header value.
    b"GET /v1.44/containers/json HTTP/1.1\r\nHost: d\r\nX-A: 1\rX-B: 2\r\n\r\n",
    # Two Content-Length headers: which one counts is up to the reader.
    b"POST /v1.44/containers/web/start HTTP/1.1\r\nHost: d\r\nContent-Length: 0\r\nContent-Length: 40\r\n\r\n",
    # Junk after the protocol version on the request line.
    b"GET /v1.44/_ping HTTP/1.1 POST /v1.44/containers/create\r\nHost: d\r\n\r\n",
    # Not HTTP/1.x at all.
    b"GET /v1.44/_ping HTTP/2.0\r\nHost: d\r\n\r\n",
]


@pytest.mark.parametrize("request_bytes", SMUGGLING)
def test_an_ambiguous_request_is_refused_before_the_daemon(proxied, request_bytes):
    proxy_path, seen = proxied
    answer = _raw(proxy_path, request_bytes)
    assert answer.startswith((b"HTTP/1.1 400", b"HTTP/1.1 403")), answer[:60]
    # The PROXY must refuse, not the daemon behind it: the first run of this
    # test was green for the junk-after-version case only because the stand-in
    # daemon rejected what the proxy had forwarded.
    assert b"DDC docker proxy" in answer, answer
    assert seen == [], f"the daemon saw an ambiguous request: {seen}"
