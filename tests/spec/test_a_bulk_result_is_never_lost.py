# -*- coding: utf-8 -*-
"""The result of a bulk action reaches the admin even after a long run.

THE FINDING: a bulk restart allows 30 seconds per container and has no
overall budget, while Discord's follow-up token for the interaction dies
after 15 minutes. Thirty-one containers that each time out are 15.5 minutes,
so `interaction.followup.send` raises NotFound and the admin never learns
what was restarted - and for the stack button, which has no except around
it, the only thing they see is the view's generic "an error occurred". The
whole time every other admin was told "another bulk operation is in
progress".

The summary now falls back to the channel the button sits in when the
interaction can no longer be answered. Nothing changes when it can.

COUNTER-CHECK (2026-09-22): red before - Restart All swallowed the summary
and the stack button raised NotFound out of its callback.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import cogs.admin_overview as ao
from services.docker_status.models import ContainerStatusResult

CHANNEL = 4242
ADMIN = 7


def _dead_followup():
    return AsyncMock(side_effect=discord.errors.NotFound(MagicMock(status=404), "expired"))


def _interaction():
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = _dead_followup()
    inter.user.id = ADMIN
    inter.channel.id = CHANNEL
    return inter


@pytest.fixture
def world(monkeypatch):
    posted = []
    channel = SimpleNamespace(send=AsyncMock(side_effect=lambda **kw: posted.append(kw)))
    cog = SimpleNamespace(_bulk_operation_in_progress=False,
                          bot=SimpleNamespace(get_channel=lambda cid: channel if cid == CHANNEL else None))
    servers = [{"docker_name": "web", "active": True, "allowed_actions": ["restart"]}]
    result = ContainerStatusResult.success_result(
        docker_name="web", display_name="web", is_running=True, cpu="1%", ram="1MB",
        uptime="1h", details_allowed=True)
    result.compose_project = "blog"
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=lambda name: {"data": result}))
    monkeypatch.setattr(ao, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True)))
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first",
                        AsyncMock(return_value=True))
    return SimpleNamespace(cog=cog, posted=posted)


def test_restart_all_posts_its_summary_to_the_channel(world):
    button = ao.ConfirmRestartAllButton(world.cog, CHANNEL)
    asyncio.run(button.callback(_interaction()))

    assert world.posted, "the summary of a finished bulk restart was lost"
    assert "restarted" in world.posted[0]["embed"].description.lower()


def test_the_stack_restart_posts_its_summary_to_the_channel(world):
    from cogs.stack_restart import ConfirmRestartStackButton

    button = ConfirmRestartStackButton(world.cog, CHANNEL, "blog")
    asyncio.run(button.callback(_interaction()))

    assert world.posted, "the summary of a finished stack restart was lost"
    assert not world.cog._bulk_operation_in_progress, "the bulk lock stayed held"


def test_a_live_interaction_still_gets_the_ephemeral_answer(world):
    """Counter-check: the channel is the fallback, not the new normal."""
    inter = _interaction()
    inter.followup.send = AsyncMock()

    asyncio.run(ao.ConfirmRestartAllButton(world.cog, CHANNEL).callback(inter))

    inter.followup.send.assert_awaited()
    assert world.posted == []
