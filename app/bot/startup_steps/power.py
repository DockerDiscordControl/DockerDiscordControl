# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup routines that interact with the mech power gift system."""

from __future__ import annotations

import docker

from ..startup_context import StartupContext, as_step


@as_step
async def grant_power_gift_step(context: StartupContext) -> None:
    logger = context.logger
    try:
        logger.info("Checking if power gift should be granted...")
        from services.mech.mech_service_adapter import get_mech_service

        campaign_id = "startup_gift_v1"
        adapter = get_mech_service()
        state = adapter.power_gift(campaign_id)

        if state.power_level > 0:
            logger.info("✅ Power gift granted: $%.2f Power", state.power_level)
            # REMOVED: Cache clear not needed - MechStatusCacheService reads from DB
            # The background loop will pick up the new value automatically on next refresh
            # Clearing the cache causes Web UI to show "OFFLINE" until loop refreshes
        else:
            logger.info("Power gift not needed (power > 0 or already granted)")
    except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error("Error checking/granting power gift: %s", e, exc_info=True)
