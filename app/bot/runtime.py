# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Runtime state helpers for the Discord bot."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pytz

from app.bootstrap import (
    apply_runtime_tweaks,
    ensure_log_files,
    ensure_token_security,
    initialize_logging,
    resolve_timezone,
)

from .dependencies import BotDependencies, load_dependencies


@dataclass(frozen=True, slots=True)
class BotRuntime:
    """Aggregated state required by the bot entrypoint and event handlers."""

    config: Mapping[str, object]
    logger: logging.Logger
    timezone: pytz.BaseTzInfo
    logs_dir: Path
    dependencies: BotDependencies


def build_runtime(config: Mapping[str, object]) -> BotRuntime:
    """Construct the runtime container for the bot."""

    logger = initialize_logging("ddc.bot", level=logging.INFO)
    apply_runtime_tweaks(logger)
    timezone = resolve_timezone(config, logger=logger)

    logs_dir = Path(__file__).resolve().parents[2] / "logs"
    # On `ddc`, not on `ddc.bot`. Every DDC module logs under ddc.<something>
    # and they are SIBLINGS of ddc.bot, not its children - attached to the bot
    # alone, the two files collected one logger out of twenty while everything
    # else reached only the console, where setup_logger gives each module its
    # own stream handler. That gap is invisible until you open the file, and
    # bot_error.log is what the panel's Application tab shows after a crash.
    ensure_log_files(logging.getLogger("ddc"), logs_dir)
    ensure_token_security(logger)

    logger.info("Final effective timezone for logging and operations: %s", timezone)

    dependencies = load_dependencies(logger)

    return BotRuntime(
        config=config,
        logger=logger,
        timezone=timezone,
        logs_dir=logs_dir,
        dependencies=dependencies,
    )
