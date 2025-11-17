# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup routines for refreshing the cached member count."""

from __future__ import annotations

import json

from services.member_count import get_member_count_service

from ..startup_context import StartupContext, as_step


@as_step
async def initialize_member_count_step(context: StartupContext) -> None:
    logger = context.logger
    member_count_service = get_member_count_service()
    try:
        logger.info("Checking if Level 1 member count needs initialization...")
        from services.mech.progress_service import get_progress_service
        from services.mech.progress_paths import get_progress_paths

        progress_service = get_progress_service()
        state = progress_service.get_state()

        paths = get_progress_paths()
        snap_file = paths.snapshot_for("main")
        if not snap_file.exists():
            logger.warning("Snapshot file not found for member count initialization")
            return

        snap = json.loads(snap_file.read_text())
        member_count = snap.get("last_user_count_sample", 0)

        if await _refresh_member_count(context, state.level, member_count, member_count_service):
            await _recalculate_goal(snap, logger)
    except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, asyncio.CancelledError, asyncio.TimeoutError, json.JSONDecodeError) as e:
        logger.error("Error initializing Level 1 member count: %s", exc, exc_info=True)


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


async def _recalculate_goal(snap: dict, logger) -> None:
    from services.mech.progress_service import current_bin, requirement_for_level_and_bin

    member_count = snap.get("last_user_count_sample", 0)
    if member_count <= 0:
        logger.debug("Skipping goal recalculation because member count is <= 0")
        return

    new_goal = requirement_for_level_and_bin(
        level=snap["level"],
        b=current_bin(member_count),
        member_count=member_count,
    )

    old_goal = snap.get("goal_requirement", new_goal)
    snap["goal_requirement"] = new_goal
    snap["difficulty_bin"] = current_bin(member_count)

    snap_file = get_progress_paths().snapshot_for("main")
    snap_file.write_text(json.dumps(snap, indent=2))
    logger.info(
        "✅ Level %s goal updated: $%.2f → $%.2f (for %s members)",
        snap["level"],
        old_goal / 100,
        new_goal / 100,
        member_count,
    )
