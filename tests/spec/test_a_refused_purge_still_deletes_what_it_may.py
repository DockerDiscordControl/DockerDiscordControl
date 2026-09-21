# -*- coding: utf-8 -*-
"""A cleanup the bot IS allowed to do is not refused because a shortcut was.

THE FINDING (review D33, pass 2, section 14 F2): `_purge_with_filter`'s
`discord.Forbidden` handler gave up on the spot:

    except discord.Forbidden:
        result.permission_errors += 1
        result.method_used = "purge forbidden -> no action"

"no action" is the whole story. Nothing was deleted and nothing else was
tried, although the two neighbours of this handler both know better:

  * the `asyncio.TimeoutError` branch three lines above falls back to
    deleting the messages one by one;
  * `_bulk_delete_messages` falls back to `_individual_delete_messages` on
    this very same `discord.Forbidden`.

And the reason it matters: `channel.purge()` needs 'Manage Messages' because
it deletes in bulk. Deleting its OWN messages is something a bot may do
without that permission. So in a channel where the bot lacks it - which is a
perfectly reasonable way to set a channel up - the purge path gave up on work
it was allowed to do, and the operator was told the cleanup failed for a
permission they never needed to grant.

Not to be confused with Z3 (pass 1, 14 F1), which is about a cleanup that
deleted nothing REPORTING success. This one is about not trying.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from services.discord.channel_cleanup_service import ChannelCleanupService

NOW = datetime.now(timezone.utc)


def _forbidden():
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"),
                             {"message": "Missing Permissions", "code": 50013})


def _bot_message(*, refused=False):
    message = MagicMock()
    message.id = 4711
    message.created_at = NOW - timedelta(days=1)
    message.embeds = []
    message.content = "status"
    message.delete = AsyncMock(side_effect=_forbidden() if refused else None)
    return message


def _channel(messages, *, purge_forbidden):
    channel = MagicMock()
    channel.id = 4242
    channel.purge = AsyncMock(
        side_effect=_forbidden() if purge_forbidden else None,
        return_value=[] if purge_forbidden else list(messages))

    def history(limit=None, **kwargs):     # noqa: ARG001 - the fake ignores limits
        async def walk():
            for message in messages:
                yield message
        return walk()

    channel.history = history
    channel.delete_messages = AsyncMock()
    return channel


async def _clean(messages, *, purge_forbidden=True):
    bot = MagicMock()
    service = ChannelCleanupService(bot=bot)
    channel = _channel(messages, purge_forbidden=purge_forbidden)
    for message in messages:
        message.author = bot.user
    return await service.delete_bot_messages_preserve_live_logs(
        channel, reason="test"), channel


async def test_a_refused_purge_deletes_the_messages_one_by_one():
    """The finding: the bot may delete its own messages without the shortcut."""
    messages = [_bot_message(), _bot_message()]

    result, _ = await _clean(messages)

    assert any(message.delete.await_count for message in messages), (
        f"the purge was refused and nothing else was tried - "
        f"method_used={result.method_used!r}, and every message is still there"
    )


async def test_it_says_what_it_did_instead():
    """The label AND the count, not the label alone.

    This first checked only that method_used no longer said "no action", and
    two probes walked straight past it: removing the fallback call, and
    replacing the delete with a pass, both left the label standing. A label
    can lie. What it says is now tied to what was counted.
    """
    messages = [_bot_message(), _bot_message()]

    result, _ = await _clean(messages)

    assert result.individually_deleted == len(messages), (
        f"method_used={result.method_used!r} but {result.individually_deleted} "
        f"of {len(messages)} messages were counted as deleted"
    )
    assert "no action" not in (result.method_used or ""), (
        f"method_used={result.method_used!r} after messages were deleted"
    )


async def test_a_cleanup_that_is_really_refused_is_still_a_failure():
    """The counter-case. Deleting one by one is not a way to claim success.

    If the individual deletes are refused too, nothing was deleted and that is
    what the result must say - this is the ground Z3 holds, and the fallback
    must not quietly take it away.
    """
    messages = [_bot_message(refused=True)]

    result, _ = await _clean(messages)

    assert result.permission_errors > 0
    assert not result.success, (
        "every delete was refused and the cleanup reports success"
    )


async def test_a_permitted_purge_still_uses_the_purge():
    """The other counter-case: the shortcut is still the normal path."""
    messages = [_bot_message()]

    result, channel = await _clean(messages, purge_forbidden=False)

    channel.purge.assert_awaited()
    assert result.method_used == "Discord purge API", result.method_used
    assert not any(message.delete.await_count for message in messages), (
        "the purge worked and the messages were deleted a second time"
    )
