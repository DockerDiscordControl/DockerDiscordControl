"""Startup orchestration for the Discord bot."""

from __future__ import annotations

import discord

from .runtime import BotRuntime
from .startup_context import StartupContext
from .startup_steps import STARTUP_STEPS, run_startup_sequence


class StartupManager:
    """Coordinate the expensive initialization routines once the bot is ready."""

    def __init__(self, bot: discord.Bot, runtime: BotRuntime):
        self._context = StartupContext(bot=bot, runtime=runtime)
        self._initial_startup_done = False

    async def handle_ready(self) -> None:
        logger = self._context.logger

        if self._initial_startup_done:
            logger.info("DDC is ready.")
            return

        logger.info("First initialization after start...")

        await run_startup_sequence(self._context, STARTUP_STEPS)

        self._initial_startup_done = True
        logger.info("Initialization complete.")
        logger.info("DDC is ready.")
