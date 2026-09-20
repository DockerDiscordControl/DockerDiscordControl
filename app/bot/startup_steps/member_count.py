# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup routines for refreshing the cached member count."""

from __future__ import annotations

import asyncio
import json

from services.member_count import get_member_count_service

from ..startup_context import StartupContext, as_step


@as_step
async def initialize_member_count_step(context: StartupContext) -> None:
    logger = context.logger
    member_count_service = get_member_count_service()
    try:
        logger.info("Checking if Level 1 member count needs initialization...")
        from services.mech.progress_service import LOCK, get_progress_service, load_snapshot

        progress_service = get_progress_service()
        state = progress_service.get_state()  # creates (or migrates) the snapshot

        with LOCK:
            member_count = load_snapshot(progress_service.mech_id).last_user_count_sample

        if await _refresh_member_count(context, state.level, member_count, member_count_service):
            await _recalculate_goal(progress_service.mech_id, logger)
    except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, asyncio.TimeoutError, json.JSONDecodeError) as e:
        logger.error("Error initializing Level 1 member count: %s", e, exc_info=True)


async def _refresh_member_count(
    context: StartupContext,
    level: int,
    previous_member_count: int,
    member_count_service,
) -> bool:
    bot = context.bot
    logger = context.logger

    guild = member_count_service.first_connected_guild(bot)
    if guild is None:
        logger.warning("Bot is not connected to any guilds; skipping member count update")
        return False

    logger.info("Found guild: %s (ID: %s)", getattr(guild, "name", "?"), getattr(guild, "id", "?"))

    resolved_count = member_count_service.compute_unique_member_count(
        guild,
        fallback=previous_member_count or None,
    )

    if resolved_count <= 0:
        logger.warning("⚠️ Could not determine member count from status channels; using fallback")
        resolved_count = previous_member_count or 1

    if resolved_count == previous_member_count and previous_member_count > 0:
        logger.info("Member count already set: %d members", previous_member_count)
        return False

    logger.info("🔒 UPDATING member count for Level %s: %s unique members", level, resolved_count)
    member_count_service.publish_member_count(resolved_count)
    member_count_service.persist_member_count_snapshot(
        resolved_count,
        source="status_channels",
        description="Unique members across all status channels (bots excluded)",
        note="This count includes ONLY members who can see status channels, not all server members",
    )
    logger.info("📝 Wrote member_count.json with %s status channel members", resolved_count)
    return True


async def _recalculate_goal(mech_id: str, logger) -> None:
    from services.mech.progress_service import (
        LOCK,
        current_bin,
        load_snapshot,
        persist_snapshot,
        requirement_for_level_and_bin,
    )

    # Read-modify-write under the progress lock and change only the goal fields: writing
    # back a copy read before publish_member_count() undid the new member count (and any
    # donation processed in between)
    with LOCK:
        snap = load_snapshot(mech_id)
        member_count = snap.last_user_count_sample
        if member_count <= 0:
            logger.debug("Skipping goal recalculation because member count is <= 0")
            return
        if snap.level >= 11:
            logger.debug("Skipping goal recalculation at max level (no next goal)")
            return

        new_bin = current_bin(member_count)
        new_goal = requirement_for_level_and_bin(
            level=snap.level,
            b=new_bin,
            member_count=member_count,
        )
        old_goal = snap.goal_requirement
        snap.goal_requirement = new_goal
        snap.difficulty_bin = new_bin
        persist_snapshot(snap)

    logger.info(
        "✅ Level %s goal updated: $%.2f → $%.2f (for %s members)",
        snap.level,
        old_goal / 100,
        new_goal / 100,
        member_count,
    )
