# -*- coding: utf-8 -*-
"""A tracked channel the bot may no longer see is not asked again every cycle.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 4 F8): when the
bot lost access to a tracked channel, the inactivity check fetched it,
Discord answered Forbidden, and the handler logged an ERROR and changed
nothing - so the next cycle, 30 seconds later, did exactly the same, for
ever. A channel that is gone (NotFound) is dropped; a failed regeneration
backs off; a forbidden one did neither.

THE CONTRACT: after Forbidden the channel is left alone for 30 minutes.

HOW THIS TEST CAN FAIL: a second cycle asks Discord again straight away.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

import cogs.background_loops as loops
from cogs.docker_control import DockerControlCog

CHANNEL = 555


async def test_two_cycles_ask_discord_once(monkeypatch):
    monkeypatch.setattr(loops, "load_config", lambda: {"channel_permissions": {str(CHANNEL): {
        "recreate_messages_on_inactivity": True, "inactivity_timeout_minutes": 10}}})
    cog = object.__new__(DockerControlCog)
    cog.initial_messages_sent = True
    cog.last_channel_activity = {CHANNEL: datetime.now(timezone.utc) - timedelta(hours=1)}
    cog.channel_server_message_ids = {}
    cog.bot = MagicMock()
    cog.bot.get_channel.return_value = None
    cog.bot.fetch_channel = AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Missing Access"))

    await DockerControlCog.inactivity_check_loop.coro(cog)
    await DockerControlCog.inactivity_check_loop.coro(cog)

    assert cog.bot.fetch_channel.await_count == 1, (
        f"a forbidden channel was asked {cog.bot.fetch_channel.await_count} times in two cycles")
