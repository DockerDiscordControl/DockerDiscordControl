"""Startup routines for optional update notifications."""

from __future__ import annotations

from ..startup_context import StartupContext, as_step


@as_step
async def send_update_notification_step(context: StartupContext) -> None:
    notifier_factory = context.runtime.dependencies.update_notifier_factory
    logger = context.logger

    if not notifier_factory:
        logger.debug("Update notifier not available - skipping update notifications")
        return

    try:
        logger.info("Checking for update notifications...")
        notifier = notifier_factory()
        if await notifier.send_update_notification(context.bot):  # pragma: no cover - network
            logger.info("Update notification sent successfully")
        else:
            logger.debug("No update notification needed")
    except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        logger.error("Error sending update notification: %s", exc, exc_info=True)
