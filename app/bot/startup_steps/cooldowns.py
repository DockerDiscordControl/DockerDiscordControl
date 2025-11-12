"""Startup routines for configuring spam protection cooldowns."""

from __future__ import annotations

from ..startup_context import StartupContext, as_step


@as_step
async def apply_dynamic_cooldowns_step(context: StartupContext) -> None:
    applicator = context.runtime.dependencies.dynamic_cooldown_applicator
    logger = context.logger

    if not applicator:
        logger.info("Dynamic cooldowns not available - using legacy hardcoded cooldowns")
        return

    try:
        logger.info("Applying dynamic cooldowns from spam protection settings...")
        applicator(context.bot)
        logger.info("Dynamic cooldowns applied successfully")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Error applying dynamic cooldowns: %s", exc, exc_info=True)
