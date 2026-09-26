# -*- coding: utf-8 -*-
"""A translation that was cut short ends in "…".

THE FINDING (translation audit, 2026-09-26, #11): a message longer than the
max_text_length setting was cut before it went to the provider, and a
translation longer than an embed allows (4096) was cut before it was posted -
both without a trace. The reader of the target channel saw a text that
simply stopped, mid-sentence, and had no way to know that more existed.

HOW THIS TEST CAN FAIL: it translates a message over the length setting and
posts a translation over the embed limit; both must end in "…" and stay
within their limit. A short message must come through untouched.

COUNTER-CHECK (2026-09-26): red before on both long cases; the short one
green on both sides.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

SOURCE = "111111111111111111"
TARGET = "222222222222222222"


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATION_API_KEY", "live-key")
    import services.translation.translation_service as ts
    from services.translation.translation_config_service import TranslationConfigService

    config = TranslationConfigService()
    config.update_settings({"provider": "deepl", "enabled": True,
                            "rate_limit_per_minute": 60, "max_text_length": 100})
    config.add_pair({"name": "P", "enabled": True, "source_channel_id": SOURCE,
                     "target_channel_id": TARGET, "target_language": "DE"})
    monkeypatch.setattr(ts, "get_translation_config_service", lambda: config)
    svc = ts.TranslationService()
    svc._get_session = AsyncMock(return_value=MagicMock())
    channel = MagicMock()
    channel.guild = None
    channel.send = AsyncMock(return_value=MagicMock(id=42))
    bot = MagicMock()
    bot.get_channel = lambda _cid: channel
    return svc, ts, bot, channel


def _run(service, content, translated=None):
    svc, ts, bot, channel = service
    sent_to_provider = []

    async def translate(provider, text, target, source, session):
        sent_to_provider.append(text)
        return ts.TranslationResult(success=True, translated_text=translated or text.upper(),
                                    detected_language="EN", provider="DeepL")

    svc._translate_with_retry = translate
    context = ts.TranslationContext(message_id="m1", channel_id=SOURCE, guild_id="g1",
                                    author_name="A", author_avatar_url="", content=content)
    asyncio.run(svc.process_message(context, bot))
    return sent_to_provider, channel.send.await_args.kwargs["embed"].description


def test_a_message_over_the_length_setting_ends_in_an_ellipsis(service):
    sent, posted = _run(service, "word " * 60)
    assert len(sent[0]) <= 100
    assert posted.endswith("…"), f"the cut translation just stops: {posted[-20:]!r}"


def test_a_translation_over_the_embed_limit_ends_in_an_ellipsis(service):
    _sent, posted = _run(service, "short", translated="x" * 5000)
    assert len(posted) <= 4096
    assert posted.endswith("…"), "the cut embed text just stops"


def test_a_short_message_is_untouched(service):
    _sent, posted = _run(service, "hello there")
    assert posted == "HELLO THERE"
