# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Keeping DockerControlCog's Discord messages current.

Moved out of cogs/docker_control.py unchanged on 2026-09-22 (roadmap Phase 3,
the cog split): the periodic status message edit loop, the /ss message
refresh, the overview update after a donation, and updating or recovering a
deleted overview message. Rendering stays in overview_embeds.py; channel
setup and teardown stay in the cog.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
from utils.logging_utils import setup_logger

from .loop_safety import survives_one_bad_cycle
from .translation_manager import _

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)


def in_batches(items, size):
    """``items`` in chunks of ``size``, in order."""
    return [list(items[index:index + size]) for index in range(0, len(items), size)]


def mech_change(current_glvl, current_power, last_glvl):
    """(level changed, power depleted, level to remember) for one cycle.

    A state that could not be read is UNKNOWN, not zero. Zero is a value: with
    a channel that last saw level 5 it fired both triggers, deleted and
    reposted the overview, and wrote 0 into the remembered level - so the next
    successful cycle saw 5 against 0 and did it again.
    """
    if current_glvl is None:
        return False, False, None
    last_glvl = last_glvl or 0
    depleted = bool(current_power is not None and current_power <= 0 and last_glvl > 0)
    if abs(current_glvl - last_glvl) >= 1:
        return True, depleted, current_glvl
    if last_glvl == 0:                      # first cycle for this channel: just remember
        return False, depleted, current_glvl
    return False, depleted, None


