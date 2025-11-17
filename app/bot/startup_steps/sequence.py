# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Helpers for orchestrating the Discord bot startup sequence."""

from __future__ import annotations

from typing import Sequence

from ..startup_context import StartupContext, StartupStep


async def run_startup_sequence(context: StartupContext, steps: Sequence[StartupStep]) -> None:
    """Execute the configured startup steps sequentially with structured logging."""

    logger = context.logger
    for step in steps:
        step_name = getattr(step, "step_name", getattr(step, "__name__", "unknown"))
        logger.info("→ Running startup step: %s", step_name)
        await step(context)
        logger.info("✓ Completed startup step: %s", step_name)
