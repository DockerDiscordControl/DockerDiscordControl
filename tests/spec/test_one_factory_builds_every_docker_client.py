# -*- coding: utf-8 -*-
"""One factory builds every Docker client (v3.0 step 6, V3 §6 and §7).

Eight places built their own client in eight ways: two through the configured
``docker_socket_path``, three with a hard-coded ``unix:///var/run/docker.sock``,
the rest through ``DOCKER_HOST``. Behind the v3.0 proxy only ``DOCKER_HOST``
leads through it - every other way walks past it, and since both ways work no
functional test would notice. The factory is the one way:

* it follows ``DOCKER_HOST`` (and docker-py's TLS variables) via ``from_env``;
* every caller names its own timeout - the eight sites used five different
  ones for good reasons (a 5 s diagnostic probe, two Advanced Settings), and
  a shared default would silently drop them;
* the API version is negotiated ONCE and reused. docker-py negotiates on every
  client built without ``version=`` (one ``GET /version`` each). V3 planned a
  fixed pin; measured on 2026-09-22, the operator's Docker 29.5.3 accepts API
  1.40-1.54 and docker-py 7.1.0 defaults to 1.44, which a daemon older than
  Docker 25 would refuse. Negotiating once keeps every daemon working;
* ``docker_socket_path`` is retired: a non-default value is reported loudly
  and not used, instead of silently steering one client past the proxy.

COUNTER-CHECK (2026-09-22): written before the factory existed, so the first
run failed on the import - a red that proves nothing on its own. The factory
was then written with the version cache disabled: the once-only test went red
with three ``GET /version``; with the cache, green.
"""

import logging
import threading

import pytest

from services.docker_proxy.allowlist_proxy import serve
from tests.spec.fake_dockerd import running_fake_dockerd


@pytest.fixture
def fake(monkeypatch):
    from services.docker_service import client_factory

    client_factory._reset_for_tests()
    with running_fake_dockerd() as (workdir, daemon_path, seen):
        monkeypatch.setenv("DOCKER_HOST", f"unix://{daemon_path}")
        yield workdir, daemon_path, seen
    client_factory._reset_for_tests()


def _versions(seen):
    return [path for _, path in seen if path.split("?", 1)[0].endswith("/version")]


def test_the_timeout_must_be_named(fake):
    from services.docker_service.client_factory import build_docker_client

    with pytest.raises(TypeError):
        build_docker_client()
    with pytest.raises(TypeError):
        build_docker_client(5)


def test_the_client_goes_where_docker_host_points(fake):
    from services.docker_service.client_factory import build_docker_client

    _, _, seen = fake
    client = build_docker_client(timeout=5)
    try:
        assert client.ping() is True
    finally:
        client.close()
    assert any(path.endswith("/_ping") for _, path in seen), seen


def test_the_api_version_is_negotiated_once(fake):
    from services.docker_service.client_factory import build_docker_client

    _, _, seen = fake
    for _ in range(3):
        client = build_docker_client(timeout=5)
        try:
            client.ping()
            assert client.api.api_version == "1.44"
        finally:
            client.close()
    assert len(_versions(seen)) == 1, _versions(seen)


def test_a_configured_socket_path_is_reported_not_used(fake, monkeypatch, caplog):
    from services.docker_service import client_factory

    monkeypatch.setattr(
        client_factory, "_load_docker_config",
        lambda: {"docker_socket_path": "/somewhere/else.sock"},
    )
    caplog.set_level(logging.WARNING)
    client = client_factory.build_docker_client(timeout=5)
    try:
        assert client.ping() is True  # reached DOCKER_HOST, not /somewhere/else.sock
    finally:
        client.close()
    assert "/somewhere/else.sock" in caplog.text and "DOCKER_HOST" in caplog.text


def test_the_factory_works_through_the_proxy(fake, monkeypatch):
    from services.docker_service.client_factory import build_docker_client

    workdir, daemon_path, seen = fake
    proxy = serve(f"{workdir}/p.sock", daemon_path)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    monkeypatch.setenv("DOCKER_HOST", f"unix://{workdir}/p.sock")
    try:
        client = build_docker_client(timeout=5)
        try:
            assert client.ping() is True
            assert [c.name for c in client.containers.list()] == ["web"]
        finally:
            client.close()
    finally:
        proxy.shutdown()
        proxy.server_close()
