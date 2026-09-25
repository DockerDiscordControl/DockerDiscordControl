# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Setting up, tearing down and regenerating DockerControlCog's channels.

Moved out of cogs/docker_control.py unchanged on 2026-09-22 (roadmap Phase 3,
the cog split): applying a channel configuration change, setting a channel up
and tearing it down, the initial status messages, regenerating a channel, and
deleting the bot's own messages (tracked overviews and a clean sweep).
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord

from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
from utils.logging_utils import setup_logger

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)


class ChannelLifecycleMixin:
    """Channel setup, teardown and regeneration, mixed into DockerControlCog."""


    async def _apply_channel_config_changes(self):
        """Apply channel configuration changes without restart."""
        # Semaphore prevents race condition from rapid consecutive saves
        if not hasattr(self, '_config_change_lock'):
            self._config_change_lock = asyncio.Semaphore(1)

        async with self._config_change_lock:
            try:
                await self.bot.wait_until_ready()

                # Force reload config
                from services.config.config_service import get_config_service
                config = get_config_service().get_config(force_reload=True)
                new_channel_permissions = config.get('channel_permissions', {})

                new_channel_ids = {int(cid) for cid in new_channel_permissions if cid.isdigit()}
                current_channel_ids = set(self.channel_server_message_ids.keys())

                added = new_channel_ids - current_channel_ids
                removed = current_channel_ids - new_channel_ids

                # Channels that stayed but changed what they are FOR. What DDC
                # tracks says which mode it built: 'admin_overview' for a control
                # channel, 'overview' for a status channel. Without this a channel
                # switched from serverstatus to control kept its server overview
                # until a restart, and the hot-reload said "nothing changed".
                switched = []
                for channel_id in new_channel_ids & current_channel_ids:
                    tracked = self.channel_server_message_ids.get(channel_id) or {}
                    if not tracked:
                        continue
                    commands = (new_channel_permissions.get(str(channel_id), {})
                                .get('commands', {}))
                    wants_control = bool(commands.get('control'))
                    built_control = 'admin_overview' in tracked
                    if wants_control != built_control:
                        switched.append(channel_id)

                if not added and not removed and not switched:
                    logger.info("Channel hot-reload: no channels added, removed or switched")
                    return

                logger.info(f"Channel hot-reload: {len(added)} added, {len(removed)} removed, "
                            f"{len(switched)} switched")

                # Teardown removed channels
                for channel_id in removed:
                    await self._teardown_channel(channel_id)

                # A switched channel is torn down and built again in its new mode
                for channel_id in switched:
                    await self._teardown_channel(channel_id)

                # Setup added and switched channels (with rate limit pause between each)
                to_set_up = list(added) + switched
                for channel_id in to_set_up:
                    channel_config = new_channel_permissions.get(str(channel_id), {})
                    await self._setup_channel(channel_id, channel_config)
                    if len(to_set_up) > 1:
                        await asyncio.sleep(2)  # Avoid Discord rate limits

                logger.info("Channel hot-reload completed successfully")

            except Exception as e:
                logger.error(f"Error applying channel config changes: {e}", exc_info=True)

    async def _teardown_channel(self, channel_id: int):
        """Clean up a removed channel: delete bot messages and remove tracking."""
        try:
            # FIX B: serialize the delete + tracking removal against any in-flight poster
            # for this channel so a teardown can't race a concurrent regenerate/command.
            async with self._get_channel_lock(channel_id):
                channel = self.bot.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    logger.info(f"Tearing down channel {channel.name} ({channel_id})")
                    try:
                        await self.delete_bot_messages(channel)
                    except Exception as e:
                        logger.warning(f"Could not delete messages in channel {channel_id}: {e}")

                self.channel_server_message_ids.pop(channel_id, None)
                self._persist_tracked_message_ids()  # FIX C: drop removed channel from persisted map

            # Remaining (non-message) tracking - safe outside the lock; drop the lock entry last.
            # Only while nobody is on it: a coroutine already waiting keeps its
            # reference, and the next caller would mint a NEW lock for the same
            # channel - two of them inside the section the lock exists for (FIX B).
            # A lock that is still busy is dropped the next time round.
            lock = self._channel_locks.get(channel_id)
            if lock is not None and not lock.locked() and not getattr(lock, '_waiters', None):
                self._channel_locks.pop(channel_id, None)
            self.last_message_update_time.pop(channel_id, None)
            self.last_channel_activity.pop(channel_id, None)
            if hasattr(self, 'last_glvl_per_channel'):
                self.last_glvl_per_channel.pop(channel_id, None)

            logger.info(f"Channel {channel_id} torn down")
        except Exception as e:
            logger.error(f"Error tearing down channel {channel_id}: {e}", exc_info=True)

    async def _setup_channel(self, channel_id: int, channel_config: dict):
        """Set up a newly added channel: send initial messages and start tracking."""
        try:
            if not channel_config.get('post_initial', False):
                logger.info(f"Channel {channel_id}: post_initial disabled, adding to tracking only")
                self.last_channel_activity[channel_id] = datetime.now(timezone.utc)
                return

            channel = await self.bot.fetch_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"Channel {channel_id} is not a text channel")
                return

            # Determine mode
            channel_commands = channel_config.get('commands', {})
            has_control = channel_commands.get('control', False)
            has_status = channel_commands.get('serverstatus', False)

            if has_control:
                mode = 'control'
            elif has_status:
                mode = 'status'
            else:
                logger.warning(f"Channel {channel_id} has no control/status permissions")
                return

            logger.info(f"Setting up new channel {channel.name} ({channel_id}) in {mode} mode")

            # FIX B: serialize delete+send against any concurrent poster (e.g. a user firing
            # /ss while this hot-reload runs) so we never post a duplicate overview.
            async with self._get_channel_lock(channel_id):
                # Clean old messages
                try:
                    # FIX C parity: remove the tracked overview by ID first (age-limited
                    # cleanup can skip a >30-day-old in-place-edited overview -> duplicate).
                    await self._delete_tracked_overview_messages(channel)
                    await self.delete_bot_messages(channel)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"Could not clean channel {channel_id}: {e}")

                # Populate cache before sending
                await self._background_cache_population()

                # Send initial messages
                if mode == 'control':
                    await self._send_control_panel_and_statuses(channel)
                else:
                    await self._send_all_server_statuses(channel)

            # Did anything actually get posted? Both senders swallow their own
            # failures, and an EMPTY entry makes the periodic loop skip this
            # channel for ever - the operator sees a blank channel and DDC never
            # tries again. Leave it out of the map instead, so the next
            # hot-reload treats it as a channel to add.
            tracked = self.channel_server_message_ids.get(channel_id) or {}
            if not tracked:
                self.channel_server_message_ids.pop(channel_id, None)
                logger.error(f"Channel {channel.name} ({channel_id}): nothing could be posted, "
                             f"so it is not tracked - the next channel save will try again")
                return

            # Start tracking
            self.last_channel_activity[channel_id] = datetime.now(timezone.utc)
            logger.info(f"Channel {channel.name} ({channel_id}) set up successfully in {mode} mode")

        except discord.NotFound:
            logger.warning(f"Channel {channel_id} not found on Discord")
        except discord.Forbidden:
            logger.warning(f"Missing permissions for channel {channel_id}")
        except Exception as e:
            logger.error(f"Error setting up channel {channel_id}: {e}", exc_info=True)

    # Send helpers (remain here as they interact closely with Cog state)
    async def _send_control_panel_and_statuses(self, channel: discord.TextChannel) -> None:
        """Send Admin Overview to control channels."""
        try:
            current_config = load_config()
            if not current_config:
                logger.error(f"Send Control Panel: Could not load configuration for channel {channel.id}.")
                return

            logger.info(f"Sending admin overview to control channel {channel.name} ({channel.id})")

            # CACHE WARMUP: Populate cache BEFORE creating admin overview
            # This prevents showing 🔄 loading icons during channel regeneration
            logger.debug("Starting cache population for admin overview (blocking to ensure data availability)")

            # Ensure semaphore exists
            if not hasattr(self, '_status_update_semaphore'):
                self._status_update_semaphore = asyncio.Semaphore(1)

            # Wait for cache to be populated before creating embed
            await self._background_cache_population()
            logger.info("Cache population complete for admin overview - proceeding with embed creation")

            # Get all server configurations
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            if not servers:
                logger.warning(f"No servers configured for channel {channel.id}")
                return

            # Sort servers by order
            ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

            # Create Admin Overview embed with CPU and RAM info
            embed, _, has_running = await self._create_admin_overview_embed(ordered_servers, current_config, force_refresh=True)

            # Import AdminOverviewView from admin_overview module
            from .admin_overview import AdminOverviewView

            # Create the Admin Overview view with buttons
            view = AdminOverviewView(self, channel.id, has_running)

            # Send the Admin Overview message
            try:
                message = await channel.send(embed=embed, view=view)

                # Track the message for automatic updates
                if channel.id not in self.channel_server_message_ids:
                    self.channel_server_message_ids[channel.id] = {}
                self.channel_server_message_ids[channel.id]['admin_overview'] = message.id
                self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate

                # Initialize update time tracking
                if channel.id not in self.last_message_update_time:
                    self.last_message_update_time[channel.id] = {}
                self.last_message_update_time[channel.id]['admin_overview'] = datetime.now(timezone.utc)

                logger.info(f"Successfully sent Admin Overview to control channel {channel.name}")
            except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                logger.error(f"Error sending Admin Overview to channel: {e}", exc_info=True)

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in _send_control_panel_and_statuses: {e}", exc_info=True)

    async def _send_all_server_statuses(self, channel: discord.TextChannel):
        """Sends only the overview embed to a status channel (no individual server messages)."""
        try:
            config = load_config()
            if not config:
                logger.error(f"Send All Statuses: Could not load configuration for channel {channel.id}.")
                return

            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            if not servers:
                logger.warning(f"No servers configured to send status in channel {channel.name}")
                return

            logger.info(f"Sending overview embed to status channel {channel.name} ({channel.id})")

            # CACHE WARMUP: Populate cache BEFORE creating overview embed
            # This prevents showing 🔄 loading icons during channel regeneration
            logger.debug("Starting cache population for overview embed (blocking to ensure data availability)")

            # Ensure semaphore exists
            if not hasattr(self, '_status_update_semaphore'):
                self._status_update_semaphore = asyncio.Semaphore(1)

            # Wait for cache to be populated before creating embed
            await self._background_cache_population()
            logger.info("Cache population complete for overview embed - proceeding with embed creation")

            # Send ONLY the overview embed (status channels don't need individual server messages)
            try:
                # Sort servers by the 'order' field from container configurations
                ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

                channel_id = channel.id
                embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)

                # The overview's buttons: Mech, info, admin, help
                from .control_ui import MechView
                view = MechView(self, channel_id)

                # Send with animation and button if available
                if animation_file:
                    logger.info(f"✅ Sending overview message with animation and Mech buttons to {channel.name}")
                    message = await self._send_message_with_files(channel, embed, animation_file, view)
                else:
                    logger.warning(f"⚠️ Sending overview message WITHOUT animation to {channel.name}")
                    message = await self._send_message_with_files(channel, embed, None, view)

                # Track ONLY the overview message for status channels
                # Clear any existing server message tracking (status channels only have overview)
                if channel.id not in self.channel_server_message_ids:
                    self.channel_server_message_ids[channel.id] = {}
                else:
                    # Clear all previous tracking except for overview
                    self.channel_server_message_ids[channel.id].clear()

                self.channel_server_message_ids[channel.id]["overview"] = message.id
                self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate

                # Initialize update time tracking for overview only
                if channel.id not in self.last_message_update_time:
                    self.last_message_update_time[channel.id] = {}
                else:
                    # Clear all previous time tracking except for overview
                    self.last_message_update_time[channel.id].clear()

                self.last_message_update_time[channel.id]["overview"] = datetime.now(timezone.utc)

                logger.info(f"✅ Successfully sent overview embed to status channel {channel.name}")

            except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                logger.error(f"Error sending overview embed to {channel.name}: {e}", exc_info=True)

            # NOTE: Individual server status messages removed for status channels
            # Status channels only show the overview embed with all servers

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in _send_all_server_statuses: {e}", exc_info=True)

    async def _regenerate_channel(self, channel: discord.TextChannel, mode: str, config: dict):
        """FIX B: Serialize regeneration per-channel so it can't race another poster
        (inactivity loop, event recreate, /ss, /control, recovery) into a duplicate overview.

        This is the single lock owner for the delete+post sequence; callers (inactivity
        loop, control_command) must NOT already hold the channel lock.
        """
        async with self._get_channel_lock(channel.id):
            await self._regenerate_channel_impl(channel, mode, config)

    async def _regenerate_channel_impl(self, channel: discord.TextChannel, mode: str, config: dict):
        """Deletes all bot messages and posts a fresh control panel and status messages."""
        if not config:
            logger.error(f"Regenerate Channel: Could not load configuration. Aborting.")
            raise ValueError("Configuration not available for channel regeneration")

        if mode not in ['control', 'status']:
            logger.error(f"Invalid regeneration mode '{mode}' for channel {channel.name}. Must be 'control' or 'status'.")
            raise ValueError(f"Invalid regeneration mode: {mode}")

        logger.info(f"Regenerating channel {channel.name} ({channel.id}) in mode '{mode}'")

        # --- Delete old messages ---
        try:
            logger.info(f"Deleting old bot messages in {channel.name}...")
            # Delete our long-lived overview by ID first - the age-limited cleanup below
            # can silently skip it once it is older than 30 days (-> duplicate overview).
            await self._delete_tracked_overview_messages(channel)
            await self.delete_bot_messages(channel, limit=300) # Limit adjustable
            await asyncio.sleep(1.0) # Short pause after deleting
            logger.info(f"Finished deleting messages in {channel.name}.")
        except (discord.errors.HTTPException, discord.errors.NotFound) as e_delete:
            logger.error(f"Error deleting messages in {channel.name}: {e_delete}", exc_info=True)
            # Continue even if deletion fails - regeneration might still work

        # --- Send new messages based on mode ---
        try:
            if mode == 'control':
                logger.debug(f"Sending control panel and statuses to {channel.name}")
                await self._send_control_panel_and_statuses(channel)
            elif mode == 'status':
                logger.debug(f"Sending status-only messages to {channel.name}")
                await self._send_all_server_statuses(channel)

            logger.info(f"✅ Regeneration for channel {channel.name} completed successfully.")

        except (discord.errors.HTTPException, discord.errors.Forbidden) as e_send:
            logger.error(f"❌ Error sending new messages to {channel.name} in mode '{mode}': {e_send}", exc_info=True)
            raise RuntimeError(f"Failed to send new messages during regeneration: {e_send}") from e_send

    async def send_initial_status(self):
        """Sends the initial status messages after a short delay."""
        logger.info("Starting send_initial_status")
        initial_send_successful = False
        try:
            await self.bot.wait_until_ready() # Ensure bot is ready before fetching channels

            # CACHE WARMUP: Populate cache BEFORE sending initial messages
            # This prevents showing 🔄 loading icons on first display
            logger.info("Starting cache population (blocking to ensure data availability)")

            # Ensure semaphore exists
            if not hasattr(self, '_status_update_semaphore'):
                self._status_update_semaphore = asyncio.Semaphore(1)

            # Wait for cache to be populated before sending messages
            await self._background_cache_population()

            logger.info("Cache population complete - proceeding with status send")

            logger.info("Proceeding with initial status send")

            # Force reload to ensure we get fresh config (not stale cache from bootstrap)
            from services.config.config_service import get_config_service
            current_config = get_config_service().get_config(force_reload=True)
            if not current_config:
                logger.error("Could not load configuration for initial status send.")
                return

            # Get channel permissions from config
            channel_permissions = current_config.get('channel_permissions', {})
            logger.info(f"Found {len(channel_permissions)} channels in config")

            # Process each channel
            for channel_id_str, channel_config in channel_permissions.items():
                try:
                    # Convert channel ID to int
                    if not channel_id_str.isdigit():
                        logger.warning(f"Invalid channel ID: {channel_id_str}")
                        continue
                    channel_id = int(channel_id_str)

                    # Check if initial posting is enabled
                    if not channel_config.get('post_initial', False):
                        logger.debug(f"Channel {channel_id}: post_initial is disabled")
                        continue

                    # Get channel permissions
                    channel_commands = channel_config.get('commands', {})
                    has_control = channel_commands.get('control', False)
                    has_status = channel_commands.get('serverstatus', False)

                    logger.info(f"Channel {channel_id}: post_initial=True, control={has_control}, status={has_status}")

                    # Determine mode
                    mode = None
                    if has_control:
                        mode = 'control'
                    elif has_status:
                        mode = 'status'
                    else:
                        logger.warning(f"Channel {channel_id} has neither control nor status permissions")
                        continue

                    # Get channel
                    try:
                        channel = await self.bot.fetch_channel(channel_id)
                        if not isinstance(channel, discord.TextChannel):
                            logger.warning(f"Channel {channel_id} is not a text channel")
                            continue

                        logger.info(f"Regenerating channel {channel.name} ({channel_id}) in {mode} mode")

                        # FIX B: serialize delete+send against any concurrent poster (e.g. a
                        # user firing /ss right at startup) so we never post a duplicate overview.
                        async with self._get_channel_lock(channel.id):
                            # Delete old messages
                            try:
                                # Remove our long-lived overview by ID first (age-limited cleanup
                                # can skip a >30-day-old in-place-edited overview -> duplicate).
                                await self._delete_tracked_overview_messages(channel)
                                await self.delete_bot_messages(channel)
                                await asyncio.sleep(1)  # Short pause after deletion
                            except (discord.errors.DiscordException, RuntimeError) as e:
                                logger.error(f"Error deleting messages in {channel.name}: {e}", exc_info=True)

                            # Clear any leftover individual server message tracking from old architecture
                            if channel.id in self.channel_server_message_ids:
                                old_entries = list(self.channel_server_message_ids[channel.id].keys())
                                for entry_key in old_entries:
                                    if entry_key not in ["overview", "admin_overview"]:
                                        logger.info(f"Clearing leftover individual server entry '{entry_key}' from channel {channel.id}")
                                        del self.channel_server_message_ids[channel.id][entry_key]

                            # Send new messages using consistent logic with _regenerate_channel
                            if mode == 'control':
                                await self._send_control_panel_and_statuses(channel)
                            elif mode == 'status':
                                # Use the same method as _regenerate_channel to ensure consistency
                                await self._send_all_server_statuses(channel)

                        # Set initial channel activity time so inactivity tracking works
                        self.last_channel_activity[channel.id] = datetime.now(timezone.utc)
                        logger.info(f"Set initial channel activity time for {channel.name} ({channel.id})")

                        logger.info(f"Successfully regenerated channel {channel.name}")
                        initial_send_successful = True
                    except discord.NotFound:
                        logger.warning(f"Channel {channel_id} not found")
                    except discord.Forbidden:
                        logger.warning(f"Missing permissions for channel {channel_id}")
                    except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                        logger.error(f"Error processing channel {channel_id}: {e}", exc_info=True)

                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error processing channel config {channel_id_str}: {e}", exc_info=True)

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Critical error during send_initial_status: {e}", exc_info=True)
        finally:
            self.initial_messages_sent = True
            logger.info(f"send_initial_status finished. Initial messages sent flag set to True. Success: {initial_send_successful}")

    async def delete_bot_messages(self, channel: discord.TextChannel, limit: int = 200):
        """Delete bot messages while preserving Live Log messages using ChannelCleanupService."""
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"Attempted to delete messages in non-text channel: {channel}")
            return

        try:
            result = await self.cleanup_service.delete_bot_messages_preserve_live_logs(
                channel=channel,
                reason="initial status cleanup",
                message_limit=limit
            )

            if result.success:
                logger.info(f"✅ CLEANUP SUCCESS: Deleted {result.messages_deleted} bot messages in {channel.name} "
                           f"via {result.method_used} (Preserved: {result.messages_preserved} Live Logs) "
                           f"in {result.execution_time_ms:.1f}ms")
            else:
                logger.warning(f"⚠️ CLEANUP PARTIAL: Deleted {result.messages_deleted} messages in {channel.name} "
                              f"(error: {result.error})")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"❌ CLEANUP FAILED for channel {channel.name}: {e}", exc_info=True)

    def _overview_buried_by_stray(self, channel_id: int, last_msg_id: int) -> bool:
        """FIX A predicate: should the inactivity loop move our overview to the bottom?

        Called only when the channel's LAST message is bot-authored. Returns True when a
        STRAY bot message (e.g. a restart/update notification) has buried our managed
        overview, i.e. the last message is NOT one of our tracked overview/admin-overview
        IDs. Returns False when:
          - there is no tracking yet (e.g. right after a restart, before messages are
            re-posted) -> keep the old, safe behavior and never regenerate on a bot
            message (avoids deleting an intact overview / a regenerate storm), or
          - the last message IS our managed overview (already at the bottom).
        Foreign (non-bot) messages are handled by the caller and always regenerate.
        """
        tracked = self.channel_server_message_ids.get(channel_id, {})
        managed_ids = set(tracked.values())
        managed_ids.discard(None)
        if not managed_ids:
            return False
        return last_msg_id not in managed_ids

    async def _delete_tracked_overview_messages(self, channel: discord.TextChannel) -> None:
        """Delete the bot's own tracked overview / admin_overview messages by ID.

        Individual delete-by-ID has neither the 14-day bulk-delete limit nor the
        30-day age cutoff that the generic cleanup (delete_bot_messages) applies.
        An overview that is edited in place keeps its original created_at, so after
        ~30 days the age-limited cleanup silently skips it and a fresh overview gets
        posted on top of the stale one -> duplicate message. Removing the tracked
        message by its known ID first prevents that.
        """
        # Messages an earlier round could not delete. Keeping their id in the
        # tracking map was meant to retry them, but the caller's next step posts
        # the replacement and overwrites it - so the old overview stayed in the
        # channel, untracked, and after 30 days the age-limited cleanup skips it
        # too. They are remembered here and tried again.
        pending = self.__dict__.setdefault('_undeleted_messages', {})
        still_there = set()
        for message_id in pending.get(channel.id, set()):
            try:
                await channel.get_partial_message(message_id).delete()
                logger.info(f"Removed stranded message {message_id} in channel {channel.id}")
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"Stranded message {message_id} in channel {channel.id} stays: {e}")
                still_there.add(message_id)
        if still_there:
            pending[channel.id] = still_there
        else:
            pending.pop(channel.id, None)

        tracked = self.channel_server_message_ids.get(channel.id)
        if not tracked:
            return
        for key in ('overview', 'admin_overview'):
            message_id = tracked.get(key)
            if not message_id:
                continue
            try:
                await channel.get_partial_message(message_id).delete()
                logger.info(f"Removed tracked '{key}' message {message_id} in channel {channel.id} before re-posting")
                tracked.pop(key, None)
            except discord.NotFound:
                tracked.pop(key, None)  # Already gone - drop the stale id
            except (discord.Forbidden, discord.HTTPException) as e:
                # Transient/permission error: remember the id OUTSIDE the tracking
                # map, which the caller is about to overwrite with the new message.
                logger.warning(f"Could not delete tracked '{key}' message {message_id} in channel {channel.id}: {e}")
                pending.setdefault(channel.id, set()).add(message_id)
                tracked.pop(key, None)
        # Keep the persisted map in sync so we don't try to delete the same id next restart.
        self._persist_tracked_message_ids()
