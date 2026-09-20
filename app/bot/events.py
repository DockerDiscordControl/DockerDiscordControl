# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Event wiring for the Discord bot."""

from __future__ import annotations

import traceback
from typing import Any

import discord
from discord.ext import commands

from cogs.translation_manager import _

from .runtime import BotRuntime
from .startup import StartupManager


def register_event_handlers(bot: discord.Bot, runtime: BotRuntime) -> None:
    """Attach the core event handlers to the bot instance."""

    startup_manager = StartupManager(bot, runtime)
    logger = runtime.logger

    @bot.event
    async def on_ready():
        logger.info("-" * 50)
        user = getattr(bot, "user", None)
        if user is not None:
            logger.info("Logged in as %s (ID: %s)", user.name, user.id)
        else:
            logger.info("Logged in (user unavailable during startup)")
        logger.info("discord.py Version: %s", discord.__version__)
        logger.info("-" * 50)

        await startup_manager.handle_ready()

    @bot.event
    async def on_error(event: str, *args: Any, **kwargs: Any) -> None:
        logger.error("Error in event %s: %s", event, traceback.format_exc())

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception) -> None:
        # The donation commands answer their own errors, so this handler must
        # not answer a second time - but that only applies to the branches that
        # RESPOND with an error. A cooldown is the one case where the command
        # has not answered at all, and returning here left the user with no
        # message and no log line: they pressed the button and pressed again
        # (review C44). The exclusion moved below the cooldown branch.
        is_donation_command = (hasattr(ctx, "command")
                               and str(ctx.command) in ["donate", "donatebroadcast"])

        if isinstance(error, commands.CommandOnCooldown):
            seconds = error.retry_after
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            time_str = ""
            if hours > 0:
                time_str += f"{int(hours)}h "
            if minutes > 0:
                time_str += f"{int(minutes)}m "
            if seconds > 0 or not time_str:
                time_str += f"{seconds:.2f}s"

            message = _("This command is on cooldown. Please try again in {duration}.").format(
                duration=time_str.strip()
            )
            try:
                await ctx.respond(message, ephemeral=True)
            except discord.HTTPException:
                pass
            return

        if is_donation_command:
            return

        if isinstance(error, discord.ApplicationCommandError):
            logger.error("Command Error in '%s': %s", ctx.command, error)
            try:
                await ctx.respond(
                    _("Error during execution: {error}").format(error=error), ephemeral=True
                )
            except discord.HTTPException:
                pass
        else:
            logger.error("Unexpected Command Error in '%s': %s", ctx.command, error)
            traceback.print_exc()
