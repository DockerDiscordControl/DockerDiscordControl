# -*- coding: utf-8 -*-
"""The startup/recovery cleanup removes the bot's stray messages of any age.

THE FINDING (stage 4 review before v3.1.0, section 14 pass 3 F2 + pass 4
F3): delete_bot_messages_preserve_live_logs looked for messages younger than
30 days first and only purged when it found one - but the purge itself had
no age bound. So an old stray bot message was deleted when a young one
happened to be there, and survived every cleanup when none was: the same
channel, cleaned or not depending on luck.

THE OPERATOR (2026-09-29): bot messages of any age go (live logs and the
tracked messages are kept as before). The auto-action notices were kept too
until 2026-10-02; since then only a notice whose lifetime still runs is
(test_an_old_auto_action_notice_is_cleaned_up).

HOW THIS TEST CAN FAIL: a channel holding only an old stray bot message is
left as it is; or the cleanup starts deleting what it preserves.

COUNTER-CHECK (2026-09-29): the first case red before the change, the
second green before and after.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.discord.channel_cleanup_service import ChannelCleanupService

BOT = SimpleNamespace(id=1, name="DDC")


def _message(message_id, days_old, content="Restarted."):
    return SimpleNamespace(id=message_id, author=BOT, content=content, embeds=[],
                           created_at=datetime.now(timezone.utc) - timedelta(days=days_old))


def _channel(messages):
    async def _history(limit=100, **kwargs):
        for message in messages:
            yield message

    async def _purge(limit=100, check=None, **kwargs):
        return [m for m in messages if check(m)]
    return SimpleNamespace(id=77, history=_history, purge=AsyncMock(side_effect=_purge))


@pytest.mark.asyncio
async def test_an_old_stray_bot_message_is_removed():
    service = ChannelCleanupService(SimpleNamespace(user=BOT))
    channel = _channel([_message(10, days_old=60)])
    result = await service.delete_bot_messages_preserve_live_logs(channel, "startup")
    assert channel.purge.await_count == 1 and result.messages_deleted == 1, (
        "a 60-day-old stray bot message survived the cleanup")


@pytest.mark.asyncio
async def test_what_is_preserved_stays():
    service = ChannelCleanupService(SimpleNamespace(user=BOT))
    kept = _message(11, days_old=1, content="kept by its id")
    channel = _channel([kept, _message(12, days_old=1)])
    result = await service.delete_bot_messages_preserve_live_logs(
        channel, "startup", keep_message_ids={11})
    assert result.messages_deleted == 1
