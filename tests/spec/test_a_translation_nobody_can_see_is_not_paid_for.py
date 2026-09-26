# -*- coding: utf-8 -*-
"""A translation is paid for only when it can be posted, and a big file is linked.

THE FINDINGS (translation audit, 2026-09-26):

#4 - process_message called the provider first and looked for the target
channel only inside _post_translation. A pair whose target channel was
deleted, or where the bot had lost "Send Messages", sent every message to
DeepL anyway - paid characters for a post that never happened - and then
counted it as translated in the panel.

#5 - every video and image was downloaded IN FULL before its size was looked
at: a 500 MB video posted in a source channel was read into memory, then
dropped for being over 25 MB. Discord says how big an attachment is before
anybody downloads it.

HOW THIS TEST CAN FAIL: it runs a pair whose target channel is gone (the
provider must not be called, nothing counted), one whose bot may not post
(the same), and forwards an attachment larger than the target guild allows
(it must be linked, not downloaded). The ordinary pair must still be
translated and counted, and a small attachment still uploaded.

COUNTER-CHECK (2026-09-26): red before on both channel cases and on the big
file; the ordinary cases green on both sides.
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
                            "rate_limit_per_minute": 60, "max_text_length": 5000})
    pair = config.add_pair({"name": "P", "enabled": True, "source_channel_id": SOURCE,
                            "target_channel_id": TARGET, "target_language": "DE"}).data
    monkeypatch.setattr(ts, "get_translation_config_service", lambda: config)
    svc = ts.TranslationService()
    svc._translate_with_retry = AsyncMock(return_value=ts.TranslationResult(
        success=True, translated_text="Hallo", detected_language="EN", provider="DeepL"))
    svc._get_session = AsyncMock(return_value=MagicMock())
    return svc, config, pair


def _context(**extra):
    from services.translation.translation_service import TranslationContext

    return TranslationContext(message_id="m1", channel_id=SOURCE, guild_id="g1",
                              author_name="Alice", author_avatar_url="", content="Hello",
                              **extra)


def _channel(*, may_send=True, upload_limit=25 * 1024 * 1024):
    channel = MagicMock()
    channel.permissions_for.return_value = MagicMock(send_messages=may_send)
    channel.guild.filesize_limit = upload_limit
    channel.send = AsyncMock(return_value=MagicMock(id=42))
    return channel


def _bot(channel):
    bot = MagicMock()
    bot.get_channel = lambda _cid: channel
    return bot


def _count(config, pair):
    return next(p for p in config.get_pairs() if p.id == pair.id).metadata.get("translation_count", 0)


def test_a_gone_target_channel_costs_nothing(service):
    svc, config, pair = service
    asyncio.run(svc.process_message(_context(), _bot(None)))

    assert svc._translate_with_retry.await_count == 0, (
        "the provider was paid for a channel that does not exist")
    assert _count(config, pair) == 0, "a translation nobody saw was counted"


def test_a_target_without_send_permission_costs_nothing(service):
    svc, config, pair = service
    asyncio.run(svc.process_message(_context(), _bot(_channel(may_send=False))))

    assert svc._translate_with_retry.await_count == 0
    assert _count(config, pair) == 0


def test_an_ordinary_pair_is_translated_and_counted(service):
    svc, config, pair = service
    channel = _channel()
    asyncio.run(svc.process_message(_context(), _bot(channel)))

    assert channel.send.await_count == 1
    assert _count(config, pair) == 1


def _session(downloads):
    class _Response:
        status = 200

        def __init__(self):
            self.content = MagicMock()
            self.content.read = AsyncMock(return_value=b"x" * 10)

        async def read(self):
            return b"x" * 10

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    session = MagicMock()

    def get(url, **_kwargs):
        downloads.append(url)
        return _Response()

    session.get = get
    return session


def test_a_file_over_the_upload_limit_is_linked_not_downloaded(service):
    svc, _config, _pair = service
    downloads = []
    svc._get_session = AsyncMock(return_value=_session(downloads))
    channel = _channel(upload_limit=8 * 1024 * 1024)
    big = {"url": "https://cdn.example/big.mp4", "filename": "big.mp4",
           "content_type": "video/mp4", "size": 500 * 1024 * 1024}

    asyncio.run(svc.process_message(_context(attachment_urls=[big]), _bot(channel)))

    assert downloads == [], "a 500 MB video was downloaded to find out it is too big"
    assert "big.mp4" in str(channel.send.await_args), "the big file was dropped, not linked"


def test_a_small_file_is_still_uploaded(service):
    svc, _config, _pair = service
    downloads = []
    svc._get_session = AsyncMock(return_value=_session(downloads))
    channel = _channel()
    small = {"url": "https://cdn.example/clip.mp4", "filename": "clip.mp4",
             "content_type": "video/mp4", "size": 10}

    asyncio.run(svc.process_message(_context(attachment_urls=[small]), _bot(channel)))

    assert downloads == ["https://cdn.example/clip.mp4"]
    assert channel.send.await_args.kwargs.get("files"), "the small file was not uploaded"
