# -*- coding: utf-8 -*-
# @covers Z3
"""Z3 - a cleanup that deleted nothing does not report success.

THE FINDING (stage 4 review pass 1, section 14 F1, re-checked 2026-09-19):
``ChannelCleanupService.cleanup_channel`` set ``result.success = True``
unconditionally once it had walked the channel. Without the "Manage
Messages" permission every delete fails with ``discord.Forbidden``, each one
counted in ``permission_errors`` - and the result still said success, the
log "✅ CLEANUP SUCCESS ... 0/N messages". Whoever asked for the cleanup is
told it worked; the messages are all still there.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from services.discord.channel_cleanup_service import (ChannelCleanupRequest,
                                                      ChannelCleanupService)

NOW = datetime.now(timezone.utc)


def _forbidden():
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"),
                             {"message": "Missing Permissions", "code": 50013})


def _message(refused):
    message = MagicMock()
    message.created_at = NOW - timedelta(days=1)
    message.id = 4711
    message.delete = AsyncMock(side_effect=_forbidden() if refused else None)
    return message


def _channel(messages):
    channel = MagicMock()
    channel.id = 4242

    def history(limit=None):          # noqa: ARG001 - the fake ignores the limit
        async def walk():
            for message in messages:
                yield message
        return walk()

    channel.history = history
    channel.delete_messages = AsyncMock(side_effect=_forbidden())
    return channel


async def _cleanup(refused):
    service = ChannelCleanupService(bot=MagicMock())
    request = ChannelCleanupRequest(channel=_channel([_message(refused)]),
                                    reason="test", bot_only=False)
    return await service.cleanup_channel(request)


@pytest.mark.asyncio
async def test_refused_deletes_are_not_a_success():
    result = await _cleanup(refused=True)

    assert result.messages_found == 1, "premise: the walk found the message"
    assert result.permission_errors > 0, "premise: the delete was refused"
    assert result.messages_deleted == 0
    assert not result.success, (
        "nothing could be deleted for lack of permission, and it reports success"
    )


@pytest.mark.asyncio
async def test_a_cleanup_that_works_is_still_a_success():
    """Counter-check: otherwise 'never a success' would pass the test above."""
    result = await _cleanup(refused=False)

    assert result.messages_deleted == 1 and result.success, (
        f"deleted {result.messages_deleted}, success={result.success}"
    )
