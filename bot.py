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
import dataclasses
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import pytz

# Fix for audioop module in Python 3.13
try:
    import audioop  # type: ignore
except ImportError:  # pragma: no cover - import shim only used on specific platforms
    import audioop_lts as audioop  # type: ignore

sys.modules["audioop"] = audioop

import discord

from app.bootstrap import configure_environment, load_main_configuration
from app.bootstrap.runtime import get_web_port
from app.bot import build_runtime, create_bot, get_decrypted_bot_token, register_event_handlers
from services.scheduling.scheduler_service import stop_scheduler_service
from utils.app_commands_helper import initialize_app_commands

# Trigger app command availability detection early in the process.
app_commands, DiscordOption, app_commands_available = initialize_app_commands()

# Seconds between re-checks of the configured token after Discord rejected the login.
TOKEN_RECHECK_INTERVAL = 20

# Missing privileged intents cannot be detected without a new login, so DDC re-executes
# itself to retry. The delay doubles per attempt (the counter survives the re-exec via
# the environment) up to the cap, so an unattended install does not burn through
# Discord's daily IDENTIFY budget (1000 per token and day).
INTENTS_RETRY_INITIAL_DELAY = 90
INTENTS_RETRY_MAX_DELAY = 900
INTENTS_RETRY_ENV = "DDC_INTENTS_RETRY_ATTEMPT"


def _handle_sigterm(signum, frame) -> None:
    logging.getLogger("ddc.bot").info("Received SIGTERM - shutting down")
    raise SystemExit(0)


def install_sigterm_handler(runtime_logger: Optional[logging.Logger] = None) -> None:
    """Make SIGTERM end the process while py-cord's own handler is not installed.

    DDC runs as PID 1 in the container, where the kernel ignores signals that have
    no handler, so ``docker stop`` would wait 10 s and then SIGKILL. ``bot.run()``
    replaces this handler with py-cord's own one while the bot runs (and resets it to
    the default when its loop closes).
    """
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except (ValueError, OSError) as e:  # not the main thread / unsupported platform
        if runtime_logger:
            runtime_logger.debug("Could not install SIGTERM handler: %s", e)


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
    """Ensure the process timezone matches the configuration.

    An invalid ``TZ`` value (e.g. ``GMT+1``) must not crash the startup, so it
    falls back to UTC with a warning.
    """

    timezone_name = os.environ.get("TZ", "Europe/Berlin")
    runtime_logger.info("Attempting to set timezone to: %s", timezone_name)

    try:
        import zoneinfo
    except ImportError:
        zoneinfo = None

    tz = None
    if zoneinfo is not None:
        try:
            tz = zoneinfo.ZoneInfo(timezone_name)
            runtime_logger.info("Successfully set timezone to %s using zoneinfo", timezone_name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError) as e:
            runtime_logger.warning("Could not set timezone %s: %s", timezone_name, e)
    else:
        try:
            tz = pytz.timezone(timezone_name)
            runtime_logger.info("Successfully set timezone to %s using pytz", timezone_name)
        except (pytz.exceptions.UnknownTimeZoneError, ValueError, OSError) as e:
            runtime_logger.warning("Could not set timezone %s: %s", timezone_name, e)

    if tz is None:
        runtime_logger.info("Using UTC as fallback")
        tz = timezone.utc

    datetime.now().astimezone(tz)


def _read_configured_token(runtime) -> Optional[str]:
    """Re-read the currently configured bot token without flooding the log."""

    quiet_logger = logging.getLogger("ddc.bot.token_watch")
    quiet_logger.propagate = False
    if not quiet_logger.handlers:
        quiet_logger.addHandler(logging.NullHandler())

    try:
        from services.config.config_service import load_config

        fresh_runtime = dataclasses.replace(runtime, config=load_config(), logger=quiet_logger)
        return get_decrypted_bot_token(fresh_runtime)
    except Exception as e:  # keep polling on transient config/decryption errors
        runtime.logger.debug("Token re-check failed: %s", e)
        return None


def _restart_process(runtime_logger: logging.Logger) -> None:
    """Replace this process with a fresh DDC instance (same PID, same arguments)."""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    try:
        os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])
    except OSError as e:
        runtime_logger.critical(
            "Could not restart DDC in-process (%s) - exiting so Docker can restart the container", e
        )
        sys.exit(1)


def _intents_retry_attempt() -> int:
    """Number of automatic login retries already made for missing intents."""

    try:
        return max(0, int(os.environ.get(INTENTS_RETRY_ENV, "0")))
    except ValueError:
        return 0


def _intents_retry_delay(attempt: int) -> int:
    """Seconds to wait before the next automatic login retry (90 s, doubling, capped)."""

    return min(INTENTS_RETRY_MAX_DELAY, INTENTS_RETRY_INITIAL_DELAY * 2 ** min(attempt, 10))


