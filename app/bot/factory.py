# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Factory helpers for creating the Discord bot client."""

from __future__ import annotations

import discord
from discord.ext import commands

from .runtime import BotRuntime


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.members = True
    intents.presences = False
    intents.typing = False
    intents.message_content = True
    return intents


# THE BOT PINGS NOBODY (audit 2026-09-26). Nothing set allowed_mentions, and
# Discord's default pings everything a message names. The channel translation
# re-posts URLs from other people's messages in the message body, so
# "https://x.com/@everyone" or a role mention glued to a link was re-posted with
# the BOT's permission to ping - by somebody who may not ping there himself.
# DDC mentions nobody on purpose anywhere, so the default is simply: none.
# A message that ever needs one names it in its own allowed_mentions.
NO_PINGS = discord.AllowedMentions.none()


def create_bot(runtime: BotRuntime):
    """Create a Discord client using the available API implementation."""

    logger = runtime.logger
    intents = _build_intents()

    try:
        logger.info("Attempting to create bot with discord.Bot (PyCord style)...")
        bot = discord.Bot(intents=intents, allowed_mentions=NO_PINGS)
        logger.info("Successfully created bot with discord.Bot")
        return bot
    except (AttributeError, ImportError) as exc:
        logger.warning("Could not create bot with discord.Bot: %s", exc)

    logger.info("Falling back to commands.Bot (discord.py style)...")
    bot = commands.Bot(command_prefix="/", intents=intents, allowed_mentions=NO_PINGS)
    logger.info("Successfully created bot with commands.Bot")
    return bot
