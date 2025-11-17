# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Runtime bootstrap helpers for the Discord bot."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Mapping, MutableMapping, Optional

import pytz

from services.config.config_service import load_config
from utils.config_cache import init_config_cache
from utils.logging_utils import setup_logger


def configure_environment(env: Optional[MutableMapping[str, str]] = None) -> str:
    """Ensure required environment defaults are present.

    Parameters
    ----------
    env:
        Optional mapping to mutate.  Defaults to :data:`os.environ` when not
        provided which keeps the function easy to use in production while still
        being testable.

    Returns
    -------
    str
        The effective value of ``DDC_DISCORD_SKIP_TOKEN_LOCK`` after applying
        the default.
    """

    target_env: MutableMapping[str, str]
    if env is None:
        target_env = os.environ
    else:
        target_env = env

    target_env.setdefault("DDC_DISCORD_SKIP_TOKEN_LOCK", "true")
    return target_env["DDC_DISCORD_SKIP_TOKEN_LOCK"]


def load_main_configuration() -> Mapping[str, object]:
    """Load the main configuration and populate the in-memory cache."""

    config = load_config()
    init_config_cache(config)
    return config


def initialize_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    """Create the primary logger for the bot."""

    logger = setup_logger(name, level=level)
    return logger


def resolve_timezone(
    config: Optional[Mapping[str, object]],
    *,
    default: str = "Europe/Berlin",
    logger: Optional[logging.Logger] = None,
) -> pytz.BaseTzInfo:
    """Resolve the timezone defined in the configuration.

    Falls back to UTC when the configured timezone is unknown or when another
    exception occurs while constructing the timezone object.  The function keeps
    logging concerns local which simplifies callers.
    """

    active_logger = logger or logging.getLogger("ddc.bootstrap")
    timezone_str = default
    if config is not None:
        timezone_str = str(config.get("timezone", default))

    try:
        tz = pytz.timezone(timezone_str)
        active_logger.info("Using timezone '%s'", timezone_str)
        return tz
    except pytz.exceptions.UnknownTimeZoneError:
        active_logger.warning(
            "Unknown timezone '%s'. Falling back to UTC for this session.", timezone_str
        )
    except (RuntimeError) as e:
        active_logger.error(
            "Error setting timezone '%s': %s. Falling back to UTC for this session.",
            timezone_str,
            e,
            exc_info=True
        )

    return pytz.timezone("UTC")


def ensure_log_files(logger: logging.Logger, logs_dir: Path) -> None:
    """Attach rotating file handlers to the provided logger if missing."""

    logs_dir.mkdir(parents=True, exist_ok=True)

    discord_log_path = logs_dir / "discord.log"
    bot_error_log_path = logs_dir / "bot_error.log"

    if not any(
        isinstance(handler, logging.FileHandler)
        and getattr(handler, "baseFilename", "") == str(discord_log_path)
        for handler in logger.handlers
    ):
        info_handler = logging.FileHandler(discord_log_path, encoding="utf-8")
        info_handler.setLevel(logging.INFO)
        info_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(info_handler)

    if not any(
        isinstance(handler, logging.FileHandler)
        and getattr(handler, "baseFilename", "") == str(bot_error_log_path)
        for handler in logger.handlers
    ):
        error_handler = logging.FileHandler(bot_error_log_path, encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(error_handler)

    logger.info(
        "Bot file loggers initialized: discord.log (INFO+), bot_error.log (ERROR+)"
    )


def ensure_token_security(logger: logging.Logger) -> bool:
    """Execute the optional token auto-encryption routine."""

    try:
        from utils.token_security import auto_encrypt_token_on_startup
    except ImportError:
        logger.debug("Token security module not available")
        return False

    try:
        auto_encrypt_token_on_startup()
        logger.debug("Token auto-encryption check completed")
        return True
    except (RuntimeError) as e:
        logger.warning("Token auto-encryption failed: %s", exc)
        return False
