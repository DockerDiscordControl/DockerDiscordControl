# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The overview embeds of DockerControlCog: expanded, collapsed and admin.

Moved out of cogs/docker_control.py unchanged on 2026-09-22 (roadmap Phase 3,
the cog split). Pure rendering: builds the embeds from the server list and
the status cache; sending and editing stays in the cog. The persistent-button
and slash-command ratchet (tests/spec/test_buttons_on_old_messages_keep_working.py)
holds across the move.
"""

import logging
import os
import time
from datetime import datetime, timezone
from io import BytesIO

import discord

from services.config.config_service import load_config
from utils.logging_utils import setup_logger
from utils.time_utils import format_datetime_with_timezone

from .translation_manager import _

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)


def power_consumption_line(decay_per_day) -> str:
    """The mech's power consumption, or that it is not known.

    The rate comes from the evolution table; a level outside it - or a table
    that could not be read - used to fall back to 1.0, printed exactly like a
    rate somebody had looked up.
    """
    from .translation_manager import _ as translate

    label = translate("Power Consumption")
    if decay_per_day is None:
        return f"{label}: 🔻 ?"
    if decay_per_day == 0:
        return f"{label}: ⚡ {translate('No decay')}"
    return f"{label}: 🔻 {decay_per_day}{translate('per_day_suffix')}"


def group_status_lines(status_cache_service, translate, boxed: bool = True) -> list:
    """The operator's container groups, as lines for the overview.

    THE OPERATOR, 2026-09-24, with a screenshot of the overview: he could not
    see his group in Discord. A group carries its own Active and its own four
    actions and the panel shows it as a row in the container table - but in
    Discord it existed only inside a menu behind a button. His instruction was
    that a group behaves like a container IN THE DISPLAY too, and the overview
    is the display.

    THE COUNT is the one thing a container line cannot have: how many members
    are running. Green when they all are, red when none is, YELLOW when they
    disagree - a group of two with one up is neither of the first two, and
    drawing it as either would be a lie about one of them.

    THE GROUP DECIDES, here as everywhere: one the operator switched off is not
    shown, and neither is one he did not allow to report status.

    Empty for an operator with no groups: no divider, no heading, nothing. The
    overview he had yesterday is the overview he keeps.

    TWO STYLES, ONE WALK (operator, 2026-09-24). The server overview draws a
    box: every container line there starts with a pipe, so the group lines do
    too, and he called that one pretty. The ADMIN overview stacks blocks and
    draws no box - the same lines arrived there as stray pipes and dashes. With
    ``boxed=False`` it is a plain heading and lines shaped like the container
    lines above them. A second implementation instead of a flag is how a group
    ends up in one view and not the other.
    """
    try:
        from services.config.group_service import get_group_service

        service = get_group_service()
        groups = service.get_groups()
    except OSError as e:
        # The containers are still worth showing; the groups are said to be
        # missing in the log rather than silently reported as "none defined".
        logger.error(f"Groups could not be read for the overview: {e}")
        return []

    lines = []
    for group in groups:
        if not group.active or "status" not in group.allowed_actions:
            continue
        members = service.members_of(group.name)
        present = members.containers
        running = 0
        for container in present:
            entry = status_cache_service.get(container) if status_cache_service else None
            data = entry.get('data') if entry else None
            if data is not None and getattr(data, 'is_running', False):
                running += 1
        total = len(present)
        if running and running == total:
            lamp = "🟢"
        elif running:
            lamp = "🟡"
        else:
            lamp = "🔴"
        name = group.name[:20] + "." if len(group.name) > 20 else group.name
        gone = " ⚠️" if members.missing else ""
        prefix = "│ " if boxed else ""
        lines.append(f"{prefix}{lamp} {name} {running}/{total}{gone}")

    if not lines:
        return []
    # Set apart, the way the panel sets them apart: a group listed among the
    # containers reads as a container with a strange name.
    heading = (f"├── {translate('Container groups')} ──────" if boxed
               else f"**{translate('Container groups')}:**")
    return [heading] + lines


def with_website_footer(embed) -> None:
    """The website line in the footer, keeping whatever was put there first.

    The animation fallback writes "Animation service temporarily unavailable"
    into the footer, and an unconditional set_footer at the end of every builder
    erased it on every render - so the operator saw a missing image and no
    reason for it.
    """
    website = "https://ddc.bot"
    existing = embed.footer.text if embed.footer and embed.footer.text else ""
    embed.set_footer(text=f"{existing} | {website}" if existing else website)


class OverviewEmbedsMixin:
    """Overview embed builders, mixed into DockerControlCog."""

    async def _create_overview_embed_expanded(self, ordered_servers, config, force_refresh=False):
        """Creates the server overview embed with EXPANDED mech status details.

        Args:
            ordered_servers: List of server configurations
            config: Application configuration
            force_refresh: If True, forces fresh data from cache (for manual commands)

        Returns:
            tuple: (embed, animation_file) where animation_file is None if no animation
        """
        # Import translation function locally to ensure it's accessible
        from .translation_manager import _ as translate

        # Initialize animation file
        animation_file = None

        # Create the overview embed
        embed = discord.Embed(
            title=translate("Server Overview"),
            color=discord.Color.blue()
        )

        # Build server status lines (same logic as original)
        now_utc = datetime.now(timezone.utc)
        fresh_config = load_config()
        timezone_str = fresh_config.get('timezone') if fresh_config else config.get('timezone')

        current_time = format_datetime_with_timezone(now_utc, timezone_str, time_only=True)

        # Add timestamp at the top
        last_update_text = translate("Last update")

        # Start building the content (same server status logic as original)
        content_lines = [
            f"{last_update_text}: {current_time}",
            "┌── Status ─────────────────"
        ]

        # Add server statuses (copy from original method)
        for server_conf in ordered_servers:
            display_name = server_conf.get('display_name', server_conf.get('docker_name'))
            docker_name = server_conf.get('docker_name')
            if not display_name or not docker_name:
                continue

            # Use cached data only (same as original)
            # Use docker_name as cache key (stable identifier)
            cached_entry = self.status_cache_service.get(docker_name)
            status_result = None

            if cached_entry and cached_entry.get('data'):
                from utils.settings import get_setting
                max_cache_age = get_setting('DDC_DOCKER_MAX_CACHE_AGE', 300)

                if 'timestamp' in cached_entry:
                    cache_age = (datetime.now(timezone.utc) - cached_entry['timestamp']).total_seconds()
                    if cache_age > max_cache_age:
                        logger.debug(f"Cache for {display_name} expired ({cache_age:.1f}s > {max_cache_age}s)")
                        cached_entry = None

                if cached_entry and cached_entry.get('data'):
                    status_result = cached_entry['data']
            else:
                logger.debug(f"[/serverstatus] No cache entry for '{display_name}' - Background loop will update")
                status_result = None

            # Check if container has info available (same as original)
            info_indicator = ""
            try:
                from services.infrastructure.container_info_service import get_container_info_service
                info_service = get_container_info_service()
                info_result = info_service.get_container_info(docker_name)
                if info_result.success and info_result.data.enabled:
                    info_indicator = " ℹ️"
            except (RuntimeError, ValueError, KeyError, OSError) as e:
                logger.debug(f"Could not check info status for {docker_name}: {e}")

            # Process status result - NOW USING ContainerStatusResult Objects (not tuples)
            # Check if we have a successful ContainerStatusResult
            from services.docker_status.models import ContainerStatusResult

            if status_result and isinstance(status_result, ContainerStatusResult) and status_result.success:
                is_running = status_result.is_running

                # Determine status icon (same logic as original)
                # Check pending actions using docker_name as key
                if docker_name in self.pending_actions:
                    pending_timestamp = self.pending_actions[docker_name]['timestamp']
                    pending_duration = (now_utc - pending_timestamp).total_seconds()
                    if pending_duration < 120:
                        status_emoji = "🟡"
                        status_text = translate("Pending")
                    else:
                        del self.pending_actions[docker_name]
                        status_emoji = "🟢" if is_running else "🔴"
                else:
                    status_emoji = "🟢" if is_running else "🔴"

                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                # Compact live player count (e.g. "  3/8") for running game servers with query data
                from services.discord.embed_helper_service import format_player_inline
                player_indicator = format_player_inline(status_result.players_online, status_result.max_players)
                # Add status line: status emoji, name, player count, info indicator
                line = f"│ {status_emoji} {truncated_name}{player_indicator}{info_indicator}"
                if status_result.not_found:
                    # Deleted/renamed container: own state instead of 🔴 or an endless 🔄
                    line = f"│ ❓ {truncated_name} · {translate('not found')}{info_indicator}"
                content_lines.append(line)
            else:
                # No cache data available - show loading status
                status_emoji = "🔄"
                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                line = f"│ {status_emoji} {truncated_name}{info_indicator}"
                content_lines.append(line)

        # The operator's groups, below the containers and set apart from them
        # (group_status_lines). Empty when he has none.
        content_lines.extend(group_status_lines(getattr(self, 'status_cache_service', None), translate))

        # Close server status box
        content_lines.append("└───────────────────────────")

        # Combine all lines into the description, cut to what Discord accepts:
        # an embed description longer than 4096 characters is REFUSED, and the
        # list grows with the installation (see
        # tests/spec/test_a_long_container_list_still_reaches_discord.py).
        from services.discord.embed_helper_service import fit_lines

        embed.description = fit_lines(
            content_lines, prefix="```\n", suffix="\n```",
            more=lambda count: translate("… and {count} more containers").format(count=count))

        # Check if any containers have info available
        has_any_info = False
        try:
            from services.infrastructure.container_info_service import get_container_info_service
            info_service = get_container_info_service()
            for server_conf in ordered_servers:
                docker_name = server_conf.get('docker_name')
                if docker_name:
                    info_result = info_service.get_container_info(docker_name)
                    if info_result.success and info_result.data.enabled:
                        has_any_info = True
                        break
        except (KeyError, AttributeError, ValueError) as e:
            logger.debug(f"Could not check info availability: {e}")

        # Help text removed - replaced with Help button in MechView

        # Check if donations are disabled by premium key
        from services.donation.donation_utils import is_donations_disabled
        donations_disabled = is_donations_disabled()

        # Add EXPANDED Mech Status with detailed information and progress bars (skip if donations disabled)
        mechonate_button = None
        if not donations_disabled:
            try:
                logger.info("DEBUG: Using Mech Status Cache Service")
                import sys
                # Add project root to Python path for service imports
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                # SERVICE FIRST: Use MechStatusCacheService for instant response
                from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
                cache_service = get_mech_status_cache_service()
                cache_request = MechStatusCacheRequest(include_decimals=True, force_refresh=force_refresh)
                mech_cache_result = cache_service.get_cached_status(cache_request)

                if not mech_cache_result.success:
                    # Callers unpack (embed, animation_file) - never return None here. Skip the
                    # mech section via the handler below and still return the server overview.
                    raise RuntimeError(f"Failed to get cached mech status: {mech_cache_result.error_message}")

                logger.info(f"CACHE: Using cached mech data (age: {mech_cache_result.cache_age_seconds:.1f}s)")

                # Get clean data from CACHED result
                current_Power = mech_cache_result.power  # Already includes decimals from request
                total_donations_received = mech_cache_result.total_donated
                logger.info(f"CACHE: Power=${current_Power:.2f}, total_donations=${total_donations_received}, level={mech_cache_result.level} ({mech_cache_result.name})")

                # Evolution info from cached service with next_name for UI.
                # Two bugs lived here until v2.4.1:
                #   1. It imported MECH_LEVELS from services.mech.mech_service, which has never
                #      exported that name. The ImportError escaped the handler below (it only
                #      catches DiscordException/RuntimeError/OSError/KeyError), so expanding the
                #      mech section in Discord crashed outright.
                #   2. It then looked the name up by comparing a static threshold against
                #      mech_cache_result.threshold, which is the *dynamic* goal in dollars. That
                #      match practically never succeeded, so next_name stayed None and low levels
                #      showed "MAX EVOLUTION REACHED!".
                # The level number is what identifies the next evolution, so look it up directly.
                from services.mech.mech_service_adapter import get_level_name
                next_name = None
                if mech_cache_result.threshold is not None and mech_cache_result.threshold > 0:
                    # For Level 10 ONLY: use corrupted name (Level 11 should have no next_name)
                    if mech_cache_result.level == 10:
                        next_name = "ERR#R: [DATA_C0RR*PTED]"
                    elif mech_cache_result.level < 10:
                        next_name = get_level_name(mech_cache_result.level + 1)
                    # Level 11: next_name stays None -> "MAX EVOLUTION REACHED!"

                evolution = {
                    'name': mech_cache_result.name,
                    'level': mech_cache_result.level,
                    'current_threshold': 0,  # Will be calculated from level if needed
                    'next_threshold': mech_cache_result.threshold,
                }

                # Only add next_name if it exists (Level 11 has no next evolution)
                if next_name is not None:
                    evolution['next_name'] = next_name

                # Speed info from CACHE - already computed!
                speed = {
                    'level': mech_cache_result.speed,
                    'description': mech_cache_result.speed_description,
                    'color': mech_cache_result.speed_color,
                    'glvl': mech_cache_result.glvl,
                    'glvl_max': mech_cache_result.glvl_max
                }

                logger.info(f"CACHE: evolution={evolution['name']}, glvl={mech_cache_result.glvl}/{mech_cache_result.glvl_max}")

                # Create mech animation with fallback
                try:
                    from services.mech.animation_cache_service import get_animation_cache_service
                    from services.mech.speed_levels import get_combined_mech_status

                    # Get animation cache service and use actual evolution level
                    cache_service = get_animation_cache_service()
                    # UNIFICATION: Use actual mech level instead of calculating from donations
                    evolution_level = mech_cache_result.level

                    # SPEED UNIFICATION: Calculate actual speed level from current power (same as MechWebService/Status Overview)
                    # SPECIAL CASE: Level 11 is maximum level - always use Speed Level 100 (same logic as all other services)
                    if evolution_level >= 11:
                        actual_speed_level = 100  # Level 11 always has maximum speed (divine speed)
                    else:
                        # Real level + its power bar maximum (not a level guessed from the power amount)
                        speed_status = get_combined_mech_status(
                            current_Power, evolution_level=evolution_level,
                            power_max=getattr(getattr(mech_cache_result, 'bars', None), 'Power_max_for_level', None))
                        actual_speed_level = speed_status['speed']['level']

                    # Get animation bytes with power-based selection (REST if power=0, WALK if power>0)
                    animation_bytes = cache_service.get_animation_with_speed_and_power(
                        evolution_level=evolution_level,
                        speed_level=actual_speed_level,  # Use actual speed level (unified with Big Mech)
                        power_level=current_Power
                    )

                    # Convert to Discord File
                    buffer = BytesIO(animation_bytes)
                    animation_file = discord.File(buffer, filename=f"mech_status_expanded_{int(time.time())}.webp", spoiler=False)
                except (RuntimeError, ValueError, KeyError, OSError) as e:
                    logger.warning(f"Animation service failed (graceful degradation): {e}")
                    animation_file = None
                    # Add fallback visual indicator in embed
                    if not embed.footer or not embed.footer.text:
                        embed.set_footer(text=translate("🎬 Animation service temporarily unavailable"))
                    else:
                        # The separator is structure, the words are language
                        # (review E35).
                        embed.set_footer(
                            text=f"{embed.footer.text} | {translate('🎬 Animation unavailable')}")

                # Use clean progress bar data from CACHE - NO MORE MANUAL CALCULATION! 🎯
                # For Level 1, use decimal Power for accurate percentage
                if mech_cache_result.level == 1:
                    Power_current = current_Power  # Use decimal value for Level 1
                else:
                    Power_current = mech_cache_result.bars.Power_current  # Use integer for Level 2+
                Power_max = mech_cache_result.bars.Power_max_for_level
                evolution_current = mech_cache_result.bars.mech_progress_current
                evolution_max = mech_cache_result.bars.mech_progress_max

                # These two and the four below used to be logger.critical - leftovers
                # from hunting a bar that showed 100 %, written on every ordinary
                # render. CRITICAL is what an operator greps for (review B23).
                logger.debug(f"BARS: mech_progress_current={mech_cache_result.bars.mech_progress_current} (type: {type(mech_cache_result.bars.mech_progress_current)})")
                logger.debug(f"BARS: mech_progress_max={mech_cache_result.bars.mech_progress_max} (type: {type(mech_cache_result.bars.mech_progress_max)})")
                logger.info(f"CACHE BARS: Power={Power_current}/{Power_max}, evolution={evolution_current}/{evolution_max}")

                # Calculate percentages from clean data
                # None at the final level, where there is no next goal
                if Power_max and Power_max > 0:
                    Power_percentage = min(100, max(0, (Power_current / Power_max) * 100))
                    Power_bar = self._create_progress_bar(Power_percentage)
                    logger.info(f"NEW SERVICE: Power bar {Power_percentage:.1f}% ({Power_current}/{Power_max})")
                else:
                    Power_bar = self._create_progress_bar(0)
                    Power_percentage = 0
                    logger.info(f"NEW SERVICE: Power bar 0% (max=0)")

                # Evolution bar from clean data
                if evolution_max > 0:
                    next_percentage = min(100, max(0, (evolution_current / evolution_max) * 100))
                    next_bar = self._create_progress_bar(next_percentage)
                    logger.debug(f"EVOLUTION: raw values evolution_current={evolution_current}, evolution_max={evolution_max}")
                    logger.debug(f"EVOLUTION: types evolution_current={type(evolution_current)}, evolution_max={type(evolution_max)}")
                    logger.debug(f"EVOLUTION: ({evolution_current}/{evolution_max})*100 = {(evolution_current/evolution_max)*100:.2f}%")
                    logger.debug(f"EVOLUTION: next_percentage={next_percentage:.1f}%")
                    logger.info(f"NEW SERVICE: Evolution bar {next_percentage:.1f}% ({evolution_current}/{evolution_max})")
                else:
                    next_bar = self._create_progress_bar(0)
                    next_percentage = 0
                    logger.info(f"NEW SERVICE: Evolution bar 0% (max level reached)")

                # Create EXPANDED mech status text with detailed information (no bold formatting)
                evolution_name = translate(evolution['name'])
                level_text = translate("Level")
                mech_status = f"{evolution_name} ({level_text} {evolution['level']})\n"
                speed_text = translate("Speed")
                mech_status += f"{speed_text}: {speed['description']}\n\n"

                # Special handling for Level 11 - corrupted power bar
                if evolution['level'] == 11:
                    # Heavily corrupted power bar - same characters as evolution bar, different distribution
                    # Power bar: 23 chars with ░(10), #(5), %(2), !(2), &(2), @(2) - same count, different pattern
                    corrupted_power_bar = "@#&░!░%#░░#!░%░&░#@░░#%"  # 23 characters: fuel/power bar
                    corrupted_power_percentage = f"#{Power_percentage:.1f}%&"
                    mech_status += f"⚡{current_Power:.2f}\n`{corrupted_power_bar}` {corrupted_power_percentage}\n"
                else:
                    mech_status += f"⚡{current_Power:.2f}\n`{Power_bar}` {Power_percentage:.1f}%\n"

                # Get level-specific decay rate (SERVICE FIRST: unified evolution system)
                from services.mech.mech_evolutions import get_evolution_level_info
                evolution_info = get_evolution_level_info(mech_cache_result.level)
                decay_per_day = evolution_info.decay_per_day if evolution_info else None

                mech_status += power_consumption_line(decay_per_day) + "\n\n"

                if evolution.get('next_name'):
                    next_evolution_name = translate(evolution['next_name'])

                    # Special handling for Level 10 → Level 11 progression (ALWAYS show corrupted bar)
                    if mech_cache_result.level == 10 or "ERR#R" in next_evolution_name or "DATA_C0RR*PTED" in next_evolution_name:
                        # Create heavily corrupted progress bar with distorted characters
                        # Evolution bar: 23 chars with ░(10), #(5), %(2), !(2), &(2), @(2)
                        corrupted_bar = "░%#!░&░#░@░░#!#%░░&░#@░"  # 23 characters: evolution progression

                        # For Level 10 → 11: Show REAL progression with corrupted display
                        if mech_cache_result.level == 10:
                            # Use actual percentage to Level 11, but display corrupted
                            corrupted_percentage = f"#{next_percentage:.1f}%&"
                            next_evolution_prefix = "ERR#R: [DATA_C0RR*PTED]"
                        else:
                            # For Level 11 itself: force 100% display (max evolution reached)
                            corrupted_percentage = "#100.0%&"
                            next_evolution_prefix = "⚠️"

                        mech_status += f"{next_evolution_prefix}\n`{corrupted_bar}` {corrupted_percentage}"
                    else:
                        mech_status += f"⬆️ {next_evolution_name}\n`{next_bar}` {next_percentage:.1f}%"
                else:
                    max_evolution_text = translate("MAX EVOLUTION REACHED!")
                    mech_status += f"🌟 {max_evolution_text}"

                # Glvl info is now included in speed description, no need for separate line

                embed.add_field(name=translate("Donation Engine"), value=mech_status, inline=False)

                # For expanded view, use mech animation
                if animation_file:
                    # KEEP ORIGINAL EXTENSION for WebP embedding support
                    original_ext = animation_file.filename.split('.')[-1]
                    animation_file.filename = f"mech_animation.{original_ext}"
                    embed.set_image(url=f"attachment://mech_animation.{original_ext}")
                    logger.debug(f"Set expanded animation with extension: {original_ext}")
                else:
                    # For refreshes without animation file, reference existing with correct extension
                    embed.set_image(url="attachment://mech_animation.webp")  # Assume WebP for new system

            except Exception as e:  # noqa: BLE001
                # Broad on purpose (review E20). The container list is already in
                # embed.description by the time this block runs; the mech is
                # decoration on top of it. Anything that escapes here takes the
                # finished list with it, and the operator loses the thing they
                # need - is my server up? - because of the thing they do not.
                #
                # This file already records that happening: the comment above
                # describes an ImportError that "escaped the handler below (it
                # only catches DiscordException/RuntimeError/OSError/KeyError),
                # so expanding the mech section in Discord crashed outright".
                # That was repaired by fixing the import. The shape that let one
                # bad import take the whole overview down was left alone.
                logger.error(f"Could not load expanded mech status for /ss: {e}", exc_info=True)
        else:
            # Donations disabled - no mech components
            animation_files = None
            logger.info("Donations disabled - skipping mech status for /ss")

        # Add website URL as footer for better spacing
        with_website_footer(embed)

        # Return tuple (embed, animation_file) - single file for expanded view
        return embed, animation_file

    async def _create_admin_overview_embed(self, ordered_servers, config, force_refresh=False):
        """Creates the admin overview embed with CPU and RAM details for control channels.

        NEW FORMAT: Clean grid layout using Discord fields (inline=true).
        Each container gets a field with status emoji, name (max 14 chars), and CPU/RAM on one line.

        Args:
            ordered_servers: List of server configurations
            config: Application configuration
            force_refresh: If True, forces fresh data from cache

        Returns:
            tuple: (embed, None, has_running_containers) - No animation for admin overview
        """
        from .translation_manager import _ as translate
        import discord
        from datetime import datetime, timezone

        # Get current time in local timezone
        now_utc = datetime.now(timezone.utc)
        fresh_config = load_config()
        timezone_str = fresh_config.get('timezone') if fresh_config else config.get('timezone')
        current_time = format_datetime_with_timezone(now_utc, timezone_str, time_only=True)

        # Count containers by status
        total_containers = len(ordered_servers)
        online_count = 0
        offline_count = 0

        # Track if any containers are running for bulk actions
        has_running_containers = False

        # Create the embed with dark-mode friendly color
        embed = discord.Embed(
            title=translate("Admin Overview"),
            color=0x2f3136  # Dark grey, dark-mode friendly
        )

        # Build description header
        # The counts are not known yet - the loop below does the counting - so
        # this slot is filled once, afterwards, and nothing is formatted twice.
        #
        # It used to build the whole line here with online='{online}' and
        # offline='{offline}' passed as LITERAL strings, so they survived the
        # format and could be filled later. They never were: the line further
        # down rebuilds the string from scratch, so that first build was a
        # catalogue lookup and a format whose result was thrown away on every
        # admin overview. And it looked deliberate, which is the worse half -
        # if the rebuild ever stopped running, the operator's panel would read
        # "Online: {online}" in words (review E42).
        header_lines = [
            translate("Last update") + f": {current_time}",
            "",
        ]

        # Collect container lines separately (will add spacing between them later)
        container_lines = []
        # The Compose stack of each line (None outside a stack or not known yet)
        line_stacks = []

        # Process each container and add line to list
        for server_conf in ordered_servers:
            display_name = server_conf.get('display_name', server_conf.get('docker_name'))
            docker_name = server_conf.get('docker_name')
            if not display_name or not docker_name:
                continue

            # Get cached status data
            # Use docker_name as cache key (stable identifier)
            cached_entry = self.status_cache_service.get(docker_name)
            status_result = None

            if cached_entry and cached_entry.get('data'):
                from utils.settings import get_setting
                max_cache_age = get_setting('DDC_DOCKER_MAX_CACHE_AGE', 300)

                if 'timestamp' in cached_entry:
                    cache_age = (datetime.now(timezone.utc) - cached_entry['timestamp']).total_seconds()
                    if cache_age > max_cache_age:
                        logger.debug(f"Cache for {display_name} expired")
                        cached_entry = None

                if cached_entry and cached_entry.get('data'):
                    status_result = cached_entry['data']

            # Check if container has info configured
            has_info = False
            try:
                from services.infrastructure.container_info_service import get_container_info_service
                info_service = get_container_info_service()
                info_result = info_service.get_container_info(docker_name)
                if info_result.success and info_result.data.enabled:
                    has_info = True
            except (discord.errors.DiscordException, RuntimeError):
                pass

            # Process status and build field
            # NOW USING ContainerStatusResult Objects (not tuples)
            from services.docker_status.models import ContainerStatusResult

            if status_result and isinstance(status_result, ContainerStatusResult) and status_result.success:
                # Extract data from ContainerStatusResult object
                is_running = status_result.is_running
                cpu_str = status_result.cpu
                ram_str = status_result.ram

                # Determine status emoji (EXACTLY same logic as Server Overview)
                # Check pending actions using docker_name as key
                if docker_name in self.pending_actions:
                    pending_timestamp = self.pending_actions[docker_name]['timestamp']
                    pending_duration = (now_utc - pending_timestamp).total_seconds()
                    if pending_duration < 120:
                        status_emoji = "🟡"
                        status_text = translate("Pending")
                    else:
                        del self.pending_actions[docker_name]
                        status_emoji = "🟢" if is_running else "🔴"
                else:
                    status_emoji = "🟢" if is_running else "🔴"

                # Count online/offline. A container Docker says does not EXIST
                # renders as "❓ ... not found" and is neither: counted as offline
                # it promised the operator a stopped container they could start
                # (SPEC.md Z3, one state further).
                if is_running:
                    has_running_containers = True
                    online_count += 1
                elif not getattr(status_result, 'not_found', False):
                    offline_count += 1

                # Truncate name to max 12 characters (shorter for single-line format)
                if len(display_name) > 12:
                    truncated_name = display_name[:12] + "…"
                else:
                    truncated_name = display_name

                # Build field name - EVERYTHING in one line
                if is_running:
                    # Format CPU: ensure 1 decimal place
                    try:
                        # cpu_str is like "0.4%" or "12%"
                        if cpu_str and cpu_str != "N/A":
                            cpu_value = float(cpu_str.replace('%', '').strip())
                            cpu_formatted = f"{cpu_value:.1f}%"
                        else:
                            cpu_formatted = "—%"
                    except (ValueError, AttributeError):
                        cpu_formatted = "—%"

                    # Format RAM: convert MB to GB with 1 decimal place
                    try:
                        # ram_str is like "2060 MB" or "2060MB"
                        if ram_str and ram_str != "N/A":
                            ram_mb = float(ram_str.replace('MB', '').replace(' ', '').strip())
                            ram_gb = ram_mb / 1024
                            ram_formatted = f"{ram_gb:.1f}GB"
                        else:
                            ram_formatted = "—GB"
                    except (ValueError, AttributeError):
                        ram_formatted = "—GB"

                    # Build single-line: "🟢 Name · cpu% • ramGB ⓘ"
                    # Use middot (·) as separator, ⓘ only if has info.
                    # Details switched off for this container are NOT a failed
                    # measurement: "Hidden" does not parse as a number, so the row
                    # used to read "—% • —GB", which the operator reads as "DDC
                    # could not measure it".
                    if not getattr(status_result, 'details_allowed', True):
                        container_line = f"{status_emoji} {truncated_name} · 🔒 {translate('Hidden')}"
                    else:
                        container_line = f"{status_emoji} {truncated_name} · {cpu_formatted} • {ram_formatted}"
                    if has_info:
                        container_line += " ⓘ"
                elif status_result.not_found:
                    # Deleted/renamed container: "❓ Name · not found"
                    container_line = f"❓ {truncated_name} · {translate('not found')}"
                    if has_info:
                        container_line += " ⓘ"
                else:
                    # Container is stopped: "🔴 Name · offline"
                    container_line = f"{status_emoji} {truncated_name} · {translate('offline')}"
                    if has_info:
                        container_line += " ⓘ"

                # Add to container lines list
                container_lines.append(container_line)
                line_stacks.append(getattr(status_result, 'compose_project', None))
            else:
                # No status data available - show loading status (same as Server Overview).
                # NOT counted as offline: the line says "loading", and counting it as
                # offline made the header read "Online: 0 • Offline: 5" right after a
                # restart - a guessed result the admin reads as "everything is down"
                # (SPEC.md Z3, review B8). Online + Offline is then smaller than the
                # total, which is the honest picture: those containers are not known yet.
                status_emoji = "🔄"

                # Truncate name to max 12 characters
                if len(display_name) > 12:
                    truncated_name = display_name[:12] + "…"
                else:
                    truncated_name = display_name

                # Single-line format: "🔄 Name"
                container_line = f"{status_emoji} {truncated_name}"
                if has_info:
                    container_line += " ⓘ"

                # Add to container lines list
                container_lines.append(container_line)
                line_stacks.append(None)

        # A bold stack heading before the first container of each stack, in the
        # server order: a scattered stack shows its heading again where it
        # reappears ("Sort by stack" in the panel brings it together).
        previous_stack = None
        for index, stack in enumerate(line_stacks):
            if stack and stack != previous_stack:
                container_lines[index] = f"**{discord.utils.escape_markdown(stack)}**\n" + container_lines[index]
            previous_stack = stack

        # The lines that were actually built, not the configured entries: the loop
        # above skips an entry without a display name or docker name, and the
        # header used to promise more containers than it showed.
        # The groups, as their own block after the containers. Same helper as
        # the other two views, so a group cannot appear in one and not another.
        group_lines = group_status_lines(getattr(self, 'status_cache_service', None), translate,
                                         boxed=False)
        # EACH LINE ITS OWN BLOCK, not one joined block (operator, 2026-09-24):
        # this view spaces its entries with a separator, and a joined block got
        # none of it - the group section stood closer together than everything
        # above it.
        container_lines.extend(group_lines)

        # The lines that were actually built. The groups are NOT counted here:
        # the header says how many CONTAINERS there are, and a group is not one.
        total_containers = len(container_lines) - len(group_lines)
        header_lines[1] = translate("Container: {total} • Online: {online} • Offline: {offline}").format(total=total_containers, online=online_count, offline=offline_count)

        # Build final description with consistent spacing between container lines
        # Use Hangul filler (ㅤ U+3164) on separator line to match ⓘ height.
        # Cut to what Discord accepts: an embed description longer than 4096
        # characters is REFUSED, so on a large installation the whole admin
        # overview never appeared - the last line says how many are missing.
        from services.discord.embed_helper_service import fit_lines

        head = "\n".join(header_lines) + "\n\n"
        embed.description = fit_lines(
            container_lines, separator="\nㅤ\n", prefix=head,
            more=lambda count: translate("… and {count} more containers").format(count=count))

        # Add footer
        with_website_footer(embed)

        return embed, None, has_running_containers

    async def _create_overview_embed_collapsed(self, ordered_servers, config, force_refresh=False):
        """Creates the server overview embed with COLLAPSED mech status (animation only).

        Args:
            ordered_servers: List of server configurations
            config: Application configuration
            force_refresh: If True, forces fresh data from cache (for manual commands)

        Returns:
            tuple: (embed, animation_file) where animation_file is None if no animation
        """
        # Import translation function locally to ensure it's accessible
        from .translation_manager import _ as translate
        import discord
        import time
        from io import BytesIO

        # Initialize animation file
        animation_file = None

        # Create the overview embed
        embed = discord.Embed(
            title=translate("Server Overview"),
            color=discord.Color.blue()
        )

        # Build server status lines (same logic as original)
        now_utc = datetime.now(timezone.utc)
        fresh_config = load_config()
        timezone_str = fresh_config.get('timezone') if fresh_config else config.get('timezone')

        current_time = format_datetime_with_timezone(now_utc, timezone_str, time_only=True)

        # Add timestamp at the top
        last_update_text = translate("Last update")

        # Start building the content (same server status logic as original)
        content_lines = [
            f"{last_update_text}: {current_time}",
            "┌── Status ─────────────────"
        ]

        # Add server statuses (copy from original method - same logic)
        for server_conf in ordered_servers:
            display_name = server_conf.get('display_name', server_conf.get('docker_name'))
            docker_name = server_conf.get('docker_name')
            if not display_name or not docker_name:
                continue

            # Use cached data only (same as original)
            # Use docker_name as cache key (stable identifier)
            cached_entry = self.status_cache_service.get(docker_name)
            status_result = None

            if cached_entry and cached_entry.get('data'):
                from utils.settings import get_setting
                max_cache_age = get_setting('DDC_DOCKER_MAX_CACHE_AGE', 300)

                if 'timestamp' in cached_entry:
                    cache_age = (datetime.now(timezone.utc) - cached_entry['timestamp']).total_seconds()
                    if cache_age > max_cache_age:
                        logger.debug(f"Cache for {display_name} expired ({cache_age:.1f}s > {max_cache_age}s)")
                        cached_entry = None

                if cached_entry and cached_entry.get('data'):
                    status_result = cached_entry['data']
            else:
                logger.debug(f"[/serverstatus] No cache entry for '{display_name}' - Background loop will update")
                status_result = None

            # Check if container has info available (same as original)
            info_indicator = ""
            try:
                from services.infrastructure.container_info_service import get_container_info_service
                info_service = get_container_info_service()
                info_result = info_service.get_container_info(docker_name)
                if info_result.success and info_result.data.enabled:
                    info_indicator = " ℹ️"
            except (RuntimeError, ValueError, KeyError, OSError) as e:
                logger.debug(f"Could not check info status for {docker_name}: {e}")

            # Process status result - NOW USING ContainerStatusResult Objects (not tuples)
            # Check if we have a successful ContainerStatusResult
            from services.docker_status.models import ContainerStatusResult

            if status_result and isinstance(status_result, ContainerStatusResult) and status_result.success:
                is_running = status_result.is_running

                # Determine status icon (same logic as original)
                # Check pending actions using docker_name as key
                if docker_name in self.pending_actions:
                    pending_timestamp = self.pending_actions[docker_name]['timestamp']
                    pending_duration = (now_utc - pending_timestamp).total_seconds()
                    if pending_duration < 120:
                        status_emoji = "🟡"
                        status_text = translate("Pending")
                    else:
                        del self.pending_actions[docker_name]
                        status_emoji = "🟢" if is_running else "🔴"
                else:
                    status_emoji = "🟢" if is_running else "🔴"

                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                # Compact live player count (e.g. "  3/8") for running game servers with query data
                from services.discord.embed_helper_service import format_player_inline
                player_indicator = format_player_inline(status_result.players_online, status_result.max_players)
                # Add status line: status emoji, name, player count, info indicator
                line = f"│ {status_emoji} {truncated_name}{player_indicator}{info_indicator}"
                if status_result.not_found:
                    # Deleted/renamed container: own state instead of 🔴 or an endless 🔄
                    line = f"│ ❓ {truncated_name} · {translate('not found')}{info_indicator}"
                content_lines.append(line)
            else:
                # No cache data available - show loading status
                status_emoji = "🔄"
                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                line = f"│ {status_emoji} {truncated_name}{info_indicator}"
                content_lines.append(line)

        # The operator's groups, below the containers and set apart from them
        # (group_status_lines). Empty when he has none.
        content_lines.extend(group_status_lines(getattr(self, 'status_cache_service', None), translate))

        # Close server status box
        content_lines.append("└───────────────────────────")

        # Combine all lines into the description, cut to what Discord accepts:
        # an embed description longer than 4096 characters is REFUSED, and the
        # list grows with the installation (see
        # tests/spec/test_a_long_container_list_still_reaches_discord.py).
        from services.discord.embed_helper_service import fit_lines

        embed.description = fit_lines(
            content_lines, prefix="```\n", suffix="\n```",
            more=lambda count: translate("… and {count} more containers").format(count=count))

        # Check if any containers have info available
        has_any_info = False
        try:
            from services.infrastructure.container_info_service import get_container_info_service
            info_service = get_container_info_service()
            for server_conf in ordered_servers:
                docker_name = server_conf.get('docker_name')
                if docker_name:
                    info_result = info_service.get_container_info(docker_name)
                    if info_result.success and info_result.data.enabled:
                        has_any_info = True
                        break
        except (KeyError, AttributeError, ValueError) as e:
            logger.debug(f"Could not check info availability: {e}")

        # Help text removed - replaced with Help button in MechView

        # Check if donations are disabled by premium key
        from services.donation.donation_utils import is_donations_disabled
        donations_disabled = is_donations_disabled()

        # Add COLLAPSED Mech Status (animation only, no text details) (skip if donations disabled)
        animation_file = None
        if not donations_disabled:
            try:
                import sys
                # Add project root to Python path for service imports
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                # SERVICE FIRST: Use MechStatusCacheService for instant response
                from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
                cache_service = get_mech_status_cache_service()
                cache_request = MechStatusCacheRequest(include_decimals=True, force_refresh=force_refresh)
                mech_cache_result = cache_service.get_cached_status(cache_request)

                if not mech_cache_result.success:
                    # Callers unpack (embed, animation_file) - never return None here. Skip the
                    # mech section via the handler below and still return the server overview.
                    raise RuntimeError(f"Failed to get cached mech status for animation: {mech_cache_result.error_message}")

                current_Power = mech_cache_result.power
                logger.info(f"CACHE (collapsed): Using cached power data: {current_Power} (age: {mech_cache_result.cache_age_seconds:.1f}s)")

                # Create mech animation with fallback
                try:
                    from services.mech.animation_cache_service import get_animation_cache_service
                    from services.mech.speed_levels import get_combined_mech_status

                    # Get animation cache service and use actual evolution level
                    cache_service = get_animation_cache_service()
                    # UNIFICATION: Use actual mech level instead of calculating from donations
                    evolution_level = mech_cache_result.level

                    # SPEED UNIFICATION: Calculate actual speed level from current power (same as MechWebService/Status Overview)
                    # SPECIAL CASE: Level 11 is maximum level - always use Speed Level 100 (same logic as all other services)
                    if evolution_level >= 11:
                        actual_speed_level = 100  # Level 11 always has maximum speed (divine speed)
                    else:
                        # Real level + its power bar maximum (not a level guessed from the power amount)
                        speed_status = get_combined_mech_status(
                            current_Power, evolution_level=evolution_level,
                            power_max=getattr(getattr(mech_cache_result, 'bars', None), 'Power_max_for_level', None))
                        actual_speed_level = speed_status['speed']['level']

                    # Get animation bytes with power-based selection (REST if power=0, WALK if power>0)
                    animation_bytes = cache_service.get_animation_with_speed_and_power(
                        evolution_level=evolution_level,
                        speed_level=actual_speed_level,  # Use actual speed level (unified with Big Mech)
                        power_level=current_Power
                    )

                    # Convert to Discord File
                    buffer = BytesIO(animation_bytes)
                    animation_file = discord.File(buffer, filename=f"mech_status_collapsed_{int(time.time())}.webp", spoiler=False)
                except (RuntimeError, ValueError, KeyError, OSError) as e:
                    logger.warning(f"Animation service failed (graceful degradation): {e}")
                    animation_file = None
                    # Add fallback visual indicator in embed
                    if not embed.footer or not embed.footer.text:
                        embed.set_footer(text=translate("🎬 Animation service temporarily unavailable"))
                    else:
                        # The separator is structure, the words are language
                        # (review E35).
                        embed.set_footer(
                            text=f"{embed.footer.text} | {translate('🎬 Animation unavailable')}")

                # For collapsed view, only add a simple field name (no detailed info)
                embed.add_field(name=translate("Donation Engine"), value="*" + translate("Click + to view Mech details") + "*", inline=False)

                # For collapsed view, use mech animation
                if animation_file:
                    # KEEP ORIGINAL EXTENSION for WebP embedding support
                    original_ext = animation_file.filename.split('.')[-1]
                    animation_file.filename = f"mech_animation.{original_ext}"
                    embed.set_image(url=f"attachment://mech_animation.{original_ext}")
                    logger.debug(f"Set animation with extension: {original_ext}")
                else:
                    # For refreshes without animation file, reference existing with correct extension
                    embed.set_image(url="attachment://mech_animation.webp")  # Assume WebP for new system

            except Exception as e:  # noqa: BLE001 - same as the expanded builder (E20)
                logger.error(f"Could not load collapsed mech status for /ss: {e}", exc_info=True)
        else:
            # Donations disabled - no mech components
            animation_files = None
            logger.info("Donations disabled - skipping collapsed mech status for /ss")

        # Add website URL as footer for better spacing
        with_website_footer(embed)

        # Return tuple (embed, animation_file) - single file for collapsed view
        return embed, animation_file

    def _create_progress_bar(self, percentage: float, length: int = 30) -> str:
        """Create a text progress bar with consistent character widths for monospace."""
        filled = int((percentage / 100) * length)
        empty = length - filled
        # Use █ and ░ - these work best in monospace code blocks
        bar = "█" * filled + "░" * empty
        return bar
