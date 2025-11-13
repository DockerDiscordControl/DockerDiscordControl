"""Startup routines for preparing and synchronising bot commands."""

from __future__ import annotations

import asyncio
import inspect

from ..commands import list_registered_command_names, setup_schedule_commands
from ..startup_context import StartupContext, as_step


@as_step
async def load_extensions_step(context: StartupContext) -> None:
    bot = context.bot
    logger = context.logger

    try:
        logger.info("Loading extensions...")
        if "cogs.docker_control" in bot.extensions:
            logger.info("Extension cogs.docker_control already loaded, skipping")
            return

        if inspect.iscoroutinefunction(bot.load_extension):
            await bot.load_extension("cogs.docker_control")
            logger.info(
                "Successfully loaded extension: cogs.docker_control (discord.py async)"
            )
        else:
            bot.load_extension("cogs.docker_control")
            logger.info(
                "Successfully loaded extension: cogs.docker_control (PyCord sync)"
            )
    except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error("Failed to load extension 'cogs.docker_control': %s", exc, exc_info=True)
        raise


@as_step
async def prepare_schedule_commands_step(context: StartupContext) -> None:
    logger = context.logger
    logger.info("Attempting direct registration of schedule commands...")
    setup_schedule_commands(context.bot, logger)


@as_step
async def synchronize_commands_step(context: StartupContext) -> None:
    bot = context.bot
    logger = context.logger

    logger.info("Waiting 2 seconds for all commands to be fully registered...")
    await asyncio.sleep(2)

    logger.info("Synchronizing App Commands after potential Cog registrations...")

    guild_id_str = str(context.runtime.config.get("guild_id", ""))
    if not guild_id_str.isdigit():
        logger.info("No guild ID configured, skipping command synchronization")
        logger.info("App Commands synchronization process completed")
        return

    guild_id = int(guild_id_str)
    logger.info("Synchronizing commands for Guild ID: %s", guild_id)

    command_names = list(list_registered_command_names(bot))
    if command_names:
        logger.info("Found %d commands to sync: %s", len(command_names), command_names)
        schedule_cmds = [name for name in command_names if name.startswith("schedule_")]
        if schedule_cmds:
            logger.info("Schedule commands to sync: %s", schedule_cmds)
        else:
            logger.info("Schedule commands not yet visible in application_commands list.")
            logger.info(
                "This is normal - commands are registered by the Cog and will be available after sync."
            )

    try:
        if hasattr(bot, "sync_commands"):
            logger.info("Attempting to sync commands...")
            await bot.sync_commands(guild_ids=[guild_id])
            logger.info("Commands synchronized successfully")
        else:
            logger.info("Bot implementation does not provide sync_commands; skipping.")
    except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        logger.error("Error syncing commands: %s", sync_error)
        await _fallback_register_commands(bot, logger, guild_id)

    logger.info("App Commands synchronization process completed")


async def _fallback_register_commands(bot, logger, guild_id: int) -> None:
    if not hasattr(bot, "application_commands"):
        logger.error("Fallback registration failed: bot has no application_commands")
        return

    try:
        logger.info("Attempting fallback: registering commands individually")
        for cmd in bot.application_commands:  # pragma: no cover - depends on Discord API
            try:
                await bot.register_commands(guild_id=guild_id, commands=[cmd])
                logger.info("Successfully registered command: %s", cmd.name)
            except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound):
                logger.error("Error registering command %s: %s", cmd.name, cmd_error)
    except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        logger.error("Fallback registration failed: %s", fallback_error)
