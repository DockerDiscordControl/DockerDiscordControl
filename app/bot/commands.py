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

    logger.info("MANUAL REGISTRATION IN setup_schedule_commands IS CURRENTLY DISABLED FOR TESTING.")
    logger.info("Relying on Cog registration and on_ready autocomplete assignment.")

    try:
        if not bot.get_cog("DockerControlCog"):
            logger.error("Could not retrieve DockerControlCog instance for setting up schedule commands")
            return False
    except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error("Error checking DockerControlCog presence: %s", e, exc_info=True)
        return False

    logger.info("Schedule command setup complete (handled by Cog definitions)")
    return True
