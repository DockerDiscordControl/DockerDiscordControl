# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Helpers for managing application command registration."""

from __future__ import annotations

import logging
from typing import Iterable

import discord
import docker


def list_registered_command_names(bot: discord.Bot) -> Iterable[str]:
    if hasattr(bot, "application_commands"):
        return [cmd.name for cmd in bot.application_commands]

    tree = getattr(bot, "tree", None)
    if tree and getattr(tree, "_global_commands", None):
        return list(tree._global_commands.keys())

    return []


def setup_schedule_commands(bot: discord.Bot, logger: logging.Logger) -> bool:
    """Ensure schedule commands are present on the cog."""

    # How the commands get registered is wiring, not news: an operator can
    # do nothing with it either way, and a log he has to triage is a log he
    # stops reading. Somebody debugging registration turns DEBUG on.
    logger.debug("Schedule commands come from the cog; autocomplete is assigned on_ready")

    try:
        if not bot.get_cog("DockerControlCog"):
            logger.error("Could not retrieve DockerControlCog instance for setting up schedule commands")
            return False
    except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error("Error checking DockerControlCog presence: %s", e, exc_info=True)
        return False

    logger.info("Schedule command setup complete (handled by Cog definitions)")
    return True
