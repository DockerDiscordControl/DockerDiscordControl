# -*- coding: utf-8 -*-
"""
THE FINDING (review C12, section 28 F1): a forwarded message loses every image
attachment after the first, without a word.

`_post_translation` puts the FIRST image attachment into the embed and sets
`image_set = True`. The later loop that downloads and re-uploads attachments
asks

    if ct.startswith('video/') or (ct.startswith('image/') and not image_set):
        ...download and attach...
    elif not ct.startswith('image/'):
        ...link it in the message text...

For the second image both conditions are false: it is not a video, `image_set`
is long since True, and it IS an image, so the `elif` does not take it either.
It is not embedded, not uploaded, not linked, not logged. It is simply gone
from the translated post, and nothing in the target channel or the log says a
picture was left behind.

`image_set` is a flag about a DIFFERENT loop. What the second loop needs to
know is not "was any image embedded" but "is THIS the attachment that was
embedded" - which is why the fix compares the URL.

The counter-check (test_the_embedded_image_is_not_uploaded_a_second_time)
holds the other end: the picture in the embed must not also arrive as a file.
"""

import threading
from unittest.mock import AsyncMock, MagicMock

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


class _Response:
    def __init__(self, status=200, data=b"x" * 10):
        self.status = status
        self._data = data

    async def read(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    """Answers every download with a small, valid body."""

    def __init__(self):
        self.get_urls = []

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        return _Response()


@pytest.fixture
def service(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    config_service = TranslationConfigService.__new__(TranslationConfigService)
    config_service.base_dir = tmp_path
    config_service.config_file = cfg_dir / "channel_translations.json"
    config_service._lock = threading.RLock()
    config_service._config_cache = None
    monkeypatch.setattr(ts_mod, "get_translation_config_service", lambda: config_service)
    return TranslationService()


@pytest.fixture
def sent(service, monkeypatch):
    """Capture exactly what reaches target_channel.send()."""
    message = MagicMock()
    message.id = 999
    channel = MagicMock()
    channel.send = AsyncMock(return_value=message)
    del channel.guild  # skip the permission gate
    bot = MagicMock()
    bot.get_channel.return_value = channel

    session = _Session()
    monkeypatch.setattr(service, "_get_session", AsyncMock(return_value=session))
    return bot, channel, session


ATTACHMENTS = [
    {"url": "https://cdn.example/first.jpg", "filename": "first.jpg",
     "content_type": "image/jpeg"},
    {"url": "https://cdn.example/second.jpg", "filename": "second.jpg",
     "content_type": "image/jpeg"},
    {"url": "https://cdn.example/third.png", "filename": "third.png",
     "content_type": "image/png"},
    {"url": "https://cdn.example/clip.mp4", "filename": "clip.mp4",
     "content_type": "video/mp4"},
    {"url": "https://cdn.example/notes.pdf", "filename": "notes.pdf",
     "content_type": "application/pdf"},
]


def _pair():
    return ChannelPair.from_dict({
        "name": "Pair-A", "enabled": True,
        "source_channel_id": "111111111111111111",
        "target_channel_id": "222222222222222222",
        "target_language": "DE", "source_language": None,
        "translate_embeds": True,
    })


async def _post(service, bot, attachments):
    context = TranslationContext(
        message_id="m", channel_id="c", guild_id="g",
        author_name="Alice", author_avatar_url="https://x/a.png",
        content="look at these",
        attachment_urls=list(attachments),
    )
    result = TranslationResult(success=True, translated_text="Sieh dir das an",
                               detected_language="EN", provider="DeepL")
    await service._post_translation(bot, _pair(), context, result,
                                    TranslationSettings())


def _what_arrived(channel):
    """Everything the target channel was told about, as one blob of text."""
    kwargs = channel.send.await_args.kwargs
    parts = [kwargs.get('content') or ""]
    for file_obj in kwargs.get('files') or []:
        parts.append(file_obj.filename)
    embed = kwargs.get('embed')
    if embed is not None and embed.image:
        parts.append(embed.image.url or "")
    return " ".join(parts)


async def test_every_attachment_reaches_the_target(service, sent):
    """THE FINDING: nothing an attachment carried may vanish in silence."""
    bot, channel, _session = sent

    await _post(service, bot, ATTACHMENTS)

    arrived = _what_arrived(channel)
    missing = [a['filename'] for a in ATTACHMENTS
               if a['filename'] not in arrived and a['url'] not in arrived]
    assert missing == []


async def test_the_second_image_is_not_lost(service, sent):
    """The narrow case from the report, stated on its own: two images."""
    bot, channel, _session = sent

    await _post(service, bot, ATTACHMENTS[:2])

    arrived = _what_arrived(channel)
    assert "second.jpg" in arrived or "https://cdn.example/second.jpg" in arrived


async def test_the_embedded_image_is_not_uploaded_a_second_time(service, sent):
    """COUNTER-CHECK: the fix must not turn into "upload everything". The
    picture already shown in the embed is not downloaded and sent again."""
    bot, channel, session = sent

    await _post(service, bot, ATTACHMENTS)

    assert "https://cdn.example/first.jpg" not in session.get_urls
    filenames = [f.filename for f in (channel.send.await_args.kwargs.get('files') or [])]
    assert "first.jpg" not in filenames
