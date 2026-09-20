# -*- coding: utf-8 -*-
"""
THE FINDING (review C50, section 28 F6): a message that needs no translation is
not forwarded, because no translation key is configured.

`process_message` resolves the API key and returns `[]` if there is none -
before the per-pair loop runs at all. But that loop contains a path the code
itself describes as needing nothing from a provider:

    else:
        # Attachment-only message — no text to translate, forward as-is
        result = TranslationResult(success=True, translated_text="",
                                   provider="passthrough")

A pair set up purely to mirror screenshots into another channel therefore does
nothing at all until someone enters a DeepL key it will never use. The log says
"No translation API key configured — skipping translation", which is true and
beside the point.

The key is now required where it is actually needed: for a pair that has text
to translate.

The counter-checks keep both other answers: text without a key is still
skipped, with its warning, and a normal translation still happens.
"""

import threading

import pytest

from services.translation import translation_service as ts_mod
from services.translation.translation_service import (
    TranslationContext,
    TranslationResult,
    TranslationService,
)
from services.translation.translation_config_service import (
    ChannelPair,
    TranslationConfigService,
    TranslationSettings,
)

SOURCE = "111111111111111111"
TARGET = "222222222222222222"


class _ConfigService:
    def __init__(self):
        self.counted = []

    @staticmethod
    def get_settings():
        settings = TranslationSettings()
        settings.enabled = True
        settings.api_key_encrypted = None
        settings.api_key_env = "DDC_SPEC_NO_SUCH_ENV"
        return settings

    @staticmethod
    def get_source_channel_ids():
        return {SOURCE}

    @staticmethod
    def get_target_channel_ids():
        return {TARGET}

    @staticmethod
    def get_pairs():
        return [ChannelPair.from_dict({
            "name": "Mirror", "enabled": True,
            "source_channel_id": SOURCE, "target_channel_id": TARGET,
            "target_language": "DE", "source_language": None,
            "translate_embeds": True,
        })]

    def increment_translation_count(self, pair_id):
        self.counted.append(pair_id)


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(ts_mod, "get_translation_config_service", lambda: _ConfigService())
    instance = TranslationService()
    posted = []

    async def _post(bot, pair, context, result, settings=None):
        posted.append((pair.name, result))

    monkeypatch.setattr(instance, "_post_translation", _post)
    instance.posted = posted
    return instance


def _context(content="", attachments=()):
    return TranslationContext(
        message_id="m", channel_id=SOURCE, guild_id="g",
        author_name="Alice", author_avatar_url="",
        content=content, attachment_urls=list(attachments))


ATTACHMENT = [{"url": "https://cdn.example/shot.png", "filename": "shot.png",
               "content_type": "image/png"}]


async def test_an_attachment_only_message_is_forwarded_without_a_key(service):
    """THE FINDING: nothing here needs a translation provider."""
    await service.process_message(_context(attachments=ATTACHMENT), bot_instance=object())

    assert service.posted, "the screenshot was never mirrored"
    assert service.posted[0][1].provider == "passthrough"


async def test_a_text_message_without_a_key_is_still_skipped(service, caplog):
    """COUNTER-CHECK: text really does need a provider."""
    import logging
    with caplog.at_level(logging.WARNING):
        await service.process_message(_context(content="hello"), bot_instance=object())

    assert service.posted == []
    assert any("api key" in r.getMessage().lower() for r in caplog.records)


async def test_a_normal_translation_still_happens(service, monkeypatch):
    """COUNTER-CHECK: with a key, nothing changes."""
    monkeypatch.setattr(service, "_resolve_api_key", lambda settings: "a-key")
    monkeypatch.setattr(service, "_get_provider", lambda settings, key: object())
    monkeypatch.setattr(service, "_get_session", _a_session)

    async def _translate(provider, text, target, source, session):
        return TranslationResult(success=True, translated_text="hallo", provider="deepl")

    monkeypatch.setattr(service, "_translate_with_retry", _translate)

    await service.process_message(_context(content="hello"), bot_instance=object())

    assert service.posted and service.posted[0][1].translated_text == "hallo"


async def _a_session():
    return object()
