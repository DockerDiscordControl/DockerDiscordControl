# -*- coding: utf-8 -*-
"""An empty tracked channel that grants neither control nor serverstatus gets no panel.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 4 F7): the
inactivity check regenerated an EMPTY tracked channel in "status" mode
whenever it lacked "control" - without the "neither control nor
serverstatus" guard the non-empty path has. Any channel with a
channel_permissions entry is tracked once somebody writes in it (a
donation-announcements-only channel, say); when that message was deleted,
the next check posted a server overview into a channel that grants neither.

THE CONTRACT: the same guard on both paths.

HOW THIS TEST CAN FAIL: an overview is posted there again.

COUNTER-CHECK (2026-09-29): red before the change; a status channel that is
empty is still regenerated.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import cogs.background_loops as loops
from cogs.docker_control import DockerControlCog

CHANNEL = 555


def _cog(monkeypatch, commands):
    monkeypatch.setattr(loops, "load_config", lambda: {"channel_permissions": {str(CHANNEL): {
        "commands": commands, "recreate_messages_on_inactivity": True,
        "inactivity_timeout_minutes": 10}}})
    cog = object.__new__(DockerControlCog)
    cog.initial_messages_sent = True
    cog.last_channel_activity = {CHANNEL: datetime.now(timezone.utc) - timedelta(hours=1)}
    cog.channel_server_message_ids = {}
    cog.bot = MagicMock()
    cog.bot.get_channel.return_value = None
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "announcements"
    channel.history.return_value.flatten = AsyncMock(return_value=[])
    cog.bot.fetch_channel = AsyncMock(return_value=channel)
    cog._regenerate_channel = AsyncMock()
    return cog


async def test_a_channel_without_either_right_stays_empty(monkeypatch):
    cog = _cog(monkeypatch, {})
    await DockerControlCog.inactivity_check_loop.coro(cog)
    cog._regenerate_channel.assert_not_awaited()


async def test_an_empty_status_channel_is_still_regenerated(monkeypatch):
    cog = _cog(monkeypatch, {"serverstatus": True})
    await DockerControlCog.inactivity_check_loop.coro(cog)
    cog._regenerate_channel.assert_awaited_once()
