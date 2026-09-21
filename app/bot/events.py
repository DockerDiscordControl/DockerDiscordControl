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

    async def _handle_command_error(ctx: Any, error: Exception) -> None:
        """Answer a failed command, whichever event carried it here.

        Registered for BOTH events on purpose. ``on_command_error`` belongs to
        py-cord's PREFIX commands, and DDC has none - ``factory.py`` sets a
        command_prefix, but not one ``@commands.command`` exists in the repo.
        Everything DDC offers is ``@commands.slash_command``, and py-cord sends
        those errors to ``application_command_error`` instead
        (``commands/core.py:483``), where the default handler prints to stderr
        and answers the user not at all (``bot.py:1219``).

        So this handler used to be wired to an event that never fired, and an
        interaction that failed was left hanging: the user saw the command
        thinking, and then nothing. Review C44 read that symptom correctly -
        "they pressed the button and pressed again" - and installed the cure on
        the wrong event (review E14). The cooldowns are real:
        ``dynamic_cooldown_manager.py`` sets ``command._buckets`` on the slash
        commands at startup, which is what py-cord checks before invoking.

        ``on_command_error`` keeps its registration. It costs nothing, and a
        prefix command may exist one day.
        """
        # The donation commands answer their own errors, so this handler must
        # not answer a second time - but that only applies to the branches that
        # RESPOND with an error. A cooldown is the one case where the command
        # has not answered at all, and returning here left the user with no
        # message and no log line: they pressed the button and pressed again
        # (review C44). The exclusion moved below the cooldown branch.
        is_donation_command = (hasattr(ctx, "command")
                               and str(ctx.command) in ["donate", "donatebroadcast"])

        async def answer(message: str) -> None:
            try:
                await ctx.respond(message, ephemeral=True)
            except discord.HTTPException:
                pass
            except discord.ClientException:
                # InteractionResponded: the command already said something.
                # Nothing to add, and nothing wrong.
                pass

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

            await answer(_("This command is on cooldown. Please try again in {duration}.").format(
                duration=time_str.strip()
            ))
            return

        if is_donation_command:
            return

        if isinstance(error, discord.ApplicationCommandError):
            logger.error("Command Error in '%s': %s", ctx.command, error)
            await answer(_("Error during execution: {error}").format(error=error))
        else:
            # This branch used to log and print a traceback and stop there,
            # which was defensible while it could only be reached by a prefix
            # command nobody has. On the slash path it is the branch a DDC
            # exception arrives in - DockerConnectionError out of a status
            # command, say - and leaving the interaction unanswered is the one
            # thing the user always notices (review E14).
            logger.error("Unexpected Command Error in '%s': %s", ctx.command, error,
                         exc_info=True)
            await answer(_("Error during execution: {error}").format(error=error))

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception) -> None:
        await _handle_command_error(ctx, error)

    @bot.event
    async def on_application_command_error(ctx: Any, error: Exception) -> None:
        await _handle_command_error(ctx, error)
