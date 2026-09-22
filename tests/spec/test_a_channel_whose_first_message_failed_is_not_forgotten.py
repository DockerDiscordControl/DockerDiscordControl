# -*- coding: utf-8 -*-
"""A channel whose first message could not be sent is not left blank for ever.

THE FINDING: setting a channel up deletes the old messages, posts the
overview and tracks its id. Both senders swallow their own send failures, and
the setup swallows what is left - so after a failed send the channel entry is
EMPTY, and the periodic loop skips every channel with no tracked message. The
operator sees an empty channel and DDC never tries again: the only way back
is the inactivity regeneration, which does nothing for a channel whose
recreate_messages_on_inactivity is off, or a restart.

A setup that tracked nothing now says so, and leaves the channel out of the
tracking map entirely - so the next hot-reload sees it as a channel to add
and builds it again.

COUNTER-CHECK (2026-09-22): red before - the empty entry stayed and nothing
was logged as an error. A setup that worked must keep its tracking (second
test).
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.docker_control import DockerControlCog

CHANNEL = 77


class _TextChannel(discord.TextChannel):
    def __init__(self):
        self.id = CHANNEL
        self.name = "status"

    def __repr__(self):
        return "<channel>"


def _cog(send):
    cog = object.__new__(DockerControlCog)
    cog.bot = SimpleNamespace(fetch_channel=AsyncMock(return_value=_TextChannel()))
    cog.channel_server_message_ids = {}
    cog._channel_locks = {}
    cog.last_channel_activity = {}
    cog.last_message_update_time = {}
    cog._persist_tracked_message_ids = MagicMock()
    cog.delete_bot_messages = AsyncMock()
    cog._delete_tracked_overview_messages = AsyncMock()
    cog._background_cache_population = AsyncMock()
    cog._send_all_server_statuses = send
    cog._send_control_panel_and_statuses = AsyncMock()
    return cog


CONFIG = {"commands": {"control": False, "serverstatus": True}, "post_initial": True}


def test_a_setup_that_posted_nothing_is_reported_and_not_tracked(caplog):
    async def _send_that_fails(channel, **kwargs):
        return None                      # the sender swallowed its own failure

    cog = _cog(_send_that_fails)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(cog._setup_channel(CHANNEL, CONFIG))

    assert CHANNEL not in cog.channel_server_message_ids, (
        "an empty entry makes the periodic loop skip this channel for ever")
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], "nothing was reported"


def test_a_setup_that_worked_keeps_its_tracking(caplog):
    """Counter-check: the ordinary setup must not be undone."""
    async def _send_that_works(channel, **kwargs):
        cog.channel_server_message_ids.setdefault(CHANNEL, {})["overview"] = 123

    cog = _cog(_send_that_works)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(cog._setup_channel(CHANNEL, CONFIG))

    assert cog.channel_server_message_ids[CHANNEL] == {"overview": 123}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert CHANNEL in cog.last_channel_activity
