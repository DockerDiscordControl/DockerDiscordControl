# -*- coding: utf-8 -*-
"""A cleanup in a channel without "Manage Messages" that deleted everything is a success.

THE FINDING (stage 4 review before v3.1.0, section 14 pass 4 F2): purge()
needs "Manage Messages" because it deletes in bulk. When refused, the
cleanup falls back to deleting the bot's own messages one by one - which
needs no permission and works (review D33). But the refused shortcut had
already been counted as a permission error, so a cleanup that removed
every message reported "could not be deleted - the bot is missing the
permission", and every startup logged a partial cleanup in such a channel.

THE CONTRACT: only a message the bot really could not delete counts.

HOW THIS TEST CAN FAIL: the refused shortcut is counted again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from services.discord.channel_cleanup_service import ChannelCleanupService

BOT = SimpleNamespace(id=1, name="DDC")


@pytest.mark.asyncio
async def test_three_own_messages_deleted_singly_is_success(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    messages = [SimpleNamespace(id=n, author=BOT, content="x", embeds=[], delete=AsyncMock(),
                                created_at=datetime.now(timezone.utc)) for n in range(3)]

    async def _history(limit=100, **kwargs):
        for m in messages:
            yield m
    channel = SimpleNamespace(id=77, history=_history, purge=AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")))

    result = await ChannelCleanupService(SimpleNamespace(user=BOT)).delete_bot_messages_preserve_live_logs(
        channel, "startup")

    assert all(m.delete.await_count == 1 for m in messages)
    assert result.success is True and result.error is None, result.error
