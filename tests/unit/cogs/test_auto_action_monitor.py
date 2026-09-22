#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Unit tests for the AutoActionMonitor cog (cogs/auto_action_monitor.py).

This listener sees *every* message in every guild the bot is in, so its guard
clauses matter: a mistake here either floods the automation service or makes
auto-actions stop reacting entirely.

Covered:
- loop protection (the bot's own messages are ignored)
- DMs are ignored (no guild)
- the TriggerContext passed on carries content, ids and flattened embed text
- webhook messages are marked as such (auto-action rules can filter on it)
- a failing automation service never propagates out of the listener

The cog is built with object.__new__ to bypass __init__, which would call
get_automation_service() and touch real state.
"""

import logging

import pytest
from unittest.mock import AsyncMock, MagicMock

from cogs.auto_action_monitor import AutoActionMonitor


def _make_cog():
    """Build an AutoActionMonitor without running __init__."""
    cog = object.__new__(AutoActionMonitor)
    cog.bot = MagicMock()
    cog.bot.user = MagicMock()  # identity comparison in the loop guard
    cog.automation_service = MagicMock()
    cog.automation_service.process_message = AsyncMock()
    return cog


def _make_message(*, author=None, guild=True, content="hello", embeds=(), webhook_id=None):
    msg = MagicMock()
    if author is None:
        # A MagicMock, not object(): the latter has no __dict__, so attributes can't be set,
        # and MagicMock compares by identity, which is what the loop guard relies on.
        author = MagicMock()
        author.id = 3003
        author.name = "tester"
    msg.author = author
    msg.guild = MagicMock() if guild else None
    if guild:
        msg.guild.id = 4242
    msg.content = content
    msg.embeds = list(embeds)
    msg.webhook_id = webhook_id
    msg.id = 1001
    msg.channel.id = 2002
    return msg


def _make_embed(*, title=None, description=None, footer_text=None, fields=()):
    embed = MagicMock()
    embed.title = title
    embed.description = description
    if footer_text is None:
        embed.footer = None
    else:
        embed.footer = MagicMock()
        embed.footer.text = footer_text
    embed.fields = [MagicMock(name=n, value=v) for n, v in fields]
    for field, (n, v) in zip(embed.fields, fields):
        field.name = n
        field.value = v
    return embed


# ---------------------------------------------------------------------------
# Guard clauses
# ---------------------------------------------------------------------------

class TestGuards:
    async def test_own_message_is_ignored(self):
        """Loop protection: reacting to our own output could trigger endlessly."""
        cog = _make_cog()
        msg = _make_message(author=cog.bot.user)
        await cog.on_message(msg)
        cog.automation_service.process_message.assert_not_awaited()

    async def test_direct_message_is_ignored(self):
        cog = _make_cog()
        await cog.on_message(_make_message(guild=False))
        cog.automation_service.process_message.assert_not_awaited()

    async def test_regular_guild_message_is_forwarded(self):
        cog = _make_cog()
        await cog.on_message(_make_message())
        cog.automation_service.process_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# TriggerContext content
# ---------------------------------------------------------------------------

class TestTriggerContext:
    async def _context_for(self, msg):
        cog = _make_cog()
        await cog.on_message(msg)
        ctx, bot = cog.automation_service.process_message.await_args.args
        assert bot is cog.bot, "the service needs the bot to send feedback messages"
        return ctx

    async def test_ids_and_content_are_strings(self):
        ctx = await self._context_for(_make_message(content="server is up"))
        assert ctx.content == "server is up"
        assert (ctx.message_id, ctx.channel_id, ctx.guild_id, ctx.user_id) == \
               ("1001", "2002", "4242", "3003")
        assert ctx.username == "tester"

    async def test_message_without_embeds_has_empty_embed_text(self):
        ctx = await self._context_for(_make_message())
        assert ctx.embeds_text == ""

    async def test_embed_title_description_footer_and_fields_are_flattened(self):
        """Most game-server bots post status in embeds, not in message content."""
        embed = _make_embed(
            title="Valheim",
            description="Server online",
            footer_text="updated just now",
            fields=(("Players", "3/8"), ("Version", "0.217.46")),
        )
        ctx = await self._context_for(_make_message(content="", embeds=[embed]))
        lines = ctx.embeds_text.split("\n")
        assert lines == [
            "Valheim",
            "Server online",
            "updated just now",
            "Players 3/8",
            "Version 0.217.46",
        ]

    async def test_empty_embed_parts_are_skipped(self):
        embed = _make_embed(title=None, description="only this", footer_text=None)
        ctx = await self._context_for(_make_message(embeds=[embed]))
        assert ctx.embeds_text == "only this"

    async def test_several_embeds_are_concatenated(self):
        first = _make_embed(title="one")
        second = _make_embed(title="two")
        ctx = await self._context_for(_make_message(embeds=[first, second]))
        assert ctx.embeds_text == "one\ntwo"

    @pytest.mark.parametrize("webhook_id, expected", [(None, False), (98765, True)])
    async def test_webhook_flag(self, webhook_id, expected):
        """Rules can require a webhook source; the flag must survive as a bool."""
        ctx = await self._context_for(_make_message(webhook_id=webhook_id))
        assert ctx.is_webhook is expected


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    async def test_service_failure_is_logged_and_swallowed(self, caplog):
        """An exception escaping the listener would take down the whole on_message chain."""
        cog = _make_cog()
        cog.automation_service.process_message = AsyncMock(
            side_effect=RuntimeError("docker unreachable")
        )
        with caplog.at_level(logging.ERROR):
            await cog.on_message(_make_message())  # must not raise
        assert any("docker unreachable" in r.getMessage() for r in caplog.records)

    async def test_broken_embed_does_not_break_the_listener(self):
        """A malformed embed from another bot must not stop message processing."""
        cog = _make_cog()
        embed = MagicMock()
        type(embed).title = property(lambda self: (_ for _ in ()).throw(AttributeError("boom")))
        msg = _make_message(embeds=[embed])
        await cog.on_message(msg)  # must not raise
        cog.automation_service.process_message.assert_not_awaited()
