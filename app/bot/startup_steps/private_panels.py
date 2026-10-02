# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Deleting the private panels a restart left open.

Their timeouts died with the old process; their tokens may still work for
up to fifteen minutes. See services/discord/private_panels.py (operator,
2026-10-02).
"""

from __future__ import annotations

from ..startup_context import StartupContext, as_step


@as_step
async def remove_left_private_panels_step(context: StartupContext) -> None:
    from services.discord.private_panels import delete_left_behind
    deleted = await delete_left_behind()
    if deleted:
        context.logger.info(f"Deleted {deleted} private panel(s) a restart had left open")
