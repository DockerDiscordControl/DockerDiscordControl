# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup routines related to environment diagnostics."""

from __future__ import annotations

from app.utils.port_diagnostics import log_port_diagnostics

from ..startup_context import StartupContext, as_step


@as_step
async def run_port_diagnostics_step(context: StartupContext) -> None:
    logger = context.logger
    try:
        logger.info("Running port diagnostics at Discord bot startup...")
        log_port_diagnostics()
    except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError) as e:
        logger.error("Error running port diagnostics at startup: %s", exc, exc_info=True)
