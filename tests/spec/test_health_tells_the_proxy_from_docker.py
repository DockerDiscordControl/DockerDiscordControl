# -*- coding: utf-8 -*-
"""/health tells "proxy unreachable" from "Docker unreachable" (v3.0 step 11, V3 §7).

With the allowlist proxy there is a new thing that can fail between DDC and
Docker. "Docker is down" and "DDC's own proxy is down" need different fixes -
the first is the host's, the second a DDC restart - and a single "cannot
reach Docker" would send the operator to the wrong one.

The check is one raw ``GET /_ping`` on the socket ``DOCKER_HOST`` names:
cheap enough for a healthcheck every 30 s, and no docker-py client (which
would negotiate the API version first). The HTTP status of /health stays 200:
restarting the container does not bring a dead daemon back.

COUNTER-CHECK (2026-09-22): written before the check existed; then the proxy's
502 was read as "ok" and the docker_unreachable case went red; restored, green.
"""

import os
import threading

import pytest

from services.docker_proxy.allowlist_proxy import serve
from tests.spec.fake_dockerd import running_fake_dockerd


def _proxy(workdir, upstream):
    server = serve(f"{workdir}/p.sock", upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"unix://{workdir}/p.sock"


def test_ok_through_the_proxy():
    from services.docker_service.reachability import docker_reachability

    with running_fake_dockerd() as (workdir, daemon_path, _):
        server, host = _proxy(workdir, daemon_path)
        try:
            assert docker_reachability(host, proxied=True) == {"path": "proxy", "state": "ok"}
        finally:
            server.shutdown()
            server.server_close()


def test_the_proxy_itself_is_down(tmp_path):
    from services.docker_service.reachability import docker_reachability

    result = docker_reachability(f"unix://{tmp_path}/missing.sock", proxied=True)
    assert result == {"path": "proxy", "state": "proxy_unreachable"}


def test_the_proxy_is_up_but_docker_behind_it_is_not():
    from services.docker_service.reachability import docker_reachability

    with running_fake_dockerd() as (workdir, _, _seen):
        server, host = _proxy(workdir, f"{workdir}/no-daemon.sock")
        try:
            assert docker_reachability(host, proxied=True) == {"path": "proxy", "state": "docker_unreachable"}
        finally:
            server.shutdown()
            server.server_close()


def test_without_the_proxy_a_dead_socket_is_docker_unreachable(tmp_path):
    from services.docker_service.reachability import docker_reachability

    assert docker_reachability(f"unix://{tmp_path}/missing.sock", proxied=False) == {
        "path": "direct", "state": "docker_unreachable"}


def test_health_reports_it(monkeypatch, tmp_path):
    from app.web import create_app

    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DOCKER_HOST", "unix:///run/ddc-proxy/docker.sock")
    import services.docker_service.reachability as reachability

    monkeypatch.setattr(reachability, "docker_reachability",
                        lambda host, proxied: {"path": "proxy", "state": "proxy_unreachable"})
    answer = create_app({"TESTING": True}).test_client().get("/health")
    assert answer.status_code == 200
    assert answer.get_json()["docker"] == {"path": "proxy", "state": "proxy_unreachable"}
