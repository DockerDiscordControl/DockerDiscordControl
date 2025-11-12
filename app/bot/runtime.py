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


@dataclass(frozen=True)
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
    ensure_log_files(logger, logs_dir)
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
