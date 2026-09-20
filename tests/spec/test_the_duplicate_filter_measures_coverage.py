# -*- coding: utf-8 -*-
"""
REFUTED (review C49, section 28 F7) - and the comment corrected.

The report said `_build_translation_text` drops an embed as a duplicate without
the coverage check its comment promises:

    # Only filter if embed text covers >50% of content (real duplicate)
    if content_lower and len(et_lower) > 20 and et_lower in content_lower:

The comment is indeed wrong - there is no ratio anywhere. But the behaviour is
not. `et_lower in content_lower` requires the WHOLE embed text to be inside the
message, and in that case dropping it loses nothing: every character of it is
already in the message, which is part one of the text being translated. There
is no input where the old condition throws away something that is not already
there, so no waiting test could be red for it.

The comment now says what the code does. THESE TESTS ARE CHARACTERISATION, NOT
A FIX: they were green before the change and are green after it. They exist so
the comment and the code cannot drift apart again - the drift is what the
reviewer actually found.
"""

import threading

import pytest

from services.translation import translation_service as ts_mod
from services.translation.translation_service import (
    TranslationContext,
    TranslationService,
)
from services.translation.translation_config_service import (
    ChannelPair,
    TranslationConfigService,
)


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


def _pair():
    return ChannelPair.from_dict({
        "name": "Pair-A", "enabled": True,
        "source_channel_id": "111111111111111111",
        "target_channel_id": "222222222222222222",
        "target_language": "DE", "source_language": None,
        "translate_embeds": True,
    })


def _context(content, embed_texts):
    return TranslationContext(
        message_id="m", channel_id="c", guild_id="g",
        author_name="Alice", author_avatar_url="",
        content=content, embed_texts=embed_texts)


def test_a_dropped_embed_never_takes_text_with_it(service):
    """The heart of the refutation: what is dropped is already in the message.

    A short embed quoted inside a long message IS dropped - and every character
    of it is still in the text being translated.
    """
    quoted = "the server is now online!"          # 25 characters, > the 20 limit
    content = "Morning everyone. " + quoted + " " + ("Details follow. " * 120)

    text = service._build_translation_text(_context(content, [quoted]), _pair())

    assert quoted in text
    assert text.count(quoted) == 1, "kept twice - the filter did not work"


def test_an_embed_with_anything_of_its_own_is_kept(service):
    """The case the report feared: it cannot happen. An embed that says
    ANYTHING beyond the message is no longer a substring of it, so the filter
    does not touch it."""
    quoted = "the server is now online!"
    content = "Morning everyone. " + quoted + " " + ("Details follow. " * 120)
    embed_text = quoted + " Maintenance window: 02:00-04:00 UTC."

    text = service._build_translation_text(_context(content, [embed_text]), _pair())

    assert "Maintenance window" in text


def test_a_short_embed_below_the_limit_is_kept(service):
    """Under 20 characters the filter never runs at all."""
    text = service._build_translation_text(_context("hello there", ["hello"]), _pair())

    assert text.count("hello") == 2


def test_an_unrelated_embed_is_kept(service):
    """And an embed that shares nothing with the message is never in question."""
    text = service._build_translation_text(
        _context("Hello everyone", ["Completely different announcement"]), _pair())

    assert "Hello everyone" in text and "Completely different" in text