def _wait_for_new_token_and_restart(runtime, rejected_token: str, retry_after: Optional[int] = None) -> None:
    """Keep the process (and the Web UI thread) alive until a different token is configured.

    py-cord closes its event loop when ``bot.run()`` fails, so a second login in this
    process is not possible. As soon as a new token is saved, the process re-executes
    itself (same PID, fresh bot and Web UI) instead of depending on a restart policy.
    With ``retry_after`` (missing intents - fixed in the Developer Portal, not by a new
    token) the process also re-executes once that many seconds have passed.
    """

    # py-cord reset SIGTERM to the default disposition when its loop closed.
    install_sigterm_handler(runtime.logger)
    web_port = get_web_port()
    runtime.logger.warning(
        "Bot login disabled - waiting for a new bot token (re-checked every %d s). "
        "The Web UI stays available on port %d.",
        TOKEN_RECHECK_INTERVAL,
        web_port,
    )

    checks = 0
    waited = 0
    while True:
        time.sleep(TOKEN_RECHECK_INTERVAL)
        checks += 1
        waited += TOKEN_RECHECK_INTERVAL
        new_token = _read_configured_token(runtime)
        if new_token and new_token != rejected_token:
            runtime.logger.info("🔑 New bot token detected - restarting DDC to log in again...")
            os.environ.pop(INTENTS_RETRY_ENV, None)  # new token -> start the intents backoff over
            time.sleep(2)  # let the Web UI finish the request that saved the token
            _restart_process(runtime.logger)
            return
        if retry_after is not None and waited >= retry_after:
            runtime.logger.warning(
                "🔁 Retrying the Discord login - restarting DDC to check whether the privileged "
                "intents are enabled now..."
            )
            os.environ[INTENTS_RETRY_ENV] = str(_intents_retry_attempt() + 1)
            _restart_process(runtime.logger)
            return
        if checks % 15 == 0:
            runtime.logger.warning(
                "Still waiting for a valid bot token / enabled intents. The Web UI is available on port %d.",
                web_port,
            )


def _run_bot_until_stopped(bot, runtime, token: str) -> None:
    """Run the bot; on a rejected token or missing intents keep the Web UI alive.

    Exiting here would make the container restart-loop, and the Web UI - the only
    place to fix the token - would only be up for a few seconds per cycle.
    """

    try:
        bot.run(token)
    except discord.LoginFailure:
        runtime.logger.error("FATAL: Discord rejected the bot token (invalid or reset token).")
        if os.getenv("DISCORD_BOT_TOKEN"):
            runtime.logger.error(
                "The token comes from the DISCORD_BOT_TOKEN environment variable - fix it in the "
                "container settings and recreate the container."
            )
        else:
            runtime.logger.error(
                "Fix the bot token in the Web UI - DDC restarts automatically as soon as a new token is saved."
            )
        _wait_for_new_token_and_restart(runtime, token)
    except discord.PrivilegedIntentsRequired:
        retry_delay = _intents_retry_delay(_intents_retry_attempt())
        runtime.logger.error(
            "FATAL: Required privileged intents (Server Members Intent, Message Content Intent) "
            "are not enabled for this bot in the Discord Developer Portal."
        )
        runtime.logger.error(
            "Enable them under Bot -> Privileged Gateway Intents - DDC retries the login "
            "automatically in about %d s (or restart the container). The Web UI stays available "
            "in the meantime.",
            retry_delay,
        )
        _wait_for_new_token_and_restart(runtime, token, retry_after=retry_delay)


def main() -> None:
    """Main entry point for the Discord bot."""

    install_sigterm_handler()

    # Ensure event loop exists before creating bot (required for py-cord)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _prepare_event_loop()

    configure_environment()
    config = load_main_configuration()
    runtime = build_runtime(config)

    _ensure_timezone(runtime.logger)

    bot = create_bot(runtime)
    register_event_handlers(bot, runtime)

    # Set global bot instance for Web UI access
    from services.scheduling.donation_message_service import set_bot_instance
    set_bot_instance(bot)

    # Retry loop for missing token with countdown
    retry_interval = int(os.getenv("DDC_TOKEN_RETRY_INTERVAL", "60"))
    max_retries = int(os.getenv("DDC_TOKEN_MAX_RETRIES", "0"))  # 0 = infinite
    retry_count = 0

    while True:
        token = get_decrypted_bot_token(runtime)
        if token:
            break

        retry_count += 1
        runtime.logger.error("FATAL: Bot token not found or could not be decrypted.")
        runtime.logger.error(
            "Please configure the bot token in the Web UI or check the configuration files."
        )

        if max_retries > 0 and retry_count >= max_retries:
            runtime.logger.error(f"Maximum retries ({max_retries}) reached. Exiting.")
            sys.exit(1)

        runtime.logger.warning(f"Retry {retry_count}: Waiting {retry_interval} seconds before next attempt...")

        # Countdown timer
        for remaining in range(retry_interval, 0, -1):
            if remaining % 10 == 0 or remaining <= 5:
                runtime.logger.info(f"⏳ Retrying in {remaining} seconds...")
            time.sleep(1)

        runtime.logger.info("Attempting to reload configuration and retry...")
        # Reload config in case it was updated
        config = load_main_configuration()
        runtime = build_runtime(config)

    # Not a fragment of it: four characters still confirm a guess and still
    # tell two logs apart, and this file gets attached to bug reports. Which
    # token is in use was already said safely, by naming its SOURCE.
    runtime.logger.info("Starting bot")
    _run_bot_until_stopped(bot, runtime, token)
    runtime.logger.info("Bot has stopped gracefully.")


def _shutdown_scheduler(logger: logging.Logger) -> None:
    try:
        logger.info("Stopping Scheduler Service...")
        if stop_scheduler_service():
            logger.info("Scheduler Service stopped successfully.")
        else:
            logger.warning("Scheduler Service could not be stopped or was not running.")
    except (RuntimeError) as e:
        logger.error("Error stopping Scheduler Service: %s", e, exc_info=True)


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
            "FATAL: An unexpected error occurred during bot execution: %s", e, exc_info=True
        )
        sys.exit(1)
    finally:
        _shutdown_scheduler(logging.getLogger("ddc.bot"))
