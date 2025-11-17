# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup routines for the background scheduler."""

from __future__ import annotations

from services.scheduling.scheduler_service import start_scheduler_service

from ..startup_context import StartupContext, as_step


@as_step
async def start_scheduler_step(context: StartupContext) -> None:
    logger = context.logger
    try:
        logger.info("Starting Scheduler Service...")
        if start_scheduler_service():
            logger.info("Scheduler Service started successfully.")
        else:
            logger.warning("Scheduler Service could not be started or was already running.")
    except (IOError, OSError, PermissionError, RuntimeError) as e:
        logger.error("Error starting Scheduler Service: %s", exc, exc_info=True)
