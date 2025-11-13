# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Entry point for the DockerDiscordControl Discord bot."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import pytz

# Fix for audioop module in Python 3.13
try:
    import audioop  # type: ignore
except ImportError:  # pragma: no cover - import shim only used on specific platforms
    import audioop_lts as audioop  # type: ignore

sys.modules["audioop"] = audioop

import discord

from app.bootstrap import configure_environment, load_main_configuration
from app.bot import build_runtime, create_bot, get_decrypted_bot_token, register_event_handlers
from services.scheduling.scheduler_service import stop_scheduler_service
from utils.app_commands_helper import initialize_app_commands

# Trigger app command availability detection early in the process.
app_commands, DiscordOption, app_commands_available = initialize_app_commands()


def _prepare_event_loop() -> asyncio.AbstractEventLoop:
    """Create a dedicated asyncio loop for the bot runtime."""

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    else:
        try:  # pragma: no cover - uvloop optional dependency
            import uvloop

            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            logging.getLogger("ddc.bot").info("Using uvloop for better performance")
        except ImportError:
            pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def _ensure_timezone(runtime_logger: logging.Logger) -> None:
    """Ensure the process timezone matches the configuration."""

    timezone_name = os.environ.get("TZ", "Europe/Berlin")
    runtime_logger.info("Attempting to set timezone to: %s", timezone_name)

    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(timezone_name)
        runtime_logger.info("Successfully set timezone to %s using zoneinfo", timezone_name)
    except ImportError:
        try:
            tz = pytz.timezone(timezone_name)
            runtime_logger.info("Successfully set timezone to %s using pytz", timezone_name)
        except (RuntimeError) as e:
            runtime_logger.warning("Could not set timezone %s: %s", timezone_name, exc)
            runtime_logger.info("Using UTC as fallback")
            tz = timezone.utc

    datetime.now().astimezone(tz)


def main() -> None:
    """Main entry point for the Discord bot."""

    configure_environment()
    config = load_main_configuration()
    runtime = build_runtime(config)

    _ensure_timezone(runtime.logger)

    bot = create_bot(runtime)
    register_event_handlers(bot, runtime)

    token = get_decrypted_bot_token(runtime)
    if not token:
        runtime.logger.error("FATAL: Bot token not found or could not be decrypted.")
        runtime.logger.error(
            "Please configure the bot token in the Web UI or check the configuration files."
        )
        sys.exit(1)

    runtime.logger.info("Starting bot with token ending in: ...%s", token[-4:])
    bot.run(token)
    runtime.logger.info("Bot has stopped gracefully.")


def _shutdown_scheduler(logger: logging.Logger) -> None:
    try:
        logger.info("Stopping Scheduler Service...")
        if stop_scheduler_service():
            logger.info("Scheduler Service stopped successfully.")
        else:
            logger.warning("Scheduler Service could not be stopped or was not running.")
    except (RuntimeError) as e:
        logger.error("Error stopping Scheduler Service: %s", exc, exc_info=True)


if __name__ == "__main__":
    try:
        try:
            asyncio.get_running_loop()
            logging.getLogger("ddc.bot").error("Event loop already running - this should not happen!")
            sys.exit(1)
        except RuntimeError:
            pass

        loop = _prepare_event_loop()

        try:
            main()
        except KeyboardInterrupt:
            logging.getLogger("ddc.bot").info("Received keyboard interrupt - shutting down gracefully")
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

            loop.close()
            asyncio.set_event_loop(None)
    except discord.LoginFailure:
        logging.getLogger("ddc.bot").error("FATAL: Invalid Discord Bot Token provided.")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        logging.getLogger("ddc.bot").error(
            "FATAL: Necessary Privileged Intents are missing in the Discord Developer Portal!"
        )
        sys.exit(1)
    except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        logging.getLogger("ddc.bot").error(
            "FATAL: An unexpected error occurred during bot execution: %s", exc, exc_info=True
        )
        sys.exit(1)
    finally:
        _shutdown_scheduler(logging.getLogger("ddc.bot"))
