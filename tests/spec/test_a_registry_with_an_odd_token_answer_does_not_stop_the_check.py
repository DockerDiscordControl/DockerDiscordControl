# -*- coding: utf-8 -*-
"""A registry whose token answer is not an object does not stop the image check.

THE FINDING (stage 4 review before v3.1.0, section 42 pass 4): a token
realm answering 200 with JSON that is not an object (null, [], a string)
made data.get() raise AttributeError, which remote_digest did not catch.
In the watchdog it aborted the check for every later container, dropped
the events already collected, and ended as asyncio's "Task exception was
never retrieved" - the next attempt 6 h later. For the info display,
cached_remote_digest broke its "never raises" and cached nothing, so each
opening asked that registry again at once.

THE CONTRACT: such an answer means "not known" (None); the next container
is still checked; the cache keeps the unknown answer for its retry time.

HOW THIS TEST CAN FAIL: the AttributeError escapes again.

COUNTER-CHECK (2026-09-30): red before the change (AttributeError).
"""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import services.automation.image_updates as image_updates
from services.automation.image_updates import ImageRef


@pytest.fixture
def odd_registry():
    async def start(token_body):
        async def manifest(request):
            realm = f"http://{request.host}/token"
            return web.Response(status=401, headers={"WWW-Authenticate": f'Bearer realm="{realm}"'})

        async def token(request):
            return web.Response(status=200, text=token_body, content_type="application/json")
        app = web.Application()
        app.router.add_route("HEAD", "/v2/a/b/manifests/latest", manifest)
        app.router.add_get("/token", token)
        server = TestServer(app)
        await server.start_server()
        return server
    return start


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["null", "[]", '"a string"'])
async def test_the_answer_is_unknown_not_an_error(odd_registry, body):
    server = await odd_registry(body)
    try:
        ref = ImageRef(f"127.0.0.1:{server.port}", "a/b", "latest")
        assert await image_updates.remote_digest(ref, scheme="http", timeout=5) is None
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_the_cache_never_raises_and_keeps_the_unknown(monkeypatch):
    async def broken(ref):
        raise AttributeError("'NoneType' object has no attribute 'get'")
    monkeypatch.setattr(image_updates, "remote_digest", broken)
    ref = ImageRef("registry.example", "a/b", "odd")
    monkeypatch.setattr(image_updates, "_REMOTE_CACHE", {})
    monkeypatch.setattr(image_updates, "_REMOTE_IN_FLIGHT", {})

    assert await image_updates.cached_remote_digest(ref, wait=1.0) is None
    assert image_updates._REMOTE_CACHE[ref][1] is None, "the unknown answer was not kept"


@pytest.mark.asyncio
async def test_the_watchdog_goes_on_to_the_next_container(odd_registry, monkeypatch, tmp_path):
    from cogs.docker_control import DockerControlCog

    server = await odd_registry("null")
    try:
        odd = ImageRef(f"127.0.0.1:{server.port}", "a/b", "latest")
        fine = ImageRef("registry.example", "c/d", "latest")
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                            lambda **kwargs: type("Client", (), {"close": lambda self: None})())
        refs = {"c1": odd, "c2": fine}
        monkeypatch.setattr(image_updates, "read_running_image",
                            lambda client, name: (f"img-{name}", refs[name], {"sha256:old"}))
        real = image_updates.remote_digest

        async def remote(ref, **kwargs):
            if ref is odd:
                return await real(ref, scheme="http", timeout=5)
            return "sha256:new"
        monkeypatch.setattr(image_updates, "remote_digest", remote)
        handed = []

        class _Automation:
            async def process_container_events(self, events, **kwargs):
                handed.extend(events)
        monkeypatch.setattr("services.automation.automation_service.get_automation_service",
                            lambda: _Automation())

        cog = DockerControlCog.__new__(DockerControlCog)
        cog.bot = None
        await cog._check_image_updates(["c1", "c2"], 111)

        assert [event.container for event in handed] == ["c2"]
    finally:
        await server.close()
