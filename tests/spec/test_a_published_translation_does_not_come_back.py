# -*- coding: utf-8 -*-
"""A translation that comes back through a followed channel is not translated again.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F12): posts from
a followed announcement channel pass the bot filter - they arrive through a
webhook, and Discord marks them IS_CROSSPOST (operator, 2026-09-27). If a DDC
TARGET channel is an announcement channel whose posts get published (by a
person or an auto-publish bot) and a DDC SOURCE channel follows it, DDC's own
translation comes back as a crosspost with a new message id - and is
translated again, round after round.

THE OPERATOR (2026-09-29): DDC guards against it.

THE CONTRACT: Discord gives a crosspost a reference to the message it copies.
When that original is a message DDC posted as a translation, the crosspost is
dropped; any other crosspost is still translated.

HOW THIS TEST CAN FAIL: the returning translation reaches the provider again;
or the guard overreaches and followed news from another server stops.

COUNTER-CHECK (2026-09-29): the first case was red before the change, the
second green before and after.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from cogs.translation_monitor import TranslationMonitor

OURS = "555"


def _forwarded(reference_id):
    monitor = TranslationMonitor.__new__(TranslationMonitor)
    monitor.bot = MagicMock()
    monitor.translation_service = MagicMock()
    monitor.translation_service.is_translated_message = lambda message_id: message_id == OURS
    monitor.translation_service.process_message = AsyncMock()
    message = MagicMock()
    message.id = 9001
    message.author.bot = True
    message.webhook_id = 1234
    message.flags.is_crossposted = True
    message.reference.message_id = reference_id
    message.embeds = []
    message.attachments = []
    message.content = "Hello everyone"
    asyncio.run(monitor.on_message(message))
    return monitor.translation_service.process_message.await_count


def test_our_own_translation_coming_back_is_dropped():
    assert _forwarded(int(OURS)) == 0, (
        "DDC's own translation came back through a followed channel and was translated again")


def test_news_from_another_server_is_still_translated():
    assert _forwarded(777) == 1, "a followed post of someone else was dropped"
