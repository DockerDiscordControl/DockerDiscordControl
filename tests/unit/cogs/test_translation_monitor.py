#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Unit tests for the TranslationMonitor cog (cogs/translation_monitor.py).

Like the auto-action listener this sees every message in every guild, and it has
one extra guard that matters a lot: it must not translate its own translations,
or a source channel and its target would feed each other forever.

Covered:
- loop protection (own messages, and messages the service already posted)
- DMs are ignored
- the TranslationContext carries ids, author, content, embeds and attachments
- embed images fall back from image to thumbnail
- attachments keep url/filename and tolerate a missing content type
- a failing translation service never propagates out of the listener

The cog is built with object.__new__ to bypass __init__, which would call
get_translation_service().
"""

import logging

import pytest
from unittest.mock import AsyncMock, MagicMock

from cogs.translation_monitor import TranslationMonitor


def _make_cog(already_translated=False):
    cog = object.__new__(TranslationMonitor)
    cog.bot = MagicMock()
    cog.bot.user = MagicMock()
    cog.translation_service = MagicMock()
    cog.translation_service.is_translated_message = MagicMock(return_value=already_translated)
    cog.translation_service.process_message = AsyncMock()
    return cog


def _make_message(*, author=None, guild=True, content="hello", embeds=(), attachments=()):
    msg = MagicMock()
    if author is None:
        author = MagicMock()
        author.display_name = "Alice"
        author.display_avatar.url = "https://cdn.example/avatar.png"
    msg.author = author
    msg.guild = MagicMock() if guild else None
    if guild:
        msg.guild.id = 4242
    msg.content = content
    msg.embeds = list(embeds)
    msg.attachments = list(attachments)
    msg.id = 1001
    msg.channel.id = 2002
    return msg


def _make_embed(*, title=None, description=None, footer_text=None, fields=(),
                image_url=None, thumbnail_url=None):
    embed = MagicMock()
    embed.title = title
    embed.description = description
    if footer_text is None:
        embed.footer = None
    else:
        embed.footer = MagicMock()
        embed.footer.text = footer_text

    embed.fields = []
    for name, value in fields:
        field = MagicMock()
        field.name = name
        field.value = value
        embed.fields.append(field)

    if image_url is None:
        embed.image = None
    else:
        embed.image = MagicMock()
        embed.image.url = image_url

    if thumbnail_url is None:
        embed.thumbnail = None
    else:
        embed.thumbnail = MagicMock()
        embed.thumbnail.url = thumbnail_url
    return embed


def _make_attachment(url, filename, content_type):
    att = MagicMock()
    att.url = url
    att.filename = filename
    att.content_type = content_type
    return att


async def _context_for(cog, msg):
    await cog.on_message(msg)
    ctx, bot = cog.translation_service.process_message.await_args.args
    assert bot is cog.bot
    return ctx


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

class TestGuards:
    async def test_own_message_is_ignored(self):
        cog = _make_cog()
        await cog.on_message(_make_message(author=cog.bot.user))
        cog.translation_service.process_message.assert_not_awaited()

    async def test_direct_message_is_ignored(self):
        cog = _make_cog()
        await cog.on_message(_make_message(guild=False))
        cog.translation_service.process_message.assert_not_awaited()

    async def test_already_translated_message_is_ignored(self):
        """Without this the target channel would be translated back into the source."""
        cog = _make_cog(already_translated=True)
        await cog.on_message(_make_message())
        cog.translation_service.process_message.assert_not_awaited()

    async def test_the_message_id_is_what_gets_checked(self):
        cog = _make_cog()
        await cog.on_message(_make_message())
        cog.translation_service.is_translated_message.assert_called_once_with("1001")

    async def test_regular_message_is_forwarded(self):
        cog = _make_cog()
        await cog.on_message(_make_message())
        cog.translation_service.process_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# TranslationContext
# ---------------------------------------------------------------------------

class TestTranslationContext:
    async def test_ids_author_and_content(self):
        cog = _make_cog()
        ctx = await _context_for(cog, _make_message(content="hi there"))
        assert (ctx.message_id, ctx.channel_id, ctx.guild_id) == ("1001", "2002", "4242")
        assert ctx.author_name == "Alice"
        assert ctx.author_avatar_url == "https://cdn.example/avatar.png"
        assert ctx.content == "hi there"

    async def test_message_without_extras_has_empty_lists(self):
        cog = _make_cog()
        ctx = await _context_for(cog, _make_message())
        assert ctx.embed_texts == []
        assert ctx.embed_images == []
        assert ctx.attachment_urls == []

    async def test_embed_text_parts_are_collected(self):
        cog = _make_cog()
        embed = _make_embed(title="Update", description="Server restarted",
                            footer_text="just now",
                            fields=(("Status", "online"),))
        ctx = await _context_for(cog, _make_message(embeds=[embed]))
        assert ctx.embed_texts == ["Update", "Server restarted", "just now", "Status: online"]

    async def test_field_without_name_keeps_only_the_value(self):
        cog = _make_cog()
        embed = _make_embed(fields=((None, "bare value"),))
        ctx = await _context_for(cog, _make_message(embeds=[embed]))
        assert ctx.embed_texts == ["bare value"]

    async def test_field_without_value_is_skipped(self):
        cog = _make_cog()
        embed = _make_embed(fields=(("Empty", ""),))
        ctx = await _context_for(cog, _make_message(embeds=[embed]))
        assert ctx.embed_texts == []

    async def test_embed_image_is_preferred_over_thumbnail(self):
        cog = _make_cog()
        embed = _make_embed(image_url="https://img/full.png",
                            thumbnail_url="https://img/thumb.png")
        ctx = await _context_for(cog, _make_message(embeds=[embed]))
        assert ctx.embed_images == ["https://img/full.png"]

    async def test_thumbnail_is_used_when_there_is_no_image(self):
        cog = _make_cog()
        embed = _make_embed(thumbnail_url="https://img/thumb.png")
        ctx = await _context_for(cog, _make_message(embeds=[embed]))
        assert ctx.embed_images == ["https://img/thumb.png"]


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

class TestAttachments:
    async def test_attachments_are_mapped(self):
        cog = _make_cog()
        att = _make_attachment("https://cdn/a.png", "a.png", "image/png")
        ctx = await _context_for(cog, _make_message(attachments=[att]))
        assert ctx.attachment_urls == [
            {"url": "https://cdn/a.png", "filename": "a.png", "content_type": "image/png"}
        ]

    async def test_missing_content_type_becomes_empty_string(self):
        """Discord leaves content_type unset for some uploads; None must not leak through."""
        cog = _make_cog()
        att = _make_attachment("https://cdn/b.bin", "b.bin", None)
        ctx = await _context_for(cog, _make_message(attachments=[att]))
        assert ctx.attachment_urls[0]["content_type"] == ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    async def test_service_failure_is_logged_and_swallowed(self, caplog):
        cog = _make_cog()
        cog.translation_service.process_message = AsyncMock(
            side_effect=RuntimeError("translation API down")
        )
        with caplog.at_level(logging.ERROR):
            await cog.on_message(_make_message())  # must not raise
        assert any("translation API down" in r.getMessage() for r in caplog.records)
