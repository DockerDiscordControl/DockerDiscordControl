# -*- coding: utf-8 -*-
"""Channel translation translates people, not other bots or webhooks.

THE FINDING (translation and spam audits, 2026-09-26): the listener skipped
only DDC's own messages and the ones it had posted itself. A second
translation bot in the same channels - or a webhook relay pointed back at a
source channel - answered every DDC translation with its own, which DDC then
translated again: a loop that burns the provider budget as fast as the two
bots can post, and floods the channels with it.

THE OPERATOR'S DECISION (2026-09-26): ignore every other bot and every
webhook; the budget itself stays global.

HOW THIS TEST CAN FAIL: it hands the listener three messages - one from
another bot, one through a webhook, one from a person - and checks which of
them reach the translation service. The person must still get through,
otherwise "translate nothing" would pass the first two cases.

COUNTER-CHECK (2026-09-26): red before on the bot and the webhook case, the
person case green on both sides.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from cogs.translation_monitor import TranslationMonitor


def _monitor():
    monitor = TranslationMonitor.__new__(TranslationMonitor)
    monitor.bot = MagicMock()
    monitor.translation_service = MagicMock()
    monitor.translation_service.is_translated_message = MagicMock(return_value=False)
    monitor.translation_service.process_message = AsyncMock()
    return monitor


def _message(*, bot=False, webhook_id=None):
    message = MagicMock()
    message.author.bot = bot
    message.webhook_id = webhook_id
    message.embeds = []
    message.attachments = []
    message.content = "Hallo zusammen"
    return message


def _forwarded(message):
    monitor = _monitor()
    asyncio.run(monitor.on_message(message))
    return monitor.translation_service.process_message.await_count


def test_another_bot_is_not_translated():
    assert _forwarded(_message(bot=True)) == 0, (
        "a message of another bot went to the translation provider")


def test_a_webhook_is_not_translated():
    assert _forwarded(_message(webhook_id=1234)) == 0, (
        "a webhook message went to the translation provider")


def test_a_person_is_still_translated():
    assert _forwarded(_message()) == 1, (
        "the everyday case: a person's message must still be translated")
