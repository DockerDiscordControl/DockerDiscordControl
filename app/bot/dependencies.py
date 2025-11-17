# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Optional runtime dependencies used by the Discord bot."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class BotDependencies:
    """Container for lazily constructed bot dependencies."""

    config_service_factory: Optional[Callable[[], Any]] = None
    dynamic_cooldown_applicator: Optional[Callable[[Any], None]] = None
    update_notifier_factory: Optional[Callable[[], Any]] = None


def load_dependencies(logger: logging.Logger) -> BotDependencies:
    """Load optional integrations that enrich the bot runtime."""

    config_service_factory: Optional[Callable[[], Any]]
    try:
        from services.config.config_service import get_config_service

        config_service_factory = get_config_service
    except ImportError:
        logger.debug("Config service not available for runtime token decryption")
        config_service_factory = None

    try:
        from services.infrastructure.dynamic_cooldown_manager import (
            apply_dynamic_cooldowns_to_bot,
        )

        dynamic_cooldown_applicator = apply_dynamic_cooldowns_to_bot
        logger.debug("Dynamic cooldown manager loaded")
    except ImportError:
        logger.warning("Dynamic cooldowns not available - using legacy cooldowns")
        dynamic_cooldown_applicator = None

    try:
        from services.infrastructure.update_notifier import get_update_notifier

        update_notifier_factory = get_update_notifier
        logger.debug("Update notifier module detected")
    except ImportError:
        logger.debug("Update notifier not available - skipping update notifications")
        update_notifier_factory = None

    return BotDependencies(
        config_service_factory=config_service_factory,
        dynamic_cooldown_applicator=dynamic_cooldown_applicator,
        update_notifier_factory=update_notifier_factory,
    )
