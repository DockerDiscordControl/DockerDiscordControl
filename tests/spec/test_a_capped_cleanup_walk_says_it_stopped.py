# -*- coding: utf-8 -*-
"""A one-by-one cleanup that stops at its cap of 50 messages says so.

THE FINDING (stage 4 review before v3.1.0, section 14 pass 4 F2, second
half): when the bulk purge is refused or times out, the cleanup deletes one
message at a time and looks at no more than 50. A channel with more of the
bot's messages than that kept the rest, and nothing said the walk had
stopped - the shortfall read like a permission problem.

THE CONTRACT: a walk that reached its cap logs a WARNING that older
messages were not looked at.

HOW THIS TEST CAN FAIL: the cap is reached in silence again.

COUNTER-CHECK (2026-09-30): red before the change; a walk under the cap
stays quiet.
"""

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from services.discord.channel_cleanup_service import ChannelCleanupService

BOT = SimpleNamespace(id=1, name="DDC")


async def _run(count, monkeypatch, caplog):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    messages = [SimpleNamespace(id=n, author=BOT, content="x", embeds=[], delete=AsyncMock(),
                                created_at=datetime.now(timezone.utc)) for n in range(count)]

    async def _history(limit=100, **kwargs):
        for m in messages[:limit]:
            yield m
    channel = SimpleNamespace(id=77, history=_history, purge=AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")))
    with caplog.at_level(logging.WARNING):
        await ChannelCleanupService(SimpleNamespace(user=BOT)).delete_bot_messages_preserve_live_logs(
            channel, "startup")
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "50" in r.getMessage()]


@pytest.mark.asyncio
async def test_the_cap_is_named(monkeypatch, caplog):
    assert await _run(60, monkeypatch, caplog), "the walk stopped at 50 messages without a word"


@pytest.mark.asyncio
async def test_a_short_walk_stays_quiet(monkeypatch, caplog):
    assert not await _run(3, monkeypatch, caplog)
