# -*- coding: utf-8 -*-
"""A channel added or removed mid-update does not abandon the other channels.

THE FINDING: _auto_update_ss_messages walks
`self.channel_server_message_ids.items()` with many awaits inside the loop,
while _teardown_channel pops from that dict and _send_all_server_statuses
creates keys in it - both scheduled onto the same loop from the web panel
(a config save) and from mech events. A save landing in the middle raises
"dictionary changed size during iteration", which the outer handler swallows,
and every channel after the current one is silently skipped for that round.

The periodic loop takes a snapshot for exactly this reason and says so; this
path did not get the same treatment during the cog split.

COUNTER-CHECK (2026-09-22): red before - the run stopped at the first channel
and the second was never updated.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.docker_control import DockerControlCog


@pytest.fixture
def cog(monkeypatch):
    cog = object.__new__(DockerControlCog)
    seen = []

    def _channel(cid):
        channel = MagicMock()
        channel.id = cid
        channel.name = f"c{cid}"

        async def _fetch(message_id):
            seen.append(cid)
            if cid == 1:
                # what a config save does while this loop runs
                cog.channel_server_message_ids[99] = {"overview": 999}
            raise discord.errors.NotFound(MagicMock(status=404), "gone")

        channel.fetch_message = _fetch
        return channel

    cog.bot = SimpleNamespace(get_channel=_channel)
    cog.channel_server_message_ids = {1: {"overview": 11}, 2: {"overview": 22}}
    cog.last_message_update_time = {}
    cog.last_channel_activity = {}
    cog._channel_locks = {}
    cog.pending_actions = {}
    cog._persist_tracked_message_ids = MagicMock()
    cog._background_cache_population = AsyncMock()
    monkeypatch.setattr("cogs.message_updates.load_config", lambda: {"language": "en"})
    monkeypatch.setattr("services.config.server_config_service.get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [{"docker_name": "web"}]))
    return cog, seen


def test_every_channel_is_still_updated(cog):
    instance, seen = cog

    asyncio.run(instance._auto_update_ss_messages("test", force_recreate=False))

    assert sorted(seen) == [1, 2], (
        f"the run was abandoned after the dict changed: {seen}")
