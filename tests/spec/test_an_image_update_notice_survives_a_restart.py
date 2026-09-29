# -*- coding: utf-8 -*-
"""A newer image is announced once per new image - across DDC restarts too.

THE FINDING (stage 4 review before v3.1.0, section 42 pass 4 F2): the image
check remembers which remote digest it already reported in memory only. After
every DDC restart or rebuild the first status loop checks at once and posts
"A newer image for ... is in the registry" again for every container still
behind - "once per new image" held for one process lifetime.

THE OPERATOR (2026-09-29): once per new image, remembered across restarts.

THE CONTRACT: what was reported is written to config/image_updates_reported.json
and read back by the next process; a newer digest is reported again, and a
container that caught up re-arms, as before.

A notice that could not be handed on is not remembered: kept, it would be
lost for good now that the memory outlives the process.

HOW THIS TEST CAN FAIL: a second process (a restart) reports the same image
again; a newer image after the restart is swallowed; or a notice that failed
is never tried again.

It runs the cog's own _check_image_updates twice, each time on a fresh cog -
what a restart is - with Docker and the registry stood in for.

COUNTER-CHECK (2026-09-29): the first case red before the change, the
second green before and after.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    state = {"remote": "sha256:new", "reported": [], "broken": False}
    monkeypatch.setattr("services.automation.image_updates.read_running_image",
                        lambda client, name: ("nginx:latest", "nginx:latest", {"sha256:old"}))
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                        lambda timeout=20: SimpleNamespace(close=lambda: None))

    async def _remote(ref):
        return state["remote"]
    monkeypatch.setattr("services.automation.image_updates.remote_digest", _remote)

    async def _process(events, **kwargs):
        if state["broken"]:
            raise TypeError("rules could not be read")
        state["reported"].extend(e.container for e in events)
        return []
    monkeypatch.setattr("services.automation.automation_service.get_automation_service",
                        lambda: SimpleNamespace(process_container_events=_process))
    return state


def _one_process_checks():
    from cogs.docker_control import DockerControlCog
    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    asyncio.run(cog._check_image_updates(["web"], None))


def test_a_restart_does_not_announce_the_same_image_again(world):
    _one_process_checks()
    _one_process_checks()
    assert world["reported"] == ["web"], (
        f"the same newer image was announced {len(world['reported'])} times across a restart")


def test_a_newer_image_after_the_restart_is_announced(world):
    _one_process_checks()
    world["remote"] = "sha256:newer"
    _one_process_checks()
    assert world["reported"] == ["web", "web"]



def test_a_notice_that_failed_is_tried_again(world):
    world["broken"] = True
    _one_process_checks()
    world["broken"] = False
    _one_process_checks()
    assert world["reported"] == ["web"], "a notice that could not be handed on was never sent"