class MessageUpdatesMixin:
    """Status and overview message maintenance, mixed into DockerControlCog."""


    # --- PERIODIC MESSAGE EDIT LOOP (FULL LOGIC, MOVED DIRECTLY INTO COG) ---
    @tasks.loop(minutes=1, reconnect=True)
    @survives_one_bad_cycle
    async def periodic_message_edit_loop(self):
        """Periodically checks and edits messages in channels that require updates."""
        config = load_config()
        if not config:
            logger.error("Periodic Edit Loop: Could not load configuration. Skipping cycle.")
            return

        # The cycle announces nothing on the way in. What it did is logged
        # when it is done: "... finished. Total tasks: N. Success: ...".
        logger.debug("--- DIRECT COG periodic_message_edit_loop cycle --- Starting Check --- ")
        if not self.initial_messages_sent:
             logger.debug("Direct Cog Periodic edit loop: Initial messages not sent yet, skipping.")
             return

        logger.debug(f"Direct Cog Periodic Edit Loop: Checking {len(self.channel_server_message_ids)} channels with tracked messages.")

        tasks_to_run = []
        now_utc = datetime.now(timezone.utc)

        channel_permissions_config = config.get('channel_permissions', {})
        # Get default permissions from config
        default_perms = {}

        # Create snapshot to avoid TOCTOU issues with concurrent dict modifications
        channel_ids_snapshot = list(self.channel_server_message_ids.keys())

        for channel_id in channel_ids_snapshot:
            # Re-check existence after snapshot (dict may have changed)
            if channel_id not in self.channel_server_message_ids or not self.channel_server_message_ids[channel_id]:
                logger.debug(f"Direct Cog Periodic Edit Loop: Skipping channel {channel_id}, no server messages tracked or channel entry removed.")
                continue

            channel_config = channel_permissions_config.get(str(channel_id), default_perms)
            enable_refresh = channel_config.get('enable_auto_refresh', default_perms.get('enable_auto_refresh', True))
            update_interval_minutes = channel_config.get('update_interval_minutes', default_perms.get('update_interval_minutes', 5))
            update_interval_delta = timedelta(minutes=update_interval_minutes)

            if not enable_refresh:
                logger.debug(f"Direct Cog Periodic Edit Loop: Auto-refresh disabled for channel {channel_id}. Skipping.")
                continue

            server_messages_in_channel = self.channel_server_message_ids[channel_id]
            logger.debug(f"Direct Cog Periodic Edit Loop: Processing channel {channel_id} (Refresh: {enable_refresh}, Interval: {update_interval_minutes}m). It has {len(server_messages_in_channel)} tracked messages.")

            if channel_id not in self.last_message_update_time:
                self.last_message_update_time[channel_id] = {}
                logger.info(f"Direct Cog Periodic Edit Loop: Initialized last_message_update_time for channel {channel_id}.")

            # Create snapshot to avoid TOCTOU issues
            display_names_snapshot = list(server_messages_in_channel.keys())

            for display_name in display_names_snapshot:
                # Re-check existence after snapshot
                if display_name not in server_messages_in_channel:
                    logger.debug(f"Direct Cog Periodic Edit Loop: Server '{display_name}' no longer tracked in channel {channel_id}. Skipping.")
                    continue

                message_id = server_messages_in_channel[display_name]
                last_update_time = self.last_message_update_time[channel_id].get(display_name)

                # EARLY CHECK: Special case for overview or admin_overview messages
                if display_name == "overview":
                    # SERVICE FIRST: Use StatusOverviewService for overview update decisions
                    try:
                        from services.discord.status_overview_service import get_status_overview_service
                        overview_service = get_status_overview_service()

                        last_activity = self.last_channel_activity.get(channel_id)
                        decision = overview_service.make_update_decision(
                            channel_id=channel_id,
                            global_config=config,
                            last_update_time=last_update_time,
                            reason="periodic_overview_check",
                            last_channel_activity=last_activity
                        )

                        if decision.should_update:
                            logger.debug(f"SERVICE_FIRST: Overview update approved - {decision.reason}")
                            tasks_to_run.append(self._update_overview_message(channel_id, message_id, "overview"))
                        else:
                            logger.debug(f"SERVICE_FIRST: Overview update skipped - {decision.skip_reason}")

                    except (ImportError, AttributeError, RuntimeError) as service_error:
                        logger.warning(f"SERVICE_FIRST: Error in overview decision service: {service_error}")
                        # Fall back to the channel's own interval - the same
                        # fallback the admin overview below has always used.
                        #
                        # This used to queue the update unconditionally, and the
                        # loop runs every minute: with the decision service
                        # broken, the overview was edited sixty times an hour for
                        # an operator who had asked for once (review E18). Two
                        # messages taking the same decision had two different
                        # fallbacks, and nobody decided that they should.
                        if last_update_time is None or (now_utc - last_update_time) >= update_interval_delta:
                            tasks_to_run.append(self._update_overview_message(channel_id, message_id, "overview"))

                    continue  # Overview message handled, move to next message

                # EARLY CHECK: Special case for admin_overview message - uses same update logic
                if display_name == "admin_overview":
                    # Admin overview uses the same update logic as standard overview
                    try:
                        from services.discord.status_overview_service import get_status_overview_service
                        overview_service = get_status_overview_service()

                        last_activity = self.last_channel_activity.get(channel_id)
                        decision = overview_service.make_update_decision(
                            channel_id=channel_id,
                            global_config=config,
                            last_update_time=last_update_time,
                            reason="periodic_admin_overview_check",
                            last_channel_activity=last_activity
                        )

                        if decision.should_update:
                            logger.debug(f"SERVICE_FIRST: Admin Overview update approved - {decision.reason}")
                            tasks_to_run.append(self._update_overview_message(channel_id, message_id, "admin_overview"))
                        else:
                            logger.debug(f"SERVICE_FIRST: Admin Overview update skipped - {decision.skip_reason}")

                    except (ImportError, AttributeError, RuntimeError) as service_error:
                        logger.warning(f"SERVICE_FIRST: Error in admin overview decision service: {service_error}")
                        # Fallback to simple update interval check
                        if last_update_time is None or (now_utc - last_update_time) >= update_interval_delta:
                            tasks_to_run.append(self._update_overview_message(channel_id, message_id, "admin_overview"))

                    continue  # Admin overview message handled, move to next message

                # CRITICAL FIX: Skip individual server messages - we only use overview messages now
                # Individual container messages are now private per architecture change
                logger.debug(f"Skipping individual server message for '{display_name}' - only overview messages are supported")

                # Clean up the phantom entry from tracking
                if display_name not in ["overview", "admin_overview"]:
                    logger.warning(f"Removing phantom individual server entry '{display_name}' from channel {channel_id} tracking")
                    del server_messages_in_channel[display_name]
                    if display_name in self.last_message_update_time.get(channel_id, {}):
                        del self.last_message_update_time[channel_id][display_name]

        if tasks_to_run:
            # There used to be a per-container bulk pre-load here, guarded by a set of
            # container names that has been empty on every cycle since individual server
            # messages were dropped in favour of the overview - so it announced work in
            # the log that it never did (review B15). _ensure_status_cache_fresh() below
            # is what actually keeps the edits from rendering stale data.
            logger.debug(f"Direct Cog Periodic Edit Loop: Attempting to run {len(tasks_to_run)} message edit tasks.")

            # Refresh the status cache at most once per cycle (only if stale) BEFORE the batches,
            # so the per-message updates render from cache and actually run in parallel.
            await self._refresh_cache_for_cycle()

            # ULTRA-PERFORMANCE: Batched parallelization for message edits
            start_batch_time = datetime.now(timezone.utc)
            total_tasks = len(tasks_to_run)
            success_count = 0
            not_found_count = 0
            error_count = 0
            none_results_count = 0

            try:
                # Plain chunks, in order. Until 2026-09-22 this block sorted the
                # tasks into "slow" and "fast" containers by reading a coroutine's
                # frame through task._coro - an attribute of asyncio.Task, which
                # these are not - so everything fell into "fast", the distribution
                # did nothing, and every cycle logged "0 slow containers
                # distributed" about work that never happened.
                BATCH_SIZE = 3  # Process 3 messages at a time instead of all at once
                balanced_batches = in_batches(tasks_to_run, BATCH_SIZE)

                logger.debug(f"Direct Cog Periodic Edit Loop: Running {total_tasks} message edits "
                            f"in {len(balanced_batches)} batches of up to {BATCH_SIZE}")

                # Process balanced batches
                for batch_num, batch_tasks in enumerate(balanced_batches, 1):
                    total_batches = len(balanced_batches)

                    logger.debug(f"Direct Cog Periodic Edit Loop: Processing batch {batch_num}/{total_batches} with {len(batch_tasks)} tasks")

                    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

                    # Collect results from this batch
                    for result in batch_results:
                        if result is True:
                            success_count += 1
                        elif result is False:
                            not_found_count += 1
                        elif isinstance(result, Exception):
                            error_count += 1
                        else:
                            none_results_count += 1

                    # Small delay between batches to reduce API pressure
                    if batch_num < total_batches:  # Don't delay after last batch
                        await asyncio.sleep(0.5)
                        logger.debug(f"Direct Cog Periodic Edit Loop: Completed batch {batch_num}/{total_batches}, brief pause before next batch")

                # Performance analysis. The ladder is deliberate: a cycle
                # that was fast says nothing, one that took over three
                # seconds says so, and one over eight warns. The log gets
                # louder as things get worse instead of talking constantly.
                batch_time = (datetime.now(timezone.utc) - start_batch_time).total_seconds() * 1000

                if batch_time < 1000:  # Under 1 second - excellent
                    logger.debug(f"Direct Cog Periodic Edit Loop: ULTRA-FAST batched processing completed in {batch_time:.1f}ms")
                elif batch_time < 3000:  # Under 3 seconds - good
                    logger.debug(f"Direct Cog Periodic Edit Loop: FAST batched processing completed in {batch_time:.1f}ms")
                elif batch_time < 8000:  # Under 8 seconds - acceptable for batched processing
                    logger.info(f"Direct Cog Periodic Edit Loop: ACCEPTABLE batched processing completed in {batch_time:.1f}ms")
                else:  # Over 8 seconds - needs investigation
                    logger.warning(f"Direct Cog Periodic Edit Loop: SLOW batched processing took {batch_time:.1f}ms")

            except (discord.errors.DiscordException, RuntimeError, OSError, KeyError) as e:
                logger.error(f"Critical error during batched message edit processing: {e}", exc_info=True)
                error_count = total_tasks  # Assume all failed

            logger.info(f"Direct Cog Periodic message update finished. Total tasks: {total_tasks}. Success: {success_count}, NotFound: {not_found_count}, Errors: {error_count}, NoEmbed: {none_results_count}")

            if error_count > 0:
                logger.warning(f"Encountered {error_count} errors during batched processing")

            # Performance summary
            avg_time_per_edit = (datetime.now(timezone.utc) - start_batch_time).total_seconds() * 1000 / total_tasks if total_tasks > 0 else 0
            logger.debug(f"Direct Cog Periodic Edit Loop: Average time per message edit: {avg_time_per_edit:.1f}ms")
        else:
            logger.info("Direct Cog Periodic message update check: No messages were due for update in any channel.")

    # Wrapper for editing, needs to be part of this Cog now if periodic_message_edit_loop uses it.
    async def _refresh_cache_for_cycle(self):
        """Refresh the status cache for this cycle; never raise.

        This call used to sit outside the guarded part, after the cycle's edit
        coroutines had been built: a failure was swallowed by the loop guard,
        those coroutines were collected without ever being awaited, and nothing
        in the DDC log said the cycle had been lost.
        """
        try:
            await self._ensure_status_cache_fresh()
        except Exception as e:  # noqa: BLE001 - the cycle goes on with what the cache holds
            logger.warning(f"Status cache could not be refreshed this cycle ({e}) - "
                           f"editing from what the cache holds")

    async def _auto_update_ss_messages(self, reason: str, force_recreate: bool = True):
        """Auto-update all existing /ss messages in channels after donations

        Args:
            reason: Reason for the update
            force_recreate: If True, delete and recreate messages (for animation updates)
                          If False, just edit the embed (for expand/collapse)
        """
        try:
            logger.info(f"🔄 Auto-updating /ss messages: {reason}")

            # Get all channels with overview messages
            updated_count = 0
            # A snapshot, like the periodic loop: a config save pops or adds a
            # channel from another task while this loop awaits, and iterating the
            # live dict then raised "dictionary changed size during iteration" -
            # swallowed by the handler below, silently abandoning every channel
            # after the current one.
            for channel_id, messages in list(self.channel_server_message_ids.items()):
                if 'overview' in messages:
                    # Per channel, and it has to be (review E23). Everything below
                    # decides EDIT or delete-and-repost for THIS channel, and it
                    # used to decide it in `force_recreate` - the function's own
                    # parameter - so the first channel that said "recreate" said it
                    # for every channel after it, in dictionary order, without
                    # their decisions ever being consulted. _edit_only_ss_messages
                    # exists to say "edit, do not recreate"; expanding a mech panel
                    # in one channel could delete and repost the overview in
                    # another, moving it to the bottom with a new id.
                    #
                    # The rate limiter further down is the clearest proof that per
                    # channel was the intent all along: should_force_recreate takes
                    # a channel id, and its answer was written to a shared variable.
                    recreate_this_channel = force_recreate
                    try:
                        channel = self.bot.get_channel(channel_id)
                        if not channel:
                            continue

                        message_id = messages['overview']
                        message = await channel.fetch_message(message_id)
                        if not message:
                            continue

                        # Get fresh server data
                        config = load_config()
                        if not config:
                            continue

                        # SERVICE FIRST: Check Web UI refresh/recreate settings before proceeding
                        try:
                            from services.discord.status_overview_service import get_status_overview_service
                            overview_service = get_status_overview_service()

                            # Get last update time for this channel
                            last_update_time = None
                            if channel_id in self.last_message_update_time and 'overview' in self.last_message_update_time[channel_id]:
                                last_update_time = self.last_message_update_time[channel_id]['overview']

                            # Make update decision based on Web UI settings
                            last_activity = self.last_channel_activity.get(channel_id)
                            decision = overview_service.make_update_decision(
                                channel_id=channel_id,
                                global_config=config,
                                last_update_time=last_update_time,
                                reason=reason,
                                force_refresh=False,  # This is auto-update, not manual
                                force_recreate=recreate_this_channel,
                                last_channel_activity=last_activity
                            )

                            # Skip if Service decides no update needed
                            if not decision.should_update:
                                logger.debug(f"SERVICE_FIRST: Skipping channel {channel_id} - {decision.skip_reason}")
                                continue

                            # Use Service decision for recreate logic
                            if decision.should_recreate:
                                recreate_this_channel = True
                                logger.debug(f"SERVICE_FIRST: Force recreate for channel {channel_id} - {decision.reason}")

                            logger.debug(f"SERVICE_FIRST: Updating channel {channel_id} - {decision.reason}")

                        except (ImportError, AttributeError, RuntimeError) as service_error:
                            logger.warning(f"SERVICE_FIRST: Error in decision service for channel {channel_id}: {service_error}")
                            # Continue with original logic if service fails (safe fallback)

                        # SERVICE FIRST: Use ServerConfigService instead of direct config access
                        server_config_service = get_server_config_service()
                        servers = server_config_service.get_all_servers()
                        ordered_servers = []
                        seen_docker_names = set()

                        # Apply server ordering
                        from services.docker_service.server_order import load_server_order
                        server_order = load_server_order()

                        for server_name in server_order:
                            for server in servers:
                                docker_name = server.get('docker_name')
                                if server.get('name') == server_name and docker_name and docker_name not in seen_docker_names:
                                    ordered_servers.append(server)
                                    seen_docker_names.add(docker_name)

                        # Add remaining servers
                        for server in servers:
                            docker_name = server.get('docker_name')
                            if docker_name and docker_name not in seen_docker_names:
                                ordered_servers.append(server)
                                seen_docker_names.add(docker_name)

                        # Auto-detect Glvl changes for force_recreate decision
                        current_glvl = None
                        try:
                            # Get current Power amount for Glvl calculation using CACHE
                            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
                            cache_service = get_mech_status_cache_service()
                            cache_request = MechStatusCacheRequest(include_decimals=True)
                            mech_cache_result = cache_service.get_cached_status(cache_request)

                            if mech_cache_result.success:
                                # Use cached glvl directly - no need for complex calculations
                                current_glvl = mech_cache_result.glvl
                                # BUGFIX: Extract current_Power from cache for power depletion check
                                current_Power = mech_cache_result.power
                            else:
                                # Unknown, not zero - see mech_change() above
                                current_glvl = None
                                current_Power = None
                        except (KeyError, ValueError, AttributeError) as e:
                            logger.debug(f"Could not get current Glvl: {e}")
                            current_glvl = None
                            current_Power = None

                        # Check if Glvl changed significantly (>= 1 level difference) or power reached 0
                        glvl_changed = False
                        power_depleted = False

                        last_glvl = self.last_glvl_per_channel.get(channel_id, 0)
                        glvl_changed, power_depleted, remember = mech_change(
                            current_glvl, current_Power, last_glvl)
                        if power_depleted:
                            from .translation_manager import _
                            logger.info(_("Mech power depleted - forcing animation update to show offline state"))
                        if glvl_changed:
                            from .translation_manager import _
                            logger.info(f"{_('Significant Glvl change detected')}: {last_glvl} → {current_glvl}")
                        if remember is not None:
                            self.last_glvl_per_channel[channel_id] = remember
                            self.mech_state_manager.set_last_glvl(channel_id, remember)

                        # Override force_recreate if significant Glvl change or power depletion detected
                        if (glvl_changed or power_depleted) and not recreate_this_channel:
                            # Check rate limit before allowing force_recreate
                            if self.mech_state_manager.should_force_recreate(channel_id):
                                recreate_this_channel = True
                                self.mech_state_manager.mark_force_recreate(channel_id)
                                from .translation_manager import _
                                if power_depleted:
                                    upgrade_text = _("Upgrading to force_recreate=True due to power depletion (offline mech)")
                                else:
                                    upgrade_text = _("Upgrading to force_recreate=True due to significant Glvl change")
                                logger.info(f"{upgrade_text}")
                            else:
                                logger.debug(f"Rate limited force_recreate for channel {channel_id} (Glvl change or power depletion)")
                                recreate_this_channel = False

                        # The overview has one shape; the big mech lives in the
                        # private panel the Mech button opens.
                        embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)

                        if recreate_this_channel:
                            # FIX B: serialize delete+recreate per channel and re-validate the
                            # tracked id first - another path (regenerate/recovery) may have already
                            # recreated this overview, in which case we must NOT post a second one.
                            async with self._get_channel_lock(channel_id):
                                if self.channel_server_message_ids.get(channel_id, {}).get('overview') != message_id:
                                    logger.debug(f"AUTO-UPDATE: overview for channel {channel_id} changed before recreate - skipping (already handled elsewhere)")
                                    continue

                                # Delete and recreate message with new animation
                                await message.delete()

                                # Create new view
                                from .control_ui import MechView
                                view = MechView(self, channel_id)

                                # Send new message with fresh animation
                                if animation_file:
                                    new_message = await self._send_message_with_files(channel, embed, animation_file, view)
                                else:
                                    new_message = await self._send_message_with_files(channel, embed, None, view)

                                # Update message tracking
                                self.channel_server_message_ids[channel_id]['overview'] = new_message.id
                                self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate
                                logger.info(f"🔄 AUTO-UPDATE: Successfully recreated /ss message in {channel.name} with new animation")
                        else:
                            # Just edit the embed (for expand/collapse - no new animation)
                            from .control_ui import MechView
                            view = MechView(self, channel_id)
                            await message.edit(embed=embed, view=view)
                            logger.info(f"✏️ AUTO-UPDATE: Successfully edited /ss message in {channel.name}")

                        updated_count += 1

                    except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                        logger.error(f"AUTO-UPDATE ERROR: Could not update /ss message in channel {channel_id}: {e}", exc_info=True)

            if updated_count > 0:
                logger.info(f"✅ Auto-updated {updated_count} /ss messages after donation")
            else:
                logger.debug("No /ss messages found to update")

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in _auto_update_ss_messages: {e}", exc_info=True)

    async def _edit_only_ss_messages(self, reason: str):
        """Edit-only update for /ss messages (used for expand/collapse)"""
        await self._auto_update_ss_messages(reason, force_recreate=False)

    async def _recover_deleted_overview(self, channel, channel_id: int, message_id: int,
                                        message_type: str, ordered_servers, config) -> bool:
        """FIX B: Recreate an overview/admin_overview whose tracked message was deleted.

        Runs under the per-channel lock and RE-VALIDATES first (B4): the periodic edit that
        hit NotFound is unlocked, so another path (regenerate / event recreate) may have
        already posted a fresh overview. If the tracked id no longer matches the deleted one,
        we abort instead of posting a second (duplicate) overview.
        """
        async with self._get_channel_lock(channel_id):
            # B4 re-validation: someone already recreated this overview -> do nothing.
            if self.channel_server_message_ids.get(channel_id, {}).get(message_type) != message_id:
                logger.debug(f"{message_type} for channel {channel_id} was already recreated by another path - skipping recovery")
                return True

            try:
                # Generate the recovery message that matches THIS channel's type, so an
                # admin_overview recovers as an Admin Overview (not a status overview that
                # would briefly flip until the next edit cycle).
                if message_type == "admin_overview":
                    embed, _ignored, has_running = await self._create_admin_overview_embed(
                        ordered_servers, config, force_refresh=False)
                    from .admin_overview import AdminOverviewView
                    view = AdminOverviewView(self, channel_id, has_running)
                    animation_file = None  # Admin Overview has no animation
                else:
                    embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
                    # The overview's buttons: Mech, info, admin, help
                    from .control_ui import MechView
                    view = MechView(self, channel_id)

                # Old bot messages before the new one - but NOT the operator's Live
                # Logs, not the auto-action notices, and not this channel's other
                # tracked overview (sweeping that one made the next cycle recover
                # it and sweep this one out again, once a minute).
                keep = {mid for key, mid in
                        self.channel_server_message_ids.get(channel_id, {}).items()
                        if key != message_type and mid}
                await self.cleanup_service.delete_bot_messages_preserve_live_logs(
                    channel=channel, reason="recovery from deleted message",
                    message_limit=100, keep_message_ids=keep)

                # Send new overview message as recovery
                if animation_file:
                    if hasattr(animation_file, 'fp') and animation_file.fp:
                        new_message = await channel.send(embed=embed, file=animation_file, view=view)
                    else:
                        new_message = await channel.send(embed=embed, view=view)
                else:
                    new_message = await channel.send(embed=embed, view=view)

                # Update tracking with new message ID.
                # Prerequisite 2: honor message_type ('overview' OR 'admin_overview') instead of
                # always writing 'overview', so we don't leave a stale key (and persist a corrupt
                # map) for control channels.
                if channel_id in self.channel_server_message_ids:
                    self.channel_server_message_ids[channel_id][message_type] = new_message.id
                    self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate

                now_utc = datetime.now(timezone.utc)
                if channel_id not in self.last_message_update_time:
                    self.last_message_update_time[channel_id] = {}
                self.last_message_update_time[channel_id][message_type] = now_utc

                logger.info(f"✅ RECOVERY SUCCESS: Auto-recreated {message_type} message {new_message.id} to replace deleted {message_id} in channel {channel_id}")
                return True  # Recovery successful

            except (discord.errors.DiscordException, RuntimeError) as recovery_error:
                logger.error(f"❌ RECOVERY FAILED: Could not auto-recreate {message_type} message for channel {channel_id}: {recovery_error}", exc_info=True)
                # Remove from tracking since we can't recover
                if channel_id in self.channel_server_message_ids and message_type in self.channel_server_message_ids[channel_id]:
                    del self.channel_server_message_ids[channel_id][message_type]
                    self._persist_tracked_message_ids()
                return False

    async def _update_overview_message(self, channel_id: int, message_id: int, message_type: str = "overview") -> bool:
        """
        Updates the overview or admin_overview message with current server statuses.

        Args:
            channel_id: Discord channel ID
            message_id: Discord message ID to update
            message_type: Type of message ("overview" or "admin_overview")

        Returns:
            bool: Success or failure
        """
        logger.debug(f"Updating {message_type} message {message_id} in channel {channel_id}")
        try:
            # Get channel. Handle a deleted channel HERE so the NotFound recovery handler below
            # only ever fires for a deleted MESSAGE (where channel/ordered_servers/config are
            # bound) - otherwise a missing channel would hit those names unbound.
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.NotFound:
                logger.warning(f"Channel {channel_id} not found - removing {message_type} from tracking.")
                if channel_id in self.channel_server_message_ids and message_type in self.channel_server_message_ids[channel_id]:
                    del self.channel_server_message_ids[channel_id][message_type]
                    self._persist_tracked_message_ids()
                return False
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"Channel {channel_id} is not a text channel, cannot update overview.")
                return False

            # Get message using partial message for better performance
            try:
                # PERFORMANCE OPTIMIZATION: Use partial message instead of fetch
                message = channel.get_partial_message(message_id)  # No API call
            except discord.NotFound:
                logger.warning(f"{message_type.capitalize()} message {message_id} in channel {channel_id} not found. Removing from tracking.")
                if channel_id in self.channel_server_message_ids and message_type in self.channel_server_message_ids[channel_id]:
                    del self.channel_server_message_ids[channel_id][message_type]
                    self._persist_tracked_message_ids()
                return False

            # Get all servers
            config = self.config
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()

            # Sort servers
            ordered_docker_names = self.ordered_server_names
            servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}

            ordered_servers = []
            seen_docker_names = set()

            # First add servers in the defined order
            for docker_name in ordered_docker_names:
                if docker_name in servers_by_name:
                    ordered_servers.append(servers_by_name[docker_name])
                    seen_docker_names.add(docker_name)

            # Add any servers that weren't in the ordered list
            for server in servers:
                docker_name = server.get('docker_name')
                if docker_name and docker_name not in seen_docker_names:
                    ordered_servers.append(server)
                    seen_docker_names.add(docker_name)

            # Create the updated embed and view based on message type
            if message_type == "admin_overview":
                # CACHE WARMUP: Refresh the cache only if it is stale (prevents 🔄 loading icons
                # without a full Docker bulk fetch per edited message - status_update_loop keeps it fresh)
                await self._ensure_status_cache_fresh()

                # Create Admin Overview embed
                embed, _animation_file, has_running = await self._create_admin_overview_embed(ordered_servers, config, force_refresh=False)
                # Create Admin Overview view
                from .admin_overview import AdminOverviewView
                view = AdminOverviewView(self, channel_id, has_running)
                animation_file = None  # Admin Overview doesn't have animations
            else:
                # CACHE WARMUP: Refresh the cache only if it is stale (see admin_overview branch)
                await self._ensure_status_cache_fresh()

                embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
                # Create MechView for standard overview
                from .control_ui import MechView
                view = MechView(self, channel_id)

            # Update the message (note: can't add files to edit, only embed)
            await message.edit(embed=embed, view=view)

            # Update message update timestamp, but NOT channel activity
            now_utc = datetime.now(timezone.utc)
            if channel_id not in self.last_message_update_time:
                self.last_message_update_time[channel_id] = {}
            self.last_message_update_time[channel_id][message_type] = now_utc

            # DO NOT update channel activity
            # This is commented out to fix the Recreate feature
            # self.last_channel_activity[channel_id] = now_utc

            logger.debug(f"Successfully updated {message_type} message {message_id} in channel {channel_id}")
            return True

        except discord.errors.NotFound:
            # Message was deleted - RECOVERY: Recreate it automatically
            logger.warning(f"{message_type.capitalize()} message {message_id} in channel {channel_id} not found (likely deleted). ATTEMPTING AUTOMATIC RECOVERY.")

            # Remove from old tracking system
            if hasattr(self, 'overview_message_ids') and channel_id in self.overview_message_ids:
                del self.overview_message_ids[channel_id]

            # FIX B: recreate under the per-channel lock with re-validation (see helper).
            return await self._recover_deleted_overview(
                channel, channel_id, message_id, message_type, ordered_servers, config)

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error updating overview message in channel {channel_id}: {e}", exc_info=True)
            return False
