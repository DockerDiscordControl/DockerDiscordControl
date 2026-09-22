# -*- coding: utf-8 -*-
"""A message DDC could not delete is tried again, not left in the channel.

THE FINDING: before posting a fresh overview, DDC deletes the tracked one by
id. When that delete fails - Discord answers 403 or 500 - the id is kept on
purpose, "so a later regenerate retries the by-id delete". It never can: the
caller's very next step posts the replacement and writes the new id over it.
The old overview then stays in the channel, untracked; after thirty days the
age-limited cleanup skips it as well, and the channel keeps two overviews for
good - the exact duplicate this helper exists to prevent.

The ids that could not be deleted are remembered per channel and tried again
on the next round.

COUNTER-CHECK (2026-09-22): red before - the failed id was overwritten and
never retried; a delete that works must not leave anything behind (third
test).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.docker_control import DockerControlCog

CHANNEL, OLD = 5, 500


def _cog(tracked):
    cog = object.__new__(DockerControlCog)
    cog.channel_server_message_ids = {CHANNEL: dict(tracked)}
    cog._persist_tracked_message_ids = MagicMock()
    return cog


def _channel(failing_ids=()):
    deleted = []

    def _partial(message_id):
        async def _delete():
            if message_id in failing_ids:
                raise discord.errors.HTTPException(MagicMock(status=500), "later")
            deleted.append(message_id)

        return SimpleNamespace(delete=_delete)

    channel = MagicMock()
    channel.id = CHANNEL
    channel.get_partial_message = _partial
    return channel, deleted


def test_a_failed_delete_is_remembered(): 
    cog = _cog({"overview": OLD})
    channel, _deleted = _channel(failing_ids={OLD})

    asyncio.run(cog._delete_tracked_overview_messages(channel))

    pending = getattr(cog, "_undeleted_messages", {}).get(CHANNEL, set())
    assert OLD in pending, "the id was dropped, so nobody will ever delete that message"
    assert cog.channel_server_message_ids[CHANNEL].get("overview") != OLD, (
        "keeping it in the tracking map only hides it: the caller overwrites it next")


def test_the_next_round_deletes_it():
    cog = _cog({"overview": OLD})
    channel, _deleted = _channel(failing_ids={OLD})
    asyncio.run(cog._delete_tracked_overview_messages(channel))

    cog.channel_server_message_ids[CHANNEL] = {"overview": 777}
    channel, deleted = _channel()
    asyncio.run(cog._delete_tracked_overview_messages(channel))

    assert OLD in deleted, f"the stranded message was never retried: {deleted}"
    assert not getattr(cog, "_undeleted_messages", {}).get(CHANNEL)


def test_a_delete_that_works_leaves_nothing_behind():
    """Counter-check: the ordinary case must not start collecting ids."""
    cog = _cog({"overview": OLD})
    channel, deleted = _channel()

    asyncio.run(cog._delete_tracked_overview_messages(channel))

    assert deleted == [OLD]
    assert not getattr(cog, "_undeleted_messages", {}).get(CHANNEL)


def test_a_message_that_is_already_gone_is_forgotten():
    """Counter-check: a 404 means done, not pending."""
    cog = _cog({"overview": OLD})
    channel = MagicMock()
    channel.id = CHANNEL

    def _partial(message_id):
        async def _delete():
            raise discord.errors.NotFound(MagicMock(status=404), "gone")

        return SimpleNamespace(delete=_delete)

    channel.get_partial_message = _partial
    asyncio.run(cog._delete_tracked_overview_messages(channel))

    assert not getattr(cog, "_undeleted_messages", {}).get(CHANNEL)
