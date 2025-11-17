# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Factory helpers for creating the Discord bot client."""

from __future__ import annotations

import logging

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


def create_bot(runtime: BotRuntime):
    """Create a Discord client using the available API implementation."""

    logger = runtime.logger
    intents = _build_intents()

    try:
        logger.info("Attempting to create bot with discord.Bot (PyCord style)...")
        bot = discord.Bot(intents=intents)
        logger.info("Successfully created bot with discord.Bot")
        return bot
    except (AttributeError, ImportError) as exc:
        logger.warning("Could not create bot with discord.Bot: %s", exc)

    logger.info("Falling back to commands.Bot (discord.py style)...")
    bot = commands.Bot(command_prefix="/", intents=intents)
    logger.info("Successfully created bot with commands.Bot")
    return bot
