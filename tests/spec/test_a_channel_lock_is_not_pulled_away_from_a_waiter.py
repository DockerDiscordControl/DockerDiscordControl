# -*- coding: utf-8 -*-
"""The per-channel lock is not pulled away from somebody waiting on it.

THE FINDING: tearing a channel down pops its entry from _channel_locks. A
coroutine that is already waiting on that Lock object keeps its reference;
the next caller asks _get_channel_lock for the same channel, finds nothing
and mints a NEW Lock. Two coroutines are then inside the "one lock per
channel" section at the same time - the very thing the lock was added for
(FIX B). Reachable when a channel is removed while /control or a regenerate
for it is in flight, or removed and re-added across two saves.

The entry is dropped only when the lock is free; otherwise it stays and is
dropped the next time round.

COUNTER-CHECK (2026-09-22): red before - the waiter's lock was replaced by a
fresh one. A lock nobody uses must still be dropped (second test).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.docker_control import DockerControlCog

CHANNEL = 42


class _TextChannel(discord.TextChannel):
    def __init__(self):
        self.id = CHANNEL
        self.name = "chan"

    def __repr__(self):
        return "<channel>"


def _text_channel():
    return _TextChannel()


def _cog():
    cog = object.__new__(DockerControlCog)
    cog.bot = SimpleNamespace(get_channel=lambda cid: None)
    cog.channel_server_message_ids = {CHANNEL: {"overview": 1}}
    cog._channel_locks = {}
    cog.last_message_update_time = {CHANNEL: 1}
    cog.last_channel_activity = {CHANNEL: 1}
    cog.mech_expanded_states = {CHANNEL: True}
    cog.last_glvl_per_channel = {CHANNEL: 3}
    cog._persist_tracked_message_ids = MagicMock()
    cog.delete_bot_messages = AsyncMock()
    return cog


@pytest.mark.asyncio
async def test_a_lock_somebody_is_waiting_for_is_kept():
    """The teardown holds the lock itself, so the waiter arrives while it runs -
    exactly what happens when /control or a regenerate is in flight."""
    cog = _cog()
    lock = cog._get_channel_lock(CHANNEL)
    entered = asyncio.Event()

    async def _competitor():
        await entered.wait()
        async with cog._get_channel_lock(CHANNEL):   # waits behind the teardown
            return cog._get_channel_lock(CHANNEL)

    async def _slow_delete(channel):
        entered.set()
        await asyncio.sleep(0.05)                    # give the competitor time to queue up

    cog.delete_bot_messages = _slow_delete
    cog.bot = SimpleNamespace(get_channel=lambda cid: _text_channel())

    waiter = asyncio.create_task(_competitor())
    await cog._teardown_channel(CHANNEL)
    lock_seen_by_the_waiter = await asyncio.wait_for(waiter, timeout=5)

    assert lock_seen_by_the_waiter is lock, (
        "a second coroutine would now enter the same section with a fresh lock")


@pytest.mark.asyncio
async def test_a_free_lock_is_dropped():
    """Counter-check: the entry must not be kept for ever."""
    cog = _cog()
    cog._get_channel_lock(CHANNEL)

    await cog._teardown_channel(CHANNEL)

    assert CHANNEL not in cog._channel_locks


@pytest.mark.asyncio
async def test_the_rest_of_the_teardown_still_happens():
    """Counter-check: keeping the lock must not keep everything else."""
    cog = _cog()
    await cog._teardown_channel(CHANNEL)

    assert CHANNEL not in cog.channel_server_message_ids
    assert CHANNEL not in cog.last_channel_activity
