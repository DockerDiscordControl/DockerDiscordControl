# -*- coding: utf-8 -*-
"""Stop All paces itself like Restart All - by attempts, not by successes.

THE FINDING: the pause between two containers ("to avoid overloading") was
fixed for the bulk RESTART on 2026-09-22: it counted successful restarts, so
on a daemon where every call fails or times out the counter stayed at zero and
fifty containers hit the daemon back to back - in exactly the situation the
pause exists for. Stop All carries its own copy of that loop and was not
touched: it still paced on stopped_count.

The repair that made one copy right left the other one wrong, which is the
reason both loops now run through one helper. Restart All, Restart Stack and
Stop All share it; only the verb differs.

COUNTER-CHECK (2026-09-23): red before - with every stop failing, Stop All
slept not once for three running containers. The second test keeps the pause
away from the first container, and the third holds the counts the summary is
built from.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
from services.docker_status.models import ContainerStatusResult

CHANNEL = 4242
NAMES = ("web", "db", "cache")


def _interaction():
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 7
    inter.channel.id = CHANNEL
    return inter


@pytest.fixture
def world(monkeypatch):
    """Three running containers, every stop failing, every sleep recorded."""
    sleeps = []
    servers = [{"docker_name": name, "active": True, "allowed_actions": ["stop"]}
               for name in NAMES]

    def _running(name):
        return {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)}

    async def _sleep(seconds):
        sleeps.append(seconds)

    cog = SimpleNamespace(_bulk_operation_in_progress=False,
                          bot=SimpleNamespace(get_channel=lambda cid: None))
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=_running))
    monkeypatch.setattr(ao, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True)))
    monkeypatch.setattr(ao.asyncio, "sleep", _sleep)
    return SimpleNamespace(cog=cog, sleeps=sleeps)


def _stop_all(world, monkeypatch, succeeds):
    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first",
                        AsyncMock(return_value=succeeds))
    button = ao.ConfirmStopAllButton(world.cog, CHANNEL)
    asyncio.run(button.callback(_interaction()))
    # The delayed overview update is fire-and-forget; only the pacing is under test.
    return [s for s in world.sleeps if s == 0.5]


def test_a_failing_stop_run_is_paced_too(world, monkeypatch):
    paced = _stop_all(world, monkeypatch, succeeds=False)

    assert paced == [0.5, 0.5], (
        f"three containers hit a struggling daemon with {len(paced)} pauses")


def test_a_successful_stop_run_pauses_between_containers(world, monkeypatch):
    """Counter-check: the first container is not kept waiting."""
    paced = _stop_all(world, monkeypatch, succeeds=True)

    assert paced == [0.5, 0.5]


def test_the_helper_counts_what_the_summary_reports(monkeypatch):
    """Counter-check: sharing the loop must not change what is counted."""
    servers = [{"docker_name": "web", "allowed_actions": ["stop"]},
               {"docker_name": "db", "allowed_actions": []},
               {"docker_name": "gone", "allowed_actions": ["stop"]}]
    cache = {"web": {"data": ContainerStatusResult.success_result(
        docker_name="web", display_name="web", is_running=True, cpu="1%", ram="1MB",
        uptime="1h", details_allowed=True)}}
    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=lambda name: cache.get(name)))
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())

    async def action(name, verb):
        assert verb == "stop"
        return True

    counts = asyncio.run(ao._act_on_running_servers(servers, action, "stop"))

    assert counts == {"done": 1, "failed": 0, "skipped": 0, "unknown": 1, "not_allowed": 1}
