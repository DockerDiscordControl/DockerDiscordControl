# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import discord
from discord.ext import commands, tasks
import asyncio
import functools
from datetime import datetime, timedelta, timezone
import os
import logging
import time
from typing import Dict, Any
from io import BytesIO

# Import app_commands using central utility
from utils.app_commands_helper import get_app_commands, get_discord_option
app_commands = get_app_commands()
DiscordOption = get_discord_option()

# Discord services
from services.discord.channel_cleanup_service import get_channel_cleanup_service

# Import our utility functions
from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
# SERVICE FIRST: docker_action moved to docker_action_service.py

from utils.time_utils import format_datetime_with_timezone
from utils.logging_utils import setup_logger
from services.docker_service.server_order import load_server_order, save_server_order
from services.docker_service.status_cache_runtime import get_docker_status_cache_runtime

# Import scheduler module
# Scheduler imports removed - unused in this module

# Import outsourced parts
from .translation_manager import _
from .control_helpers import get_guild_id, container_select, _channel_has_permission
# control_ui imports removed - unused in this module

# Import the autocomplete handlers that have been moved to their own module
# Note: Task-related autocomplete handlers removed as commands are now UI-based

# Schedule commands mixin removed - task scheduling now handled through UI

# Import the status handlers mixin that contains status-related functionality
from .status_handlers import StatusHandlersMixin
from .overview_embeds import OverviewEmbedsMixin
from .slash_commands import SlashCommandsMixin
from .ddc_ui import DDCModal, DDCView

# Import the command handlers mixin that contains Docker action command functionality
# Command handlers removed - using UI buttons for all container control

# Import central logging function
# log_user_action import removed - unused in this module

# Configure logger for the cog using utility (INFO for release)
logger = setup_logger('ddc.docker_control', level=logging.INFO)

# DonationView will be defined in this file

# CRITICAL DEBUG: Log at module load time to verify new code is being executed
logger.info("=" * 80)
logger.info("[MODULE LOAD DEBUG] docker_control.py module is being loaded - NEW CODE VERSION e214386")
logger.info("=" * 80)

# Overview edits treat status cache entries older than this as stale, independent of
# DDC_DOCKER_CACHE_DURATION (up to 300 s), so a container stopped outside DDC doesn't stay 🟢
# for minutes. A stale cache still triggers only ONE shared bulk refresh (_ensure_status_cache_fresh).
STATUS_CACHE_MAX_RENDER_AGE_SECONDS = 60


def _status_entry_age_seconds(entry) -> float:
    """Age of a status cache entry in seconds (0 if it has no usable timestamp)."""
    timestamp = entry.get('timestamp')
    if hasattr(timestamp, 'timestamp'):
        return time.time() - timestamp.timestamp()
    return 0.0


def _heartbeat_enabled(config: dict) -> bool:
    """True if the heartbeat is switched on AND has a ping URL.

    The URL is read with "or ''": a config that holds null instead of an empty
    string (an older version, a hand edit) used to raise AttributeError on
    .strip(), which the caller's except (OSError, KeyError, ValueError) does not
    catch - the rest of the startup, including the first status message, was
    skipped without a word (review B11).
    """
    heartbeat = config.get('heartbeat', {})
    if not isinstance(heartbeat, dict) or not heartbeat.get('enabled', False):
        return False
    return bool((heartbeat.get('ping_url') or '').strip())


# --------------------------------------------------------------------------- #
# Background loops: one bad cycle must not be the last one (review E17)
# --------------------------------------------------------------------------- #
#
# Measured in the shipped py-cord (ext/tasks/__init__.py):
#
#   line 103  _valid_exception = (OSError, GatewayNotFound, ConnectionClosed,
#                                 aiohttp.ClientError, asyncio.TimeoutError)
#   line 171  only those are retried;
#   line 195  ANYTHING else sets _has_failed, calls the loop's error handler and
#             re-raises - the loop is over, permanently, until DDC restarts;
#   line 474  the DEFAULT error handler is a bare print() to sys.stderr.
#
# So a single ValueError or DDC exception used to end the status display for the
# rest of the run, and DDC's own log never mentioned it. The operator sees stale
# numbers and has nothing to look at. That is the worst shape a defect can have.
#
# Two answers, because they cover different failures. The decorator keeps a bad
# CYCLE from being fatal; the error handler makes a loop that dies anyway say so
# through DDC's logger instead of py-cord's print.

def survives_one_bad_cycle(coro):
    """Let a loop body fail a cycle without ending the loop.

    The cycle is lost and said so at ERROR. The loop runs again at its next
    interval, which is what "periodic" is supposed to mean.

    CancelledError travels on untouched: it means DDC is shutting down, not
    that the cycle failed. It descends from BaseException, so `except Exception`
    would not have caught it anyway - the clause is a signpost, and becomes
    load-bearing the moment somebody widens the handler.
    """
    @functools.wraps(coro)
    async def wrapper(*args, **kwargs):
        try:
            return await coro(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - see above
            logger.error("Background loop '%s' lost a cycle (%s: %s) - it will "
                         "run again at the next interval",
                         coro.__name__, type(e).__name__, e, exc_info=True)
            return None
    return wrapper


def _register_loop_error_handlers(cls) -> None:
    """Give every tasks.Loop on a class an error handler that uses the logger."""
    for attribute_name in dir(cls):
        candidate = getattr(cls, attribute_name, None)
        if not isinstance(candidate, tasks.Loop):
            continue

        def make_handler(loop_name):
            async def handler(*args):
                exception = args[-1]
                logger.error(
                    "BACKGROUND LOOP STOPPED: '%s' ended with %s: %s. It will "
                    "NOT run again until DDC is restarted - whatever it does is "
                    "no longer happening.",
                    loop_name, type(exception).__name__, exception,
                    exc_info=exception)
            handler.__name__ = f"on_{loop_name}_stopped"
            return handler

        candidate.error(make_handler(attribute_name))


class DockerControlCog(commands.Cog, StatusHandlersMixin, OverviewEmbedsMixin, SlashCommandsMixin):
    """Cog for DockerDiscordControl container management via Discord."""

    def __init__(self, bot: commands.Bot, config: dict):
        """Initializes the DockerDiscordControl Cog."""
        logger.info("Initializing DockerControlCog... [DDC-SETUP]")

        # Basic initialization
        self.bot = bot
        self._initial_config = config  # Only for startup, use self.config property for live access
        self._config_service = None  # Lazy-loaded ConfigService reference

        # Check if donations are disabled and remove donation commands
        try:
            from services.donation.donation_utils import is_donations_disabled
            if is_donations_disabled():
                logger.info("Donations are disabled - removing donation commands")
                # Remove donate and donatebroadcast commands after cog is initialized
                self.donations_disabled = True
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug(f"Error checking donation status: {e}")
            self.donations_disabled = False

        # Initialize Mech State Manager for persistence
        from services.mech.mech_state_manager import get_mech_state_manager
        self.mech_state_manager = get_mech_state_manager()

        # Member count updates moved to on-demand (during donations with level-ups)

        # Load persisted states
        logger.debug("Step 1: Loading mech state...")
        try:
            state_data = self.mech_state_manager.load_state()
            logger.debug("Step 1a: Mech state loaded successfully")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 1 FAILED: {e}", exc_info=True)
            raise

        # Safe int conversion with error handling
        self.mech_expanded_states = {}
        for k, v in state_data.get("mech_expanded_states", {}).items():
            try:
                self.mech_expanded_states[int(k)] = v
            except (ValueError, TypeError):
                logger.warning(f"Invalid channel ID in mech_expanded_states: {k}")

        self.last_glvl_per_channel = {}
        for k, v in state_data.get("last_glvl_per_channel", {}).items():
            try:
                self.last_glvl_per_channel[int(k)] = v
            except (ValueError, TypeError):
                logger.warning(f"Invalid channel ID in last_glvl_per_channel: {k}")
        logger.info(f"Loaded persisted Mech states: {len(self.mech_expanded_states)} expanded, {len(self.last_glvl_per_channel)} Glvl tracked")

        self.expanded_states = {}  # For container expand/collapse

        # FIX C: Restore persisted overview/admin_overview message ids. This lets the bot
        # delete a long-lived (possibly >30-day-old) overview by ID after a restart before
        # re-posting, preventing a duplicate that the age-limited cleanup would otherwise miss.
        self.channel_server_message_ids: Dict[int, Dict[str, int]] = {}
        for cid_str, msgs in state_data.get("channel_overview_message_ids", {}).items():
            if not isinstance(msgs, dict):
                continue
            try:
                cid = int(cid_str)
                restored = {k: int(v) for k, v in msgs.items()
                            if k in ('overview', 'admin_overview') and v}
                if restored:
                    self.channel_server_message_ids[cid] = restored
            except (ValueError, TypeError):
                logger.warning(f"Invalid persisted overview id entry for channel {cid_str}")
        if self.channel_server_message_ids:
            logger.info(f"Restored persisted overview message ids for {len(self.channel_server_message_ids)} channel(s)")
        self.last_message_update_time: Dict[int, Dict[str, datetime]] = {}
        self.initial_messages_sent = False
        self.last_channel_activity: Dict[int, datetime] = {}

        # Cache configuration - SERVICE FIRST: Use StatusCacheService
        # Initialize StatusCacheService instead of local cache
        logger.debug("Step 2: Initializing StatusCacheService...")
        try:
            from services.status.status_cache_service import get_status_cache_service
            self.status_cache_service = get_status_cache_service()
            logger.debug("Step 2 complete: StatusCacheService initialized for DockerControlCog")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 2 FAILED: {e}", exc_info=True)
            raise

        # Share the cache snapshot through the dedicated runtime helper so other
        # components can inspect the data without importing the cog directly.
        logger.debug("Step 3: Getting docker status cache runtime...")
        try:
            self._status_cache_runtime = get_docker_status_cache_runtime()
            logger.debug("Step 3 complete: Docker status cache runtime initialized")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 3 FAILED: {e}", exc_info=True)
            raise

        # Keep cache_ttl_seconds for compatibility (some code might still reference it)
        from utils.settings import get_setting
        cache_duration = get_setting('DDC_DOCKER_CACHE_DURATION', 30)
        self.cache_ttl_seconds = int(cache_duration * 2.5)
        # The refresh interval itself. The status embeds decide from it when a status is old
        # enough to deserve an age hint. Recovering it by dividing cache_ttl_seconds by 2.5
        # would be an invisible coupling between two files, so it is published explicitly.
        self.status_refresh_interval_seconds = cache_duration

        self.pending_actions: Dict[str, Dict[str, Any]] = {}

        # Status cache refresh bookkeeping (see _ensure_status_cache_fresh)
        self._last_status_cache_refresh = 0.0
        self._status_fetch_failed = set()

        # Initialize services
        logger.debug("Step 4: Initializing cleanup service...")
        try:
            self.cleanup_service = get_channel_cleanup_service(bot)
            logger.debug("Step 4 complete: Cleanup service initialized")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 4 FAILED: {e}", exc_info=True)
            raise

        # Initialize Mech Status Cache Service
        logger.debug("Step 5: Initializing MechStatusCacheService...")
        try:
            from services.mech.mech_status_cache_service import get_mech_status_cache_service
            self.mech_status_cache_service = get_mech_status_cache_service()
            logger.debug("Step 5 complete: MechStatusCacheService initialized")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 5 FAILED: {e}", exc_info=True)
            raise

        # Setup event listeners for Discord updates
        logger.debug("Step 6: Setting up Discord event listeners...")
        try:
            self._setup_discord_event_listeners()
            logger.debug("Step 6 complete: Discord event listeners setup")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 6 FAILED: {e}", exc_info=True)
            raise

        # Docker query cooldown tracking
        self.last_docker_query = {}  # Track last query time per container
        self.docker_query_cooldown = get_setting('DDC_DOCKER_QUERY_COOLDOWN', 2)

        # Load server order
        logger.debug("Step 7: Loading server order...")
        try:
            self.ordered_server_names = load_server_order()
            logger.debug(f"Step 7a: Loaded server order from persistent file: {self.ordered_server_names}")
            if not self.ordered_server_names:
                if 'server_order' in config:
                    logger.debug("Step 7b: Using server_order from config")
                    self.ordered_server_names = config.get('server_order', [])
                else:
                    logger.debug("Step 7c: No server_order found, using all server names from config")
                    # SERVICE FIRST: Use ServerConfigService instead of direct config access
                    server_config_service = get_server_config_service()
                    servers = server_config_service.get_all_servers()
                    self.ordered_server_names = [s.get('docker_name') for s in servers if s.get('docker_name')]
                save_server_order(self.ordered_server_names)
                logger.debug(f"Step 7d: Saved default server order: {self.ordered_server_names}")
            logger.debug("Step 7 complete: Server order loaded")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 7 FAILED: {e}", exc_info=True)
            raise

        # Register persistent views for mech buttons
        logger.debug("Step 8: Registering persistent mech views...")
        try:
            self._register_persistent_mech_views()
            logger.debug("Step 8 complete: Persistent mech views registered")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 8 FAILED: {e}", exc_info=True)
            raise

        # Initialize task tracking
        logger.debug("Step 9: Initializing asyncio locks...")
        try:
            self._active_tasks = set()
            self._task_lock = asyncio.Lock()

            # Initialize interaction lock to prevent race conditions between button clicks and auto-updates
            self._interaction_lock = asyncio.Lock()
            self._active_interactions = set()  # Track active button interactions per channel

            # FIX B: Per-channel locks serialize every path that deletes+posts an overview
            # (regenerate, recreate, recovery, /ss, /control, initial send) so two concurrent
            # paths can never post a duplicate overview into the same channel.
            self._channel_locks: Dict[int, asyncio.Lock] = {}
            logger.debug("Step 9 complete: Asyncio locks initialized")
        except Exception as e:
            logger.error(f"[DEBUG INIT] Step 9 FAILED: {e}", exc_info=True)
            raise

        # NOTE: Background loops are started in cog_load() hook, not in __init__
        # This is because __init__ runs before bot.loop is available
        logger.info("DockerControlCog __init__ phase 1 complete. Background loops will start in cog_load().")

        # PERFORMANCE OPTIMIZATION: Initialize embed cache for StatusHandlersMixin
        self._embed_cache = {
            'translated_terms': {},
            'box_elements': {},
            'last_cache_clear': datetime.now(timezone.utc)
        }

        logger.info("Ensuring other potential loops (if any residues from old structure) are cancelled.")
        if hasattr(self, 'heartbeat_send_loop') and self.heartbeat_send_loop.is_running(): self.heartbeat_send_loop.cancel()
        if hasattr(self, 'status_update_loop') and self.status_update_loop.is_running(): self.status_update_loop.cancel()
        if hasattr(self, 'inactivity_check_loop') and self.inactivity_check_loop.is_running(): self.inactivity_check_loop.cancel()

        # Track if background loops have been started (to avoid double-start on reconnect)
        self._background_loops_started = False

    @property
    def config(self) -> dict:
        """
        Live configuration property - always returns fresh config from ConfigService.

        This enables hot-reload of configuration without container restart.
        Changes to channel_permissions, servers, admin_users etc. take effect immediately.
        """
        try:
            if self._config_service is None:
                from services.config.config_service import get_config_service
                self._config_service = get_config_service()
            return self._config_service.get_config()
        except Exception as e:
            # Fallback to initial config if ConfigService fails
            logger.warning(f"ConfigService unavailable, using initial config: {e}")
            return self._initial_config

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Called when the bot is ready. This is the correct place to start background loops in PyCord.

        NOTE: PyCord 2.x does NOT support cog_load() hook (only discord.py 2.0+).
        on_ready() is called after bot connects and event loop is available.
        """
        # Only start loops once (on_ready can be called multiple times on reconnect)
        if self._background_loops_started:
            logger.info("[on_ready] Background loops already started, skipping")
            return

        logger.info("=== on_ready() called - Starting background loops ===")

        # Ensure clean loop state
        logger.info("Ensuring clean loop state...")
        self._cancel_existing_loops()

        # Initialize background loops with proper error handling
        logger.info("Setting up background loops...")
        self._setup_background_loops()

        self._background_loops_started = True
        logger.info("=== on_ready() complete - Background loops started ===")

    def _setup_discord_event_listeners(self):
        """Set up event listeners for Discord status message updates."""
        try:
            from services.infrastructure.event_manager import get_event_manager
            event_manager = get_event_manager()

            # Register listener for Discord update events from cache service
            event_manager.register_listener('discord_update_needed', self._handle_discord_update_event)
            event_manager.register_listener('channel_config_changed', self._handle_channel_config_changed)

            logger.info("Discord update event listeners registered (status + channel hot-reload)")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to setup Discord event listeners: {e}", exc_info=True)

    def _handle_discord_update_event(self, event_data):
        """Handle discord_update_needed events for automatic status message refresh."""
        try:
            # Extract relevant data from event
            event_info = event_data.data
            reason = event_info.get('reason', 'unknown')
            trigger_source = event_info.get('trigger_source', 'unknown')

            logger.info(f"Discord update event received: reason={reason}, source={trigger_source}")

            # Schedule async updates using the bot's event loop
            if self.bot and hasattr(self.bot, 'loop'):
                # Update /ss messages (overview messages are updated automatically via event)
                # NOTE: _auto_update_ss_messages already handles overview message updates
                # No need to call _update_all_overview_messages_after_donation separately
                asyncio.run_coroutine_threadsafe(
                    self._auto_update_ss_messages(f"Event: {reason}", force_recreate=True),
                    self.bot.loop
                )

                logger.info(f"Discord status message updates scheduled for: {reason}")
            else:
                logger.warning("Cannot schedule Discord updates: bot loop not available")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error handling Discord update event: {e}", exc_info=True)

    # --- Channel Hot-Reload ---

    def _handle_channel_config_changed(self, event_data):
        """Handle channel_config_changed events from Web UI save (hot-reload)."""
        try:
            logger.info("Channel config changed event received — scheduling hot-reload")
            if self.bot and hasattr(self.bot, 'loop'):
                asyncio.run_coroutine_threadsafe(
                    self._apply_channel_config_changes(),
                    self.bot.loop
                )
            else:
                logger.warning("Cannot schedule channel hot-reload: bot loop not available")
        except Exception as e:
            logger.error(f"Error handling channel config change: {e}", exc_info=True)

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

                if not added and not removed:
                    logger.info("Channel hot-reload: no channels added or removed")
                    return

                logger.info(f"Channel hot-reload: {len(added)} added, {len(removed)} removed")

                # Teardown removed channels
                for channel_id in removed:
                    await self._teardown_channel(channel_id)

                # Setup added channels (with rate limit pause between each)
                for channel_id in added:
                    channel_config = new_channel_permissions.get(str(channel_id), {})
                    await self._setup_channel(channel_id, channel_config)
                    if len(added) > 1:
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
            self._channel_locks.pop(channel_id, None)  # FIX B: drop the per-channel lock
            self.last_message_update_time.pop(channel_id, None)
            self.last_channel_activity.pop(channel_id, None)
            if hasattr(self, 'mech_expanded_states'):
                self.mech_expanded_states.pop(channel_id, None)
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
                    await self._send_all_server_statuses(channel, allow_toggle=False, force_collapse=True)

            # Start tracking
            self.last_channel_activity[channel_id] = datetime.now(timezone.utc)
            logger.info(f"Channel {channel.name} ({channel_id}) set up successfully in {mode} mode")

        except discord.NotFound:
            logger.warning(f"Channel {channel_id} not found on Discord")
        except discord.Forbidden:
            logger.warning(f"Missing permissions for channel {channel_id}")
        except Exception as e:
            logger.error(f"Error setting up channel {channel_id}: {e}", exc_info=True)

    def _cancel_existing_loops(self):
        """Cancel any existing background loops."""
        loops_to_check = [
            'heartbeat_send_loop',
            'status_update_loop',
            'periodic_message_edit_loop',
            'inactivity_check_loop',
            'performance_cache_clear_loop'
        ]

        for loop_name in loops_to_check:
            if hasattr(self, loop_name):
                loop = getattr(self, loop_name)
                if loop.is_running():
                    logger.info(f"Cancelling existing {loop_name}")
                    loop.cancel()

    async def _track_task(self, task: asyncio.Task):
        """Track an active task and remove it when done."""
        async with self._task_lock:
            self._active_tasks.add(task)
        try:
            await task
        except asyncio.CancelledError:
            pass
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Task error: {e}", exc_info=True)
        finally:
            async with self._task_lock:
                self._active_tasks.discard(task)

    async def _start_interaction(self, channel_id: int) -> bool:
        """Mark the start of a button interaction for a channel.

        Returns:
            bool: True if interaction started successfully, False if already active
        """
        async with self._interaction_lock:
            if channel_id in self._active_interactions:
                logger.debug(f"Interaction already active for channel {channel_id}")
                return False
            self._active_interactions.add(channel_id)
            logger.debug(f"Started interaction for channel {channel_id}")
            return True

    async def _end_interaction(self, channel_id: int):
        """Mark the end of a button interaction for a channel."""
        async with self._interaction_lock:
            self._active_interactions.discard(channel_id)
            logger.debug(f"Ended interaction for channel {channel_id}")

    async def _is_channel_interacting(self, channel_id: int) -> bool:
        """Check if a channel currently has an active button interaction."""
        async with self._interaction_lock:
            return channel_id in self._active_interactions

    def _setup_background_loops(self):
        """Initialize and start all background loops with proper tracking."""
        try:
            # Start status update loop (30 seconds interval)
            status_task = self.bot.loop.create_task(
                self._start_loop_safely(self.status_update_loop, "Status Update Loop")
            )
            self.bot.loop.create_task(self._track_task(status_task))

            # Start periodic message edit loop (1 minute interval)
            logger.info("Scheduling controlled start of periodic_message_edit_loop...")
            edit_task = self.bot.loop.create_task(
                self._start_periodic_message_edit_loop_safely()
            )
            self.bot.loop.create_task(self._track_task(edit_task))

            # Start inactivity check loop (1 minute interval)
            inactivity_task = self.bot.loop.create_task(
                self._start_loop_safely(self.inactivity_check_loop, "Inactivity Check Loop")
            )
            self.bot.loop.create_task(self._track_task(inactivity_task))

            # Start cache clear loop (5 minute interval)
            cache_task = self.bot.loop.create_task(
                self._start_loop_safely(self.performance_cache_clear_loop, "Performance Cache Clear Loop")
            )
            self.bot.loop.create_task(self._track_task(cache_task))

            # Member count updates moved to on-demand (during level-ups only)

            # Start Status Watchdog loop if enabled
            try:
                heartbeat_enabled = _heartbeat_enabled(load_config() or {})
            except (OSError, KeyError, ValueError):
                heartbeat_enabled = False

            if heartbeat_enabled:
                heartbeat_task = self.bot.loop.create_task(
                    self._start_loop_safely(self.heartbeat_send_loop, "Heartbeat Loop")
                )
                self.bot.loop.create_task(self._track_task(heartbeat_task))

            # Schedule initial status send with simple delay
            logger.info("Scheduling initial status send...")

            async def send_initial_after_delay():
                try:
                    await self.bot.wait_until_ready()
                    logger.info("Bot ready - waiting 10 seconds before initial status send")
                    await asyncio.sleep(10)
                    logger.info("Starting initial status send")
                    await self.send_initial_status()
                    logger.info("Initial status send completed")
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error in initial status send: {e}", exc_info=True)

            # Tracked like its siblings: this one sleeps ten seconds and then posts
            # the overview messages, and it used to be the only task the cog did not
            # know about while it ran (review B39).
            initial_task = self.bot.loop.create_task(send_initial_after_delay())
            self.bot.loop.create_task(self._track_task(initial_task))

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error setting up background loops: {e}", exc_info=True)
            raise

        # Initialize global status cache
        self.update_global_status_cache()

        logger.info("Background loops setup complete. Initial status send scheduled.")

    # --- PERIODIC MESSAGE EDIT LOOP (FULL LOGIC, MOVED DIRECTLY INTO COG) ---
    @tasks.loop(minutes=1, reconnect=True)
    @survives_one_bad_cycle
    async def periodic_message_edit_loop(self):
        """Periodically checks and edits messages in channels that require updates."""
        config = load_config()
        if not config:
            logger.error("Periodic Edit Loop: Could not load configuration. Skipping cycle.")
            return

        logger.info("--- DIRECT COG periodic_message_edit_loop cycle --- Starting Check --- ")
        if not self.initial_messages_sent:
             logger.debug("Direct Cog Periodic edit loop: Initial messages not sent yet, skipping.")
             return

        logger.info(f"Direct Cog Periodic Edit Loop: Checking {len(self.channel_server_message_ids)} channels with tracked messages.")

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
            logger.info(f"Direct Cog Periodic Edit Loop: Processing channel {channel_id} (Refresh: {enable_refresh}, Interval: {update_interval_minutes}m). It has {len(server_messages_in_channel)} tracked messages.")

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
            logger.info(f"Direct Cog Periodic Edit Loop: Attempting to run {len(tasks_to_run)} message edit tasks.")

            # Refresh the status cache at most once per cycle (only if stale) BEFORE the batches,
            # so the per-message updates render from cache and actually run in parallel.
            await self._ensure_status_cache_fresh()

            # ULTRA-PERFORMANCE: Batched parallelization for message edits
            start_batch_time = datetime.now(timezone.utc)
            total_tasks = len(tasks_to_run)
            success_count = 0
            not_found_count = 0
            error_count = 0
            none_results_count = 0

            try:
                # IMPROVED: Intelligent batch distribution based on historical performance
                BATCH_SIZE = 3  # Process 3 messages at a time instead of all at once

                # Known slow containers that should be distributed across batches
                KNOWN_SLOW_CONTAINERS = {'Satisfactory', 'V-Rising', 'Valheim', 'ProjectZomboid'}

                # Separate tasks into fast and slow
                slow_tasks = []
                fast_tasks = []

                for task in tasks_to_run:
                    # Extract container name from task (assuming it's the second argument)
                    if hasattr(task, '_coro') and hasattr(task._coro, 'cr_frame'):
                        # Try to extract display_name from coroutine arguments
                        try:
                            frame_locals = task._coro.cr_frame.f_locals
                            display_name = frame_locals.get('display_name', '')
                            if display_name in KNOWN_SLOW_CONTAINERS:
                                slow_tasks.append(task)
                            else:
                                fast_tasks.append(task)
                        except (AttributeError, ValueError, KeyError) as frame_error:
                            # Default to fast if we can't determine container type from frame inspection
                            logger.debug(f"Failed to extract container name from task frame, defaulting to fast batch: {frame_error}")
                            fast_tasks.append(task)
                    else:
                        fast_tasks.append(task)  # Default to fast if we can't determine

                # Create balanced batches: distribute slow containers evenly
                balanced_batches = []
                batch_count = (total_tasks + BATCH_SIZE - 1) // BATCH_SIZE

                # Distribute slow tasks first (one per batch if possible)
                slow_distribution = [[] for _ in range(batch_count)]
                for i, slow_task in enumerate(slow_tasks):
                    batch_index = i % batch_count
                    slow_distribution[batch_index].append(slow_task)

                # Fill remaining slots with fast tasks
                fast_task_index = 0
                for batch_index in range(batch_count):
                    current_batch = slow_distribution[batch_index][:]

                    # Fill up to BATCH_SIZE with fast tasks
                    while len(current_batch) < BATCH_SIZE and fast_task_index < len(fast_tasks):
                        current_batch.append(fast_tasks[fast_task_index])
                        fast_task_index += 1

                    if current_batch:  # Only add non-empty batches
                        balanced_batches.append(current_batch)

                logger.info(f"Direct Cog Periodic Edit Loop: Running {total_tasks} message edits in INTELLIGENT BATCHED mode (batch size: {BATCH_SIZE}, slow containers distributed)")
                logger.info(f"Performance optimization: {len(slow_tasks)} slow containers distributed across {len(balanced_batches)} batches")

                # Process balanced batches
                for batch_num, batch_tasks in enumerate(balanced_batches, 1):
                    total_batches = len(balanced_batches)

                    logger.info(f"Direct Cog Periodic Edit Loop: Processing batch {batch_num}/{total_batches} with {len(batch_tasks)} tasks")

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

                # Performance analysis
                batch_time = (datetime.now(timezone.utc) - start_batch_time).total_seconds() * 1000

                if batch_time < 1000:  # Under 1 second - excellent
                    logger.info(f"Direct Cog Periodic Edit Loop: ULTRA-FAST batched processing completed in {batch_time:.1f}ms")
                elif batch_time < 3000:  # Under 3 seconds - good
                    logger.info(f"Direct Cog Periodic Edit Loop: FAST batched processing completed in {batch_time:.1f}ms")
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
            logger.info(f"Direct Cog Periodic Edit Loop: Average time per message edit: {avg_time_per_edit:.1f}ms")
        else:
            logger.info("Direct Cog Periodic message update check: No messages were due for update in any channel.")

    # Wrapper for editing, needs to be part of this Cog now if periodic_message_edit_loop uses it.
    async def _edit_single_message_wrapper(self, channel_id: int, display_name: str, message_id: int, current_config: dict, allow_toggle: bool):
        """
        Handles message editing and updates timestamps.

        Args:
            channel_id: Discord channel ID
            display_name: Display name of the server
            message_id: Discord message ID to edit
            current_config: Current configuration
            allow_toggle: Whether to allow toggle button

        Returns:
            bool: Success or failure
        """
        # This is a method of DockerControlCog that handles message editing
        result = await self._edit_single_message(channel_id, display_name, message_id, current_config)

        if result is True:
            # CRITICAL FIX: Since channel_server_message_ids now uses docker_name as keys,
            # the display_name parameter might actually be docker_name. Use it directly for consistency.
            # This works because the wrapper is called with the same identifier used in channel_server_message_ids
            now_utc = datetime.now(timezone.utc)
            if channel_id not in self.last_message_update_time:
                self.last_message_update_time[channel_id] = {}
            # Use display_name directly (it's actually docker_name from the keys)
            self.last_message_update_time[channel_id][display_name] = now_utc
            logger.debug(f"Updated last_message_update_time for '{display_name}' in {channel_id} to {now_utc}")

            # DO NOT update channel activity for periodic updates
            # This is intentional - we only want to update activity for new messages,
            # not for periodic refreshes, so the Recreate feature can work properly
            # by detecting when the last message is from a user, not the bot

            # The following code is commented out to fix the Recreate feature
            # Channel activity is only updated in on_message and when a new message is sent
            """
            channel_permissions = current_config.get('channel_permissions', {})
            channel_config_specific = channel_permissions.get(str(channel_id))
            default_recreate_enabled = True
            default_timeout_minutes = 10
            recreate_enabled = default_recreate_enabled
            timeout_minutes = default_timeout_minutes
            if channel_config_specific:
                recreate_enabled = channel_config_specific.get('recreate_messages_on_inactivity', default_recreate_enabled)
                timeout_minutes = channel_config_specific.get('inactivity_timeout_minutes', default_timeout_minutes)
            if recreate_enabled and timeout_minutes > 0:
                 self.last_channel_activity[channel_id] = now_utc
                 logger.debug(f"[_EDIT_WRAPPER in COG] Updated last_channel_activity for channel {channel_id} to {now_utc} due to successful bot edit.")
            """
        return result

    # Helper function for editing a single message, needs to be part of this Cog or accessible (e.g. from StatusHandlersMixin)
    # Assuming _edit_single_message is available via StatusHandlersMixin or also moved.
    # For clarity, if _edit_single_message was also in TaskLoopsMixin, it needs to be moved here too.
    # If it's in StatusHandlersMixin, self._edit_single_message will work if StatusHandlersMixin is inherited.
    # Based on current inheritance, StatusHandlersMixin IS inherited, so self._edit_single_message should be fine.

    async def _start_loop_safely(self, loop_task, loop_name: str):
        """Generic helper to start a task loop safely."""
        try:
            await self.bot.wait_until_ready()
            if not loop_task.is_running():
                loop_task.start()
                logger.info(f"{loop_name} started successfully via _start_loop_safely.")
            else:
                logger.info(f"{loop_name} was already running when _start_loop_safely was called (or restarted). Attempting to ensure it is running.")
                if not loop_task.is_running():
                    loop_task.start()
                    logger.info(f"{loop_name} re-started successfully via _start_loop_safely after check.")
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error starting {loop_name} via _start_loop_safely: {e}", exc_info=True)

    async def _start_periodic_message_edit_loop_safely(self):
        await self._start_loop_safely(self.periodic_message_edit_loop, "Periodic Message Edit Loop (Direct Cog)")

    async def trigger_status_refresh(self, container_name: str, delay_seconds: int = 5):
        """
        Trigger a status refresh for a specific container after an action.
        Called by AAS (Auto-Action System) after automated container actions.

        Args:
            container_name: Docker container name
            delay_seconds: Delay before refresh (default 5s for container to stabilize)
        """
        async def _delayed_refresh():
            try:
                logger.info(f"[AAS_REFRESH] Waiting {delay_seconds}s before refreshing status for {container_name}")
                await asyncio.sleep(delay_seconds)

                # Invalidate caches
                if self.status_cache_service.get(container_name):
                    self.status_cache_service.remove(container_name)
                    logger.info(f"[AAS_REFRESH] Invalidated StatusCacheService for {container_name}")

                from services.infrastructure.container_status_service import get_container_status_service
                container_status_service = get_container_status_service()
                container_status_service.invalidate_container(container_name)
                logger.info(f"[AAS_REFRESH] Invalidated ContainerStatusService for {container_name}")

                # Find the server config for this container. config['servers'] is a list, so look it
                # up via ServerConfigService (same source as the overview builders).
                config = load_config()
                server_config = get_server_config_service().get_server_by_docker_name(container_name)
                display_name = server_config.get('display_name', container_name) if server_config else None

                if not display_name:
                    logger.warning(f"[AAS_REFRESH] Container {container_name} not found in config")
                    return

                # Get fresh status
                if server_config:
                    fresh_status = await self.get_status(server_config)
                    if fresh_status.success:
                        self.status_cache_service.set(container_name, fresh_status, datetime.now(timezone.utc))

                # Update tracked status messages (Server Overview individual containers)
                if hasattr(self, 'tracked_status_messages'):
                    for channel_id, messages in self.tracked_status_messages.items():
                        for msg_data in messages:
                            if msg_data.get('display_name') == display_name:
                                try:
                                    channel = self.bot.get_channel(channel_id)
                                    if channel:
                                        message = await channel.fetch_message(msg_data['message_id'])
                                        if message:
                                            embed, view, _ = await self._generate_status_embed_and_view(
                                                channel_id, display_name, server_config, config,
                                                allow_toggle=True, force_collapse=False, show_cache_age=False
                                            )
                                            if embed:
                                                await message.edit(embed=embed, view=view)
                                                logger.info(f"[AAS_REFRESH] Updated status message for {display_name}")
                                except Exception as e:
                                    logger.error(f"[AAS_REFRESH] Failed to update status message: {e}")

                # Update overview messages (Server Overview collapsed view)
                if hasattr(self, 'channel_server_message_ids'):
                    for channel_id, server_messages in self.channel_server_message_ids.items():
                        if 'overview' in server_messages:
                            try:
                                await self._update_overview_message(channel_id, server_messages['overview'], 'overview')
                                logger.info(f"[AAS_REFRESH] Updated overview in channel {channel_id}")
                            except Exception as e:
                                logger.error(f"[AAS_REFRESH] Failed to update overview: {e}")

                        # Also update admin_overview if exists
                        if 'admin_overview' in server_messages:
                            try:
                                await self._update_overview_message(channel_id, server_messages['admin_overview'], 'admin_overview')
                                logger.info(f"[AAS_REFRESH] Updated admin_overview in channel {channel_id}")
                            except Exception as e:
                                logger.error(f"[AAS_REFRESH] Failed to update admin_overview: {e}")

                logger.info(f"[AAS_REFRESH] Status refresh complete for {container_name}")

            except Exception as e:
                logger.error(f"[AAS_REFRESH] Error refreshing status for {container_name}: {e}", exc_info=True)

        # Run as background task
        task = asyncio.create_task(_delayed_refresh())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _clean_sweep_bot_messages(self, channel, reason: str):
        """Clean sweep: Delete all bot messages in channel using ChannelCleanupService."""
        try:
            result = await self.cleanup_service.clean_sweep_bot_messages(
                channel=channel,
                reason=reason,
                message_limit=100
            )

            if result.success:
                logger.info(f"✅ CLEAN SWEEP SUCCESS: Cleaned {result.messages_deleted}/{result.messages_found} "
                           f"bot messages from channel {channel.id} in {result.execution_time_ms:.1f}ms")
            else:
                logger.warning(f"⚠️ CLEAN SWEEP PARTIAL: Cleaned {result.messages_deleted}/{result.messages_found} "
                              f"messages from channel {channel.id} (error: {result.error})")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"❌ CLEAN SWEEP FAILED for channel {channel.id}: {e}", exc_info=True)
            # Don't raise - clean sweep failure shouldn't stop recovery

    # send_initial_status_after_delay_and_ready() stood here: a second copy of the
    # wait -> sleep -> send_initial_status() sequence, written for a caller in
    # __init__ that no longer exists and called by nothing, tests included. The one
    # that runs is the closure in _setup_background_loops(), which is reached only
    # past _cancel_existing_loops() and the _background_loops_started guard; the copy
    # was a way around both, and a second initial send posts overview messages whose
    # ids the cog does not track (review B16).

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listens to messages to update channel activity for inactivity tracking."""
        if message.author.bot:  # Ignore bot messages for triggering activity
            return
        if not message.guild:  # Ignore DMs
            return

        channel_id = message.channel.id
        channel_permissions = self.config.get('channel_permissions', {})
        # Use direct default values since DEFAULT_CONFIG was removed
        default_perms_inactivity = True
        default_perms_timeout = 10

        channel_config = channel_permissions.get(str(channel_id))

        if channel_config:  # Only if this channel has specific permissions defined
            recreate_enabled = channel_config.get('recreate_messages_on_inactivity', default_perms_inactivity)
            timeout_minutes = channel_config.get('inactivity_timeout_minutes', default_perms_timeout)

            if recreate_enabled and timeout_minutes > 0:
                now_utc = datetime.now(timezone.utc)
                logger.debug(f"[on_message] Updating last_channel_activity for channel {channel_id} to {now_utc} due to user message.")
                self.last_channel_activity[channel_id] = now_utc

    # --- STATUS HANDLERS MOVED TO status_handlers.py ---
    # All status-related functionality has been moved to the StatusHandlersMixin class in status_handlers.py
    # This includes the following methods:
    # - get_status
    # - _generate_status_embed_and_view
    # - send_server_status

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
            logger.info("Starting cache population for admin overview (blocking to ensure data availability)")

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

    async def _send_all_server_statuses(self, channel: discord.TextChannel, allow_toggle: bool = True, force_collapse: bool = False):
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
            logger.info("Starting cache population for overview embed (blocking to ensure data availability)")

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

                # Set collapsed state (force_collapse overrides)
                channel_id = channel.id
                if force_collapse:
                    self.mech_expanded_states[channel_id] = False
                    self.mech_state_manager.set_expanded_state(channel_id, False)

                embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)

                # Create MechView with expand/collapse buttons for mech status
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
                await self._send_all_server_statuses(channel, allow_toggle=False, force_collapse=True)

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
                                await self._send_all_server_statuses(channel, allow_toggle=False, force_collapse=True)

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

    async def _background_cache_population(self, skip_if_refreshed_since: float = None):
        """Perform background cache population without blocking initial status send.

        Args:
            skip_if_refreshed_since: time.monotonic() value; if another caller (or the
                status_update_loop) completed a refresh after it, skip the fetch. Lets
                concurrent callers waiting on the semaphore share one bulk fetch.
        """
        try:
            logger.info("Starting background cache population")

            # Load configuration
            config = load_config()
            if not config:
                logger.error("Background cache population: Could not load configuration.")
                return

            # Get container names from servers
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            if not servers:
                logger.info("Background cache population: No servers configured")
                return

            container_names = [s.get('docker_name') for s in servers if s.get('docker_name')]
            if not container_names:
                logger.info("Background cache population: No containers found")
                return

            logger.info(f"Background cache population: Processing {len(container_names)} containers")
            start_time = time.time()

            # Ensure semaphore exists (tests / early callers may run before any loop created it)
            if not hasattr(self, '_status_update_semaphore'):
                self._status_update_semaphore = asyncio.Semaphore(1)

            # Use semaphore for race condition protection (same as status_update_loop)
            async with self._status_update_semaphore:
                if (skip_if_refreshed_since is not None
                        and getattr(self, '_last_status_cache_refresh', 0.0) >= skip_if_refreshed_since):
                    logger.debug("Background cache population: cache was refreshed while waiting - skipping fetch")
                    return

                # Bulk fetch container status (same logic as status_update_loop)
                results = await self.bulk_fetch_container_status(container_names)

                success_count = 0
                error_count = 0
                failed_names = set()

                # Update cache with results (same logic as status_update_loop)
                for name, result in results.items():
                    if result.success:
                        # Cache ContainerStatusResult directly
                        self.status_cache_service.set(name, result, datetime.now(timezone.utc))
                        success_count += 1
                    else:
                        logger.warning(f"Background cache population: Failed to fetch status for {name}. Error: {result.error_message}")
                        error_count += 1
                        failed_names.add(name)

                # A container missing from the results (its fetch raised) counts as failed too,
                # so its aging cache entry doesn't force a bulk refresh per overview edit
                failed_names.update(n for n in container_names if n not in results)
                self._mark_status_cache_refreshed(failed_names)
                duration_ms = (time.time() - start_time) * 1000
                logger.info(f"Background cache population completed: {success_count} success, {error_count} errors in {duration_ms:.1f}ms")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error during background cache population: {e}", exc_info=True)

    def _mark_status_cache_refreshed(self, failed_names=None):
        """Record a completed bulk status refresh (called while holding _status_update_semaphore)."""
        self._last_status_cache_refresh = time.monotonic()
        # Containers whose fetch failed are never cached - remember them so they don't make the
        # cache look permanently stale (which would trigger a full bulk fetch per overview edit).
        self._status_fetch_failed = set(failed_names or ())

    async def _ensure_status_cache_fresh(self):
        """Refresh the status cache only if it is stale.

        status_update_loop refreshes every DDC_DOCKER_CACHE_DURATION seconds and
        ContainerStatusService drops entries older than that, so the cache is stale
        when a configured container that did not fail its last fetch has no entry
        (expired, or invalidated after a container action) or an entry older than
        STATUS_CACHE_MAX_RENDER_AGE_SECONDS (long cache durations must not keep a
        container stopped outside DDC green for minutes). Overview renders use the
        cache as-is otherwise instead of doing a full Docker bulk fetch per message.
        """
        requested_at = time.monotonic()
        try:
            servers = get_server_config_service().get_all_servers()
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning(f"Status cache freshness check failed, refreshing: {e}")
            servers = None

        if servers is not None:
            failed = getattr(self, '_status_fetch_failed', set())
            stale = []
            for server in servers:
                docker_name = server.get('docker_name')
                if not docker_name or docker_name in failed:
                    continue
                entry = self.status_cache_service.get(docker_name)
                if not entry or _status_entry_age_seconds(entry) > STATUS_CACHE_MAX_RENDER_AGE_SECONDS:
                    stale.append(docker_name)
            if not stale:
                logger.debug("Status cache is fresh - rendering from cache")
                return
            logger.debug(f"Status cache stale for {len(stale)} container(s) - refreshing")

        await self._background_cache_population(skip_if_refreshed_since=requested_at)

    # _update_single_message WAS REMOVED
    # _update_single_server_message_by_name WAS REMOVED

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

    def _get_channel_lock(self, channel_id: int) -> asyncio.Lock:
        """FIX B: Return the per-channel asyncio.Lock, creating it lazily.

        Created on first use, which always happens inside an `async with` on the bot's
        event loop, so the Lock binds to the correct loop. asyncio.Lock is NOT reentrant:
        a method holding this lock must never call another method that also acquires it
        for the same channel (see lock-owner convention in _regenerate_channel et al.).
        """
        lock = self._channel_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._channel_locks[channel_id] = lock
        return lock

    def _persist_tracked_message_ids(self) -> None:
        """Persist overview/admin_overview message ids to mech_state.json (best-effort).

        Only the single managed overview id per channel is stored; per-server/per-docker
        ids are intentionally excluded. This enables _delete_tracked_overview_messages to
        remove a stale, long-lived overview by ID after a restart so a fresh overview is
        not posted on top of it (-> duplicate). Called from every site that POSTS a new
        overview, so the persisted id always reflects the latest message.
        """
        try:
            snapshot = {}
            for cid, msgs in self.channel_server_message_ids.items():
                kept = {k: v for k, v in msgs.items()
                        if k in ('overview', 'admin_overview') and v}
                if kept:
                    snapshot[str(cid)] = kept
            self.mech_state_manager.set_state("channel_overview_message_ids", snapshot)
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            logger.warning(f"Could not persist overview message ids: {e}")

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
                # Transient/permission error: KEEP the id so a later regenerate retries the
                # by-id delete instead of permanently stranding a >30-day-old overview.
                logger.warning(f"Could not delete tracked '{key}' message {message_id} in channel {channel.id}: {e}")
        # Keep the persisted map in sync so we don't try to delete the same id next restart.
        self._persist_tracked_message_ids()


    # Legacy command methods removed - all container control and info editing
    # is now handled through Discord UI buttons for better user experience

    # /info_edit command removed - info editing now handled through UI buttons


    # _handle_donate_interaction lived here twice: this first version was dead,
    # Python keeps the last definition (review B13). The live one is below. They
    # were NOT the same: this one asked is_donations_disabled(), the live one
    # treats any value in donation_disable_key as 'donations off' - noted for the
    # operator, behaviour unchanged.



    # NOTE: Old _create_overview_embed method was removed
    # Use _create_overview_embed_expanded or _create_overview_embed_collapsed instead



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
            for channel_id, messages in self.channel_server_message_ids.items():
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

                        # Skip update if channel has active button interaction
                        if await self._is_channel_interacting(channel_id):
                            logger.debug(f"Skipping auto-update for channel {channel_id} - active interaction")
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
                                current_glvl = 0
                                current_Power = 0.0
                        except (KeyError, ValueError, AttributeError) as e:
                            logger.debug(f"Could not get current Glvl: {e}")
                            # BUGFIX: Set fallback values if cache fails
                            current_glvl = 0
                            current_Power = 0.0

                        # Check if Glvl changed significantly (>= 1 level difference) or power reached 0
                        glvl_changed = False
                        power_depleted = False

                        if current_glvl is not None:
                            last_glvl = self.last_glvl_per_channel.get(channel_id, 0)

                            # Special check: if power reached exactly 0, always force update
                            if current_Power <= 0 and last_glvl > 0:
                                power_depleted = True
                                from .translation_manager import _
                                logger.info(_("Mech power depleted - forcing animation update to show offline state"))
                            if abs(current_glvl - last_glvl) >= 1:
                                glvl_changed = True
                                from .translation_manager import _
                                glvl_change_text = _("Significant Glvl change detected")
                                logger.info(f"{glvl_change_text}: {last_glvl} → {current_glvl}")
                                self.last_glvl_per_channel[channel_id] = current_glvl
                                self.mech_state_manager.set_last_glvl(channel_id, current_glvl)
                            elif last_glvl == 0:  # First time tracking
                                self.last_glvl_per_channel[channel_id] = current_glvl
                                self.mech_state_manager.set_last_glvl(channel_id, current_glvl)

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

                        # Create updated embed based on expansion state
                        is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
                        logger.info(f"AUTO-UPDATE: Channel {channel_id} is_expanded={is_mech_expanded}, force_recreate={recreate_this_channel}")
                        if is_mech_expanded:
                            logger.info(f"AUTO-UPDATE: Creating expanded embed for channel {channel_id}")
                            embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
                        else:
                            logger.info(f"AUTO-UPDATE: Creating collapsed embed for channel {channel_id}")
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

    # --- Status Watchdog (Heartbeat) Loop ---
    @tasks.loop(minutes=5)
    async def heartbeat_send_loop(self):
        """
        Status Watchdog: Pings an external monitoring URL periodically.

        This implements a "Dead Man's Switch" pattern - if DDC stops running,
        the monitoring service (e.g., Healthchecks.io, Uptime Kuma) will detect
        the missing ping and send an alert.

        Security: Only outbound HTTPS requests, no tokens or data shared.
        """
        try:
            import aiohttp

            # Load heartbeat configuration
            current_config = load_config() or self.config or {}
            heartbeat_config = current_config.get('heartbeat', {})

            if not isinstance(heartbeat_config, dict):
                return

            # Check if enabled
            if not heartbeat_config.get('enabled', False):
                return

            # Get ping URL
            ping_url = heartbeat_config.get('ping_url', '').strip()
            if not ping_url:
                return

            # Security: Only allow HTTPS
            if not ping_url.startswith('https://'):
                logger.warning("[Watchdog] Monitoring URL must use HTTPS - skipping ping")
                return

            # Get interval and update loop if needed
            try:
                interval_minutes = int(heartbeat_config.get('interval', 5))
                interval_minutes = max(1, min(60, interval_minutes))  # Clamp 1-60
            except (ValueError, TypeError):
                interval_minutes = 5

            if self.heartbeat_send_loop.minutes != interval_minutes:
                try:
                    self.heartbeat_send_loop.change_interval(minutes=interval_minutes)
                    logger.info(f"[Watchdog] Interval updated to {interval_minutes} minutes")
                except Exception as e:
                    logger.warning(f"[Watchdog] Failed to update interval: {e}")

            # Ping the monitoring URL
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            logger.debug(f"[Watchdog] Ping successful")
                        else:
                            logger.warning(f"[Watchdog] Ping returned status {resp.status}")
            except aiohttp.ClientError as e:
                logger.warning(f"[Watchdog] Ping failed: {e}")
            except Exception as e:
                logger.error(f"[Watchdog] Unexpected error during ping: {e}")

        except Exception as e:
            logger.error(f"[Watchdog] Error in heartbeat loop: {e}", exc_info=True)

    @heartbeat_send_loop.before_loop
    async def before_heartbeat_loop(self):
        """Wait until the bot is ready before starting the watchdog loop."""
        await self.bot.wait_until_ready()
        logger.info("[Watchdog] Status monitoring loop ready")

    # --- Status Cache Update Loop ---
    @tasks.loop(seconds=30)
    @survives_one_bad_cycle
    async def status_update_loop(self):
        """Periodically updates the cache with the latest container statuses."""
        # Load configuration first
        config = load_config()
        if not config:
            logger.error("Status Update Loop: Could not load configuration. Skipping cycle.")
            return

        # Get cache duration from environment
        from utils.settings import get_setting
        cache_duration = get_setting('DDC_DOCKER_CACHE_DURATION', 30)

        # Update cache TTL based on current interval
        calculated_ttl = int(cache_duration * 2.5)
        if self.cache_ttl_seconds != calculated_ttl:
            self.cache_ttl_seconds = calculated_ttl
            logger.info(f"[STATUS_LOOP] Cache TTL updated to {calculated_ttl} seconds (interval: {cache_duration}s)")
        # Keep the published interval in sync when the setting changes at runtime.
        self.status_refresh_interval_seconds = cache_duration

        # Dynamically change the loop interval if needed
        if self.status_update_loop.seconds != cache_duration:
            try:
                self.status_update_loop.change_interval(seconds=cache_duration)
                logger.info(f"[STATUS_LOOP] Cache update interval changed to {cache_duration} seconds")
            except (discord.errors.DiscordException, RuntimeError, OSError, KeyError) as e:
                logger.error(f"[STATUS_LOOP] Failed to change interval: {e}", exc_info=True)

        # Configuration already loaded and validated above
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()
        if not servers:
            return # No servers to update

        container_names = [s.get('docker_name') for s in servers if s.get('docker_name')]

        logger.info(f"[STATUS_LOOP] Bulk updating cache for {len(container_names)} containers")
        start_time = time.time()

        try:
            # RACE CONDITION PROTECTION: Use semaphore to prevent concurrent status updates
            if not hasattr(self, '_status_update_semaphore'):
                self._status_update_semaphore = asyncio.Semaphore(1)

            async with self._status_update_semaphore:
                # Bulk fetch returns ContainerStatusResult objects
                results = await self.bulk_fetch_container_status(container_names)

                success_count = 0
                error_count = 0
                failed_names = set()

                # Process ContainerStatusResult objects
                for name, result in results.items():
                    if result.success:
                        # Cache ContainerStatusResult directly
                        self.status_cache_service.set(name, result, datetime.now(timezone.utc))
                        success_count += 1
                    else:
                        logger.warning(f"[STATUS_LOOP] Failed to fetch status for {name}. Error: {result.error_message}")
                        error_count += 1
                        failed_names.add(name)

                # Missing from the results (fetch raised) = failed, see _background_cache_population
                failed_names.update(n for n in container_names if n not in results)
                self._mark_status_cache_refreshed(failed_names)
                duration_ms = (time.time() - start_time) * 1000
                logger.info(f"[STATUS_LOOP] Cache updated: {success_count} success, {error_count} errors in {duration_ms:.1f}ms")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"[STATUS_LOOP] Unexpected error during status update loop: {e}", exc_info=True)

    @status_update_loop.before_loop
    async def before_status_update_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    # --- Mech Status Cache Startup ---
    @tasks.loop(count=1)  # Only run once to start the background loop
    async def start_mech_cache_loop(self):
        """Start the MechStatusCacheService background loop."""
        try:
            logger.info("Starting MechStatusCacheService background loop...")
            await self.mech_status_cache_service.start_background_loop()
            logger.info("MechStatusCacheService background loop started successfully")
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to start MechStatusCacheService background loop: {e}", exc_info=True)

    @start_mech_cache_loop.before_loop
    async def before_start_mech_cache_loop(self):
        """Wait until the bot is ready before starting the mech cache."""
        await self.bot.wait_until_ready()

    # --- Initial Animation Cache Warmup (NON-BLOCKING OPTIMIZATION) ---
    @tasks.loop(count=1)  # Only run once to perform initial cache warmup
    async def initial_animation_cache_warmup(self):
        """Perform initial animation cache warmup in background after startup completes."""
        try:
            # PERFORMANCE OPTIMIZATION: Let startup complete first, then cache in background
            logger.info("Scheduling animation cache warmup in background (startup optimization)")

            # Wait for bot to be fully ready and operational
            await self.bot.wait_until_ready()

            # Additional delay to ensure Discord channels are loaded and bot is responsive
            await asyncio.sleep(15)  # Let all startup processes complete first

            logger.info("Starting background animation cache warmup...")

            from services.mech.animation_cache_service import get_animation_cache_service
            animation_cache = get_animation_cache_service()

            # Run cache warmup with parallel optimization
            await self._perform_optimized_cache_warmup(animation_cache)

            logger.info("Background animation cache warmup completed successfully")
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to perform background animation cache warmup: {e}", exc_info=True)

    async def _perform_optimized_cache_warmup(self, animation_cache):
        """Perform cache warmup with parallel processing for better performance."""
        try:
            # Get current mech status for cache warmup
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
            from services.mech.speed_levels import get_combined_mech_status

            cache_service = get_mech_status_cache_service()
            cache_request = MechStatusCacheRequest(include_decimals=True)
            mech_result = cache_service.get_cached_status(cache_request)

            if not mech_result.success:
                logger.warning("Could not get mech status for optimized warmup - using fallback")
                # Use fallback: cache current level animation
                await animation_cache.perform_initial_cache_warmup()
                return

            current_level = mech_result.level
            current_power = mech_result.power

            # Calculate current speed level
            if current_level >= 11:
                current_speed_level = 100  # Level 11 always has maximum speed
            else:
                # Real level + its power bar maximum (not a level guessed from the power amount)
                speed_status = get_combined_mech_status(
                    current_power, evolution_level=current_level,
                    power_max=getattr(getattr(mech_result, 'bars', None), 'Power_max_for_level', None))
                current_speed_level = speed_status['speed']['level']

            logger.info(f"Optimized cache warmup: Level {current_level}, Power {current_power:.2f}, Speed {current_speed_level}")

            # PARALLEL OPTIMIZATION: Generate small and big animations simultaneously
            small_task = asyncio.create_task(
                self._cache_small_animation_async(animation_cache, current_level, current_speed_level, current_power)
            )
            big_task = asyncio.create_task(
                self._cache_big_animation_async(animation_cache, current_level, current_speed_level, current_power)
            )

            # Wait for both to complete in parallel (much faster than serial)
            await asyncio.gather(small_task, big_task, return_exceptions=True)

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in optimized cache warmup: {e}", exc_info=True)
            # Fallback to original implementation
            await animation_cache.perform_initial_cache_warmup()

    async def _cache_small_animation_async(self, animation_cache, level, speed_level, power):
        """Cache small animation asynchronously."""
        try:
            logger.debug(f"Parallel caching: Small animation Level {level}, Speed {speed_level}")
            # Run in thread pool to avoid blocking the event loop
            await asyncio.to_thread(
                animation_cache.get_animation_with_speed_and_power, level, speed_level, power
            )
            logger.debug(f"Completed: Small animation Level {level}")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to cache small animation: {e}")

    async def _cache_big_animation_async(self, animation_cache, level, speed_level, power):
        """Cache big animation asynchronously."""
        try:
            logger.debug(f"Parallel caching: Big animation Level {level}, Speed {speed_level}")
            # Run in thread pool to avoid blocking the event loop
            await asyncio.to_thread(
                animation_cache.get_animation_with_speed_and_power_big, level, speed_level, power
            )
            logger.debug(f"Completed: Big animation Level {level}")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to cache big animation: {e}")

    @initial_animation_cache_warmup.before_loop
    async def before_initial_animation_cache_warmup(self):
        """Minimal delay before starting background cache warmup."""
        # No additional wait needed - the loop itself handles timing
        pass

    # --- Inactivity Check Loop ---
    @tasks.loop(seconds=30)
    @survives_one_bad_cycle
    async def inactivity_check_loop(self):
        """Checks for channel inactivity and regenerates messages if needed."""
        config = load_config()
        if not config:
            logger.error("Inactivity Check Loop: Could not load configuration. Skipping cycle.")
            return

        now_utc = datetime.now(timezone.utc)
        channel_permissions = config.get('channel_permissions', {})

        try:
            if not self.initial_messages_sent:
                logger.info("Inactivity check loop: Initial messages not sent yet, skipping.")
                return

            logger.info("Inactivity check loop running")

            # Log tracked channels for debugging
            logger.info(f"Currently tracking {len(self.last_channel_activity)} channels for activity: {list(self.last_channel_activity.keys())}")

            # Check each channel we've previously registered activity for
            for channel_id, last_activity_time in list(self.last_channel_activity.items()):
                channel_config = channel_permissions.get(str(channel_id))

                logger.debug(f"Checking channel {channel_id}")

                # Skip channels with no config
                if not channel_config:
                    logger.debug(f"Channel {channel_id} has no specific config, skipping")
                    continue

                recreate_enabled = channel_config.get('recreate_messages_on_inactivity', True)
                timeout_minutes = channel_config.get('inactivity_timeout_minutes', 10)

                logger.debug(f"Channel {channel_id} - recreate_enabled={recreate_enabled}, timeout_minutes={timeout_minutes}")

                if not recreate_enabled or timeout_minutes <= 0:
                    logger.debug(f"Channel {channel_id} - Recreate disabled or timeout <= 0, skipping")
                    continue

                # Calculate time since last activity
                time_since_last_activity = now_utc - last_activity_time
                inactivity_threshold = timedelta(minutes=timeout_minutes)

                logger.debug(f"Channel {channel_id} - Time since last activity: {time_since_last_activity}, threshold: {inactivity_threshold}")

                # Check if we've passed the inactivity threshold
                if time_since_last_activity >= inactivity_threshold:
                    logger.info(f"Channel {channel_id} has been inactive for {time_since_last_activity}, attempting regeneration")

                    try:
                        # Fetch the Discord channel
                        channel = await self.bot.fetch_channel(channel_id)

                        if not isinstance(channel, discord.TextChannel):
                            logger.warning(f"Channel {channel_id} is not a text channel, removing from activity tracking")
                            del self.last_channel_activity[channel_id]
                            continue

                        logger.debug(f"Successfully fetched channel {channel.name} ({channel_id})")

                        # Check the last message to confirm inactivity
                        history = await channel.history(limit=3).flatten()

                        logger.debug(f"Found {len(history)} messages in recent history for channel {channel.name}")

                        # If there are no messages at all, regenerate
                        if not history:
                            logger.info(f"No messages found in channel {channel.name} ({channel_id}). Regenerating")
                            # Determine the mode: control or status
                            has_control_permission = _channel_has_permission(channel_id, 'control', config)
                            regeneration_mode = 'control' if has_control_permission else 'status'
                            logger.debug(f"Regeneration mode for empty channel: {regeneration_mode}")
                            await self._regenerate_channel(channel, regeneration_mode, config)
                            self.last_channel_activity[channel_id] = now_utc
                            continue

                        # Check if the last message is from our bot
                        # Safety check: ensure bot.user is available
                        if self.bot.user is None:
                            logger.warning(f"Bot user is None, cannot check message author. Skipping channel {channel_id}")
                            continue

                        last_msg = history[0]
                        bot_user_id = self.bot.user.id

                        # Log detailed info for debugging recreation issues
                        logger.debug(f"Channel {channel.name}: Last message author={last_msg.author.id} ({last_msg.author.name}), bot_id={bot_user_id}")

                        # Check if last message is from our bot (by user ID or application ID)
                        bot_app_id = getattr(self.bot, 'application_id', None)
                        is_from_bot = (last_msg.author.id == bot_user_id or
                                      (hasattr(last_msg, 'application_id') and bot_app_id and last_msg.application_id == bot_app_id))

                        if is_from_bot:
                            # FIX A: Distinguish our OWN managed overview/admin-overview (already at
                            # the bottom -> nothing to do) from a STRAY bot message such as a
                            # restart/update notification that has buried our overview.
                            if not self._overview_buried_by_stray(channel_id, last_msg.id):
                                self.last_channel_activity[channel_id] = now_utc
                                logger.debug(f"Last message in channel {channel.name} ({channel_id}) is our managed overview (or no tracking) - resetting inactivity timer, no regeneration")
                                continue

                            # Our overview is buried under a stray bot message -> move it to the bottom
                            logger.info(f"Channel {channel.name} ({channel_id}): own overview buried under stray bot message {last_msg.id} - will regenerate to move it to the bottom")
                        else:
                            # The last message is from a user (foreign), regenerate as before
                            logger.info(f"Last message in channel {channel.name} is NOT from our bot (author_id={last_msg.author.id}, bot_id={bot_user_id}). Will regenerate")

                        # Determine the mode: control or status
                        has_control_permission = _channel_has_permission(channel_id, 'control', config)
                        has_status_permission = _channel_has_permission(channel_id, 'serverstatus', config)

                        logger.debug(f"Channel permissions - control: {has_control_permission}, status: {has_status_permission}")

                        regeneration_mode = 'control' if has_control_permission else 'status'

                        # Force the mode to be valid
                        if not has_control_permission and not has_status_permission:
                            logger.warning(f"Channel {channel.name} has neither control nor status permissions. Cannot regenerate")
                            continue

                        logger.debug(f"Will regenerate with mode: {regeneration_mode}")

                        # FIX A: Don't regenerate while a user is mid-interaction (e.g. expanding the
                        # mech) - deleting the message they are interacting with would no-op their
                        # click. Skip this cycle; the loop retries in 30s.
                        if await self._is_channel_interacting(channel_id):
                            logger.debug(f"Channel {channel_id} has an active interaction - deferring regeneration to next cycle")
                            continue

                        # Attempt channel regeneration with improved error handling
                        try:
                            logger.info(f"Starting inactivity regeneration for {channel.name} ({channel_id}) in mode '{regeneration_mode}'")
                            await self._regenerate_channel(channel, regeneration_mode, config)

                            # Reset activity timer only on successful regeneration
                            self.last_channel_activity[channel_id] = now_utc
                            logger.info(f"✅ Channel {channel.name} ({channel_id}) successfully regenerated due to inactivity. Mode: {regeneration_mode}")

                        except (discord.errors.DiscordException, RuntimeError, OSError) as regen_error:
                            logger.error(f"❌ Failed to regenerate channel {channel.name} ({channel_id}) due to inactivity: {regen_error}", exc_info=True)
                            # Don't reset activity timer on failure - try again next cycle
                            # But prevent infinite retries by adding a small delay
                            error_delay = timedelta(minutes=2)
                            self.last_channel_activity[channel_id] = now_utc - inactivity_threshold + error_delay
                            logger.warning(f"Delaying next regeneration attempt for {channel.name} by {error_delay}")

                    except discord.NotFound:
                        logger.warning(f"Channel {channel_id} not found. Removing from activity tracking")
                        del self.last_channel_activity[channel_id]
                    except discord.Forbidden:
                        logger.error(f"Cannot access channel {channel_id} (forbidden). Continuing tracking but regeneration not possible")
                    except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                        logger.error(f"Error during inactivity check for channel {channel_id}: {e}", exc_info=True)
                else:
                    logger.debug(f"Channel {channel_id} - Inactivity threshold not reached yet")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in inactivity_check_loop: {e}", exc_info=True)

    @inactivity_check_loop.before_loop
    async def before_inactivity_check_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    # --- Performance Cache Clear Loop ---
    @tasks.loop(minutes=5)
    async def performance_cache_clear_loop(self):
        """Clears performance caches every 5 minutes to prevent memory buildup."""
        try:
            logger.debug("Running performance cache clear loop")

            # Import and clear the control UI performance caches
            from .control_ui import _clear_caches
            _clear_caches()

            # Clear any other performance-critical caches
            if hasattr(self, '_embed_cache'):
                # Clear embed cache if it's getting too large (>100 entries)
                if len(self._embed_cache.get('translated_terms', {})) > 100:
                    self._embed_cache['translated_terms'].clear()
                    logger.debug("Cleared embed translation cache due to size")

                if len(self._embed_cache.get('box_elements', {})) > 100:
                    self._embed_cache['box_elements'].clear()
                    logger.debug("Cleared embed box elements cache due to size")

            logger.debug("Performance cache clear completed")

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in performance_cache_clear_loop: {e}", exc_info=True)

    @performance_cache_clear_loop.before_loop
    async def before_performance_cache_clear_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    # Member count updates moved to on-demand during level-ups only

    # --- Final Control Command ---
    # REMOVED: Old single-message control command - replaced by Admin View version at line 1354
    # @commands.slash_command(name="control", description=_("Displays the control panel in the control channel"), guild_ids=get_guild_id())
    async def control_command(self, ctx: discord.ApplicationContext):
        """(Re)generates the control panel message in the current channel if permitted.

        NOTE: This method is kept for backwards compatibility but not exposed as a slash command.
        The new /control command at line 1354 provides the Admin View functionality.
        """
        # Check spam protection first
        if not await self._check_spam_protection(ctx, "control"):
            return

        if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
            return

        if not _channel_has_permission(ctx.channel.id, 'control', self.config):
            await ctx.respond(_("You do not have permission to use this command in this channel, or control panels are disabled here."), ephemeral=True)
            return

        # Permission check passed - now safe to defer with public response
        await ctx.defer(ephemeral=False)
        logger.info(f"Control panel regeneration requested by {ctx.author} in {ctx.channel.name}")

        try:
            await ctx.followup.send(_("Regenerating control panel... Please wait."), ephemeral=True)
        except (discord.errors.HTTPException, discord.errors.Forbidden) as e_followup:
            logger.error(f"Error sending initial followup for /control command: {e_followup}", exc_info=True)

        # Run regeneration directly instead of as background task for better user experience
        try:
            await self._regenerate_channel(ctx.channel, 'control', self.config)
            logger.info(f"Control panel regeneration completed for channel {ctx.channel.name}")
            # Send success confirmation
            try:
                await ctx.followup.send(_("✅ Control panel regenerated successfully!"), ephemeral=True)
            except Exception:
                pass  # Followup might have already been used or expired
        except (discord.errors.DiscordException, RuntimeError, OSError) as e_regen:
            logger.error(f"Error during control panel regeneration: {e_regen}", exc_info=True)
            try:
                await ctx.followup.send(_("❌ Error regenerating control panel. Check logs for details."), ephemeral=True)
            except Exception:
                pass

    # --- TASK COMMANDS REMOVED ---
    # All task-related Discord slash commands have been removed.
    # Task scheduling is now handled exclusively through the UI buttons in the server status panels.
    # Users can click the ⏰ button to add tasks and the ❌ button to delete tasks.

    # Note: The following implementation methods have been removed as they are no longer needed:
    # - All _impl_schedule_* methods (task creation via commands)
    # - _impl_task_delete_panel_command (task deletion panel via command)
    # Task management is now integrated into the status UI.

    # /info command removed - container information now accessed through UI buttons


    # --- Cog Teardown ---
    def cog_unload(self):
        """Cancel all running background tasks when the cog is unloaded."""
        logger.info("Unloading DockerControlCog, cancelling tasks...")
        if hasattr(self, 'heartbeat_send_loop') and self.heartbeat_send_loop.is_running(): self.heartbeat_send_loop.cancel()
        if hasattr(self, 'status_update_loop') and self.status_update_loop.is_running(): self.status_update_loop.cancel()
        if hasattr(self, 'periodic_message_edit_loop') and self.periodic_message_edit_loop.is_running(): self.periodic_message_edit_loop.cancel()
        if hasattr(self, 'inactivity_check_loop') and self.inactivity_check_loop.is_running(): self.inactivity_check_loop.cancel()
        if hasattr(self, 'performance_cache_clear_loop') and self.performance_cache_clear_loop.is_running(): self.performance_cache_clear_loop.cancel()
        # These three are started in setup() and used to be missing here, although
        # this method says of itself that it cancels ALL background tasks. After an
        # unload they kept running against a cog nobody uses any more - the donation
        # loop polls every 30 s and would announce a donation through a bot that has
        # been taken apart (review B31).
        if hasattr(self, 'start_mech_cache_loop') and self.start_mech_cache_loop.is_running(): self.start_mech_cache_loop.cancel()
        if hasattr(self, 'initial_animation_cache_warmup') and self.initial_animation_cache_warmup.is_running(): self.initial_animation_cache_warmup.cancel()
        if hasattr(self, 'donation_notification_task') and self.donation_notification_task.is_running(): self.donation_notification_task.cancel()
        # And the one-shot tasks the startup created. _active_tasks was written and
        # never read, so nothing stopped them - _track_task removes each one when it
        # ends, so what is left here is still running (review B39).
        for task in list(getattr(self, '_active_tasks', ())):
            if not task.done():
                task.cancel()
        logger.info("All direct Cog loops cancellation attempted.")

        # PERFORMANCE OPTIMIZATION: Clear all caches on unload
        try:
            from .control_ui import _clear_caches
            _clear_caches()
            logger.info("Performance caches cleared on cog unload")
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error clearing performance caches on unload: {e}", exc_info=True)

    # Method to update shared docker status cache from instance cache
    def update_global_status_cache(self):
        """Publish the current status cache snapshot to the shared runtime."""

        try:
            snapshot = self.status_cache_service.copy()
            self._status_cache_runtime.publish(snapshot)
            logger.debug(
                "Published docker status cache runtime snapshot with %d entries",
                len(snapshot),
            )
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error publishing docker status cache snapshot: {e}", exc_info=True)

    # Accessor method to get the current status cache
    def get_status_cache(self) -> Dict[str, Any]:
        """Returns the current status cache."""
        return self.status_cache_service.copy()

    async def _update_all_overview_messages_after_donation(self):
        """Force update all overview messages after a donation to show new mech animation."""
        logger.info("Updating all overview messages after donation...")

        try:
            # Iterate through all channels with overview messages
            updated_count = 0
            for channel_id, messages in self.channel_server_message_ids.items():
                if 'overview' in messages:
                    message_id = messages['overview']
                    try:
                        # Force recreation of the message with new animation
                        channel = self.bot.get_channel(channel_id)
                        if not channel:
                            continue

                        # Fetch the message
                        try:
                            message = await channel.fetch_message(message_id)
                        except discord.NotFound:
                            logger.warning(f"Overview message {message_id} not found in channel {channel_id}. REGENERATING new overview message for recovery.")

                            # RECOVERY: Generate new overview message to replace the missing one
                            try:
                                # Get fresh server data for regeneration
                                config = load_config()
                                if not config:
                                    continue

                                # SERVICE FIRST: Use ServerConfigService instead of direct config access
                                server_config_service = get_server_config_service()
                                servers = server_config_service.get_all_servers()

                                # Sort servers by the 'order' field from container configurations
                                ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

                                # Determine mech expansion state and create appropriate embed
                                is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
                                if is_mech_expanded:
                                    embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
                                else:
                                    embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)

                                # Create MechView with expand/collapse buttons
                                from .control_ui import MechView
                                view = MechView(self, channel_id)

                                # CLEAN SWEEP: Delete all old bot messages before creating new one
                                await self._clean_sweep_bot_messages(channel, "recovery from missing message")

                                # Send new overview message as recovery
                                if animation_file:
                                    if hasattr(animation_file, 'fp') and animation_file.fp:
                                        new_message = await channel.send(embed=embed, file=animation_file, view=view)
                                    else:
                                        new_message = await channel.send(embed=embed, view=view)
                                else:
                                    new_message = await channel.send(embed=embed, view=view)

                                # Update tracking with new message ID
                                self.channel_server_message_ids[channel_id]['overview'] = new_message.id
                                self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate
                                now_utc = datetime.now(timezone.utc)
                                if channel_id not in self.last_message_update_time:
                                    self.last_message_update_time[channel_id] = {}
                                self.last_message_update_time[channel_id]['overview'] = now_utc

                                logger.info(f"✅ RECOVERY SUCCESS: Generated new overview message {new_message.id} to replace missing {message_id} in channel {channel_id}")
                                continue

                            except (discord.errors.DiscordException, RuntimeError) as recovery_error:
                                logger.error(f"❌ RECOVERY FAILED: Could not regenerate overview message for channel {channel_id}: {recovery_error}", exc_info=True)
                                # Remove from tracking since we can't recover
                                if channel_id in self.channel_server_message_ids and 'overview' in self.channel_server_message_ids[channel_id]:
                                    del self.channel_server_message_ids[channel_id]['overview']
                                continue

                        # Get fresh server data
                        config = load_config()
                        if not config:
                            continue

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

                        # Create updated embed based on expansion state (with new mech animation)
                        is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
                        if is_mech_expanded:
                            embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
                        else:
                            embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)

                        # Delete and recreate message with new animation
                        # ROBUST: Handle case where message was already deleted (e.g., by /ss command)
                        try:
                            await message.delete()
                        except discord.NotFound:
                            logger.debug(f"Overview message {message_id} already deleted in channel {channel_id} (probably by /ss command)")
                            # Continue anyway - we'll create a new message below

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

                        # Update last_glvl_per_channel to prevent duplicate updates
                        try:
                            # Use CACHE for glvl tracking
                            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
                            cache_service = get_mech_status_cache_service()
                            cache_request = MechStatusCacheRequest(include_decimals=True)
                            mech_cache_result = cache_service.get_cached_status(cache_request)

                            if mech_cache_result.success:
                                current_glvl = mech_cache_result.glvl
                                self.last_glvl_per_channel[channel_id] = current_glvl
                                self.mech_state_manager.set_last_glvl(channel_id, current_glvl)
                        except Exception:
                            pass

                        updated_count += 1
                        logger.info(f"Updated overview message in channel {channel_id} after donation")
                    except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                        logger.error(f"Failed to update overview in channel {channel_id}: {e}", exc_info=True)

            logger.info(f"Successfully updated {updated_count} overview messages after donation")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error updating overview messages after donation: {e}", exc_info=True)

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
                    is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
                    if is_mech_expanded:
                        embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
                    else:
                        embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
                    # Create MechView with expand/collapse buttons
                    from .control_ui import MechView
                    view = MechView(self, channel_id)

                # CLEAN SWEEP: Delete all old bot messages before creating new one
                await self._clean_sweep_bot_messages(channel, "recovery from deleted message")

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

                # Create standard overview embed based on expansion state
                is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
                if is_mech_expanded:
                    embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
                else:
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

    def _register_persistent_mech_views(self):
        """Register persistent views for mech buttons to work after bot restart.

        Buttons whose custom_id contains a channel id are registered once per channel with
        a tracked overview (restored from disk before this runs), so the ids actually match.
        """
        try:
            from .control_ui import (MechExpandButton, MechCollapseButton, MechDonateButton,
                                   MechDisplayButton, ReadStoryButton, PlaySongButton, EpilogueButton,
                                   MechHistoryButton, MechView, MechDetailsView)
            from .admin_overview import AdminOverviewView
            import discord

            # Create persistent views for mech buttons
            # These views will persist across bot restarts
            class PersistentMechExpandView(DDCView):
                def __init__(self, cog_instance, channel_id):
                    super().__init__(timeout=None)
                    self.add_item(MechExpandButton(cog_instance, channel_id))

            class PersistentMechCollapseView(DDCView):
                def __init__(self, cog_instance, channel_id):
                    super().__init__(timeout=None)
                    self.add_item(MechCollapseButton(cog_instance, channel_id))

            class PersistentMechDonateView(DDCView):
                def __init__(self, cog_instance, channel_id):
                    super().__init__(timeout=None)
                    self.add_item(MechDonateButton(cog_instance, channel_id))

            class PersistentMechHistoryView(DDCView):
                def __init__(self, cog_instance, channel_id):
                    super().__init__(timeout=None)
                    self.add_item(MechHistoryButton(cog_instance, channel_id))

            # Create persistent views for mech selection buttons (levels 1-11)
            class PersistentMechSelectionView(DDCView):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    # Add buttons for all possible mech levels (1-11). Registered as locked: the
                    # callback re-checks the live mech level, so a pre-restart locked "Next"
                    # button can't reveal a locked mech (custom_id is the same either way).
                    for level in range(1, 12):
                        self.add_item(MechDisplayButton(cog_instance, level, f"{level}", False))
                    # Add epilogue button
                    self.add_item(EpilogueButton(cog_instance))

            # Create persistent views for story buttons (levels 1-11)
            class PersistentMechStoryView(DDCView):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    # Add story and music buttons for all possible levels (1-11)
                    for level in range(1, 12):
                        self.add_item(ReadStoryButton(cog_instance, level))
                        self.add_item(PlaySongButton(cog_instance, level))

            # Register persistent views with proper cog instance
            self.bot.add_view(PersistentMechSelectionView(self))
            self.bot.add_view(PersistentMechStoryView(self))

            # Channel-specific views for every channel with a tracked overview
            tracked_channels = dict(getattr(self, 'channel_server_message_ids', None) or {})
            for channel_id, tracked in tracked_channels.items():
                try:
                    channel_id = int(channel_id)
                    self.bot.add_view(PersistentMechExpandView(self, channel_id))
                    self.bot.add_view(PersistentMechCollapseView(self, channel_id))
                    self.bot.add_view(PersistentMechDonateView(self, channel_id))
                    self.bot.add_view(PersistentMechHistoryView(self, channel_id))
                    # Private (ephemeral) mech details: mech_private_donate/history_<channel_id>
                    self.bot.add_view(MechDetailsView(self, channel_id))
                    # The overview messages themselves, bound to their tracked message ids
                    tracked = tracked or {}
                    if tracked.get('overview'):
                        self.bot.add_view(MechView(self, channel_id), message_id=int(tracked['overview']))
                    if tracked.get('admin_overview'):
                        self.bot.add_view(AdminOverviewView(self, channel_id, True),
                                          message_id=int(tracked['admin_overview']))
                except (discord.errors.DiscordException, RuntimeError, ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Could not register persistent views for channel {channel_id}: {e}")

            logger.info(f"✅ Registered persistent mech views for button persistence ({len(tracked_channels)} tracked channel(s))")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.warning(f"⚠️ Could not register persistent mech views: {e}")

_register_loop_error_handlers(DockerControlCog)


class DonationView(DDCView):
    """View with donation buttons that track clicks."""

    def __init__(self, donation_manager_available: bool, message=None, bot=None):
        super().__init__(timeout=890)  # 14.8 minutes (just under Discord's 15-minute limit)
        self.donation_manager_available = donation_manager_available
        self.message = message  # Store reference to the message for auto-delete
        self.auto_delete_task = None
        self.bot = bot  # Store bot instance for modal access
        logger.info(f"DonationView initialized with donation_manager_available: {donation_manager_available}, timeout: 890s")

        # Import translation function
        from .translation_manager import _

        # Add Buy Me a Coffee button (direct link)
        coffee_button = discord.ui.Button(
            label=_("☕ Buy Me a Coffee"),
            style=discord.ButtonStyle.link,
            url="https://buymeacoffee.com/dockerdiscordcontrol"
        )
        self.add_item(coffee_button)

        # Add PayPal button (direct link)
        paypal_button = discord.ui.Button(
            label=_("💳 PayPal"),
            style=discord.ButtonStyle.link,
            url="https://www.paypal.com/donate/?hosted_button_id=XKVC6SFXU2GW4"
        )
        self.add_item(paypal_button)

        # Add Broadcast Donation button
        broadcast_button = discord.ui.Button(
            label=_("📢 Broadcast Donation"),
            style=discord.ButtonStyle.success,
            custom_id="donation_broadcast"
        )
        broadcast_button.callback = self.broadcast_clicked
        self.add_item(broadcast_button)

    async def on_timeout(self):
        """Called when the view times out."""
        try:
            # Cancel auto-delete task if it exists
            if self.auto_delete_task and not self.auto_delete_task.done():
                self.auto_delete_task.cancel()

            # Delete the message when timeout occurs
            if self.message:
                logger.info("DonationView timeout reached, deleting message to prevent inactive buttons")
                try:
                    await self.message.delete()
                except discord.NotFound:
                    logger.debug("Message already deleted")
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error deleting donation message on timeout: {e}", exc_info=True)
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in DonationView.on_timeout: {e}", exc_info=True)

    async def start_auto_delete_timer(self):
        """Start the auto-delete timer that runs shortly before timeout."""
        try:
            # Wait for 885 seconds (14.75 minutes), then delete message
            # This gives us a 5-second buffer before Discord's timeout
            await asyncio.sleep(885)
            if self.message:
                logger.info("Auto-deleting donation message before Discord timeout")
                try:
                    await self.message.delete()
                except discord.NotFound:
                    logger.debug("Message already deleted")
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error auto-deleting donation message: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("Auto-delete timer cancelled")
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in auto-delete timer: {e}", exc_info=True)

    async def broadcast_clicked(self, interaction: discord.Interaction):
        """Handle Broadcast Donation button click."""
        try:
            # Show modal for donation details
            modal = DonationBroadcastModal(self.donation_manager_available, interaction.user.name, self.bot)
            await interaction.response.send_modal(modal)
        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in broadcast_clicked: {e}", exc_info=True)

class DonationBroadcastModal(DDCModal):
    """Modal for donation broadcast details."""

    def __init__(self, donation_manager_available: bool, default_name: str, bot=None):
        from .translation_manager import _
        super().__init__(title=_("📢 Broadcast Your Donation"))
        self.donation_manager_available = donation_manager_available
        self.bot = bot  # Store bot instance for mech service access

        # Name field (pre-filled with Discord username)
        self.name_input = discord.ui.InputText(
            label=_("Your Name") + " *",
            placeholder=_("How should we display your name?"),
            value=default_name,
            style=discord.InputTextStyle.short,
            required=True,
            max_length=50
        )
        self.add_item(self.name_input)

        # Get dynamic placeholder for amount field with next level info
        amount_placeholder = self._get_dynamic_amount_placeholder()

        # Amount field (optional) with dynamic placeholder showing next level goal
        self.amount_input = discord.ui.InputText(
            label=_("💰 Donation Amount (optional)"),
            placeholder=amount_placeholder,
            style=discord.InputTextStyle.short,
            required=False,
            max_length=10
        )
        self.add_item(self.amount_input)

        # Public sharing field
        self.share_input = discord.ui.InputText(
            label=_("📢 Share donation publicly?"),
            placeholder=_("Remove X to keep private"),
            value="X",  # Default to sharing
            style=discord.InputTextStyle.short,
            required=False,
            max_length=10
        )
        self.add_item(self.share_input)

    def _get_dynamic_amount_placeholder(self) -> str:
        """Get dynamic placeholder text showing how much is needed for next level."""
        from .translation_manager import _

        try:
            # Get current mech state from progress_service (includes member-based dynamic costs)
            from services.mech.progress_service import get_progress_service

            progress_service = get_progress_service()
            state = progress_service.get_state()

            # Calculate remaining amount needed for next level
            needed_amount = state.evo_max - state.evo_current

            if needed_amount > 0 and state.level < 11:
                # Format amount (remove trailing zeros)
                formatted_amount = f"{needed_amount:.2f}".rstrip('0').rstrip('.')
                formatted_amount = formatted_amount.replace('.00', '')

                next_level = state.level + 1

                # Return dynamic placeholder with motivation text
                return f"💎 Need ${formatted_amount} for Level {next_level}! (e.g. {formatted_amount})"
            else:
                # At max level or no next level info
                return _("🎯 Support DDC development! (e.g. 10.50)")

        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Error getting dynamic amount placeholder: {e}", exc_info=True)
            # Fallback to default placeholder
            return _("10.50 (numbers only, $ will be added automatically)")

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.info(f"=== DONATION MODAL CALLBACK STARTED ===")
        logger.info(f"User: {interaction.user.name}, Raw inputs: name={self.name_input.value}, amount={self.amount_input.value}")

        # Send immediate acknowledgment to avoid timeout (will be replaced quickly)
        from .translation_manager import _
        await interaction.response.send_message(
            _("⏳ Processing..."),  # Shortened processing message
            ephemeral=True
        )

        try:
            # Get values from modal
            donor_name = self.name_input.value or interaction.user.name
            raw_amount = self.amount_input.value.strip() if self.amount_input.value else ""
            logger.info(f"Processed values: donor_name={donor_name}, raw_amount={raw_amount}")

            # Check sharing preference
            share_preference = self.share_input.value.strip() if self.share_input.value else ""
            should_share_publicly = "X" in share_preference.upper() or "x" in share_preference

            # Validate and format amount
            import re
            amount = ""
            amount_validation_error = None
            if raw_amount:
                if '-' in raw_amount:
                    amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - negative amounts not allowed"
                else:
                    cleaned_amount = re.sub(r'[^\d.,]', '', raw_amount)
                    cleaned_amount = cleaned_amount.replace(',', '.')

                    try:
                        numeric_value = float(cleaned_amount)
                        if numeric_value > 0:
                            amount = f"${numeric_value:.2f}"
                        elif numeric_value == 0:
                            amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - must be greater than 0"
                        else:
                            amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - please use only numbers"
                    except ValueError:
                        amount_validation_error = f"⚠️ Invalid amount: '{raw_amount}' - please use only numbers (e.g. 10.50)"

            if amount_validation_error:
                await interaction.followup.send(
                    amount_validation_error + _("\n\nTip: Use format like: 10.50 or 5 ($ will be added automatically)"),
                    ephemeral=True
                )
                return

            # Process donation through mech service
            donation_amount_euros = None
            processing_msg = None  # Initialize for later deletion
            # Set only after the ledger confirmed the booking. Previously the
            # broadcast below ran regardless: an exception was swallowed at the
            # "except" further down (evolution_occurred = False) and execution fell
            # through, and with donation_manager_available False nothing was booked
            # at all - both ways thanked the donor for money the ledger never saw.
            # SPEC.md Z3/Z8.
            donation_booked = False
            evolution_occurred = False
            old_evolution_level = None
            new_evolution_level = None

            if self.donation_manager_available:
                try:
                    from services.mech.mech_service import get_mech_service
                    mech_service = get_mech_service()

                    # Get old state before donation using SERVICE FIRST
                    from services.mech.mech_service import GetMechStateRequest
                    old_state_request = GetMechStateRequest(include_decimals=False)
                    old_state_result = mech_service.get_mech_state_service(old_state_request)
                    if not old_state_result.success:
                        logger.error("Failed to get old mech state")
                        # This used to be a bare return. The callback has already
                        # answered "⏳ Processing..." to close the modal, so every
                        # path after it owes the donor a replacement - and the
                        # booking failure three branches down does exactly that.
                        # Somebody who has just given money and is told nothing
                        # assumes it did not work, and gives again (review E19).
                        await interaction.edit_original_response(
                            content=_("❌ Donation processing failed: {error}").format(
                                error=_("the mech state could not be read")))
                        return
                    old_evolution_level = old_state_result.level

                    # Parse amount if provided
                    if amount:
                        amount_match = re.search(r'(\d+(?:\.\d+)?)', amount)
                        if amount_match:
                            donation_amount_euros = float(amount_match.group(1))

                    # Record donation if amount > 0
                    if donation_amount_euros and donation_amount_euros > 0:
                        amount_dollars = float(donation_amount_euros)  # Keep decimal precision

                        # Quick feedback to user first (store message to delete later)
                        processing_msg = await interaction.followup.send(
                            _("💰 Processing ${amount} donation...").format(amount=f"{amount_dollars:.2f}"),
                            ephemeral=False  # Make it visible so we can delete it
                        )

                        # UNIFIED DONATION SERVICE: Single clean path with guaranteed events
                        from services.donation.unified_donation_service import process_discord_donation

                        donation_result = await process_discord_donation(
                            discord_username=interaction.user.name,
                            amount=amount_dollars,
                            user_id=str(interaction.user.id),
                            guild_id=str(interaction.guild.id) if interaction.guild else None,
                            channel_id=str(interaction.channel.id) if interaction.channel else None,
                            bot_instance=self.bot,
                            # Unique per submission: if the same interaction reaches
                            # the service twice, it is booked once. SPEC.md Z4.
                            idempotency_key=str(interaction.id),
                        )

                        if not donation_result.success:
                            logger.error(f"Donation failed: {donation_result.error_message}")
                            # The PUBLIC "Processing..." message must go: this early
                            # return used to skip both places that delete it, so the
                            # channel kept reading "Processing a $X donation" for a
                            # donation that never happened (SPEC.md Z8, review B14).
                            if processing_msg:
                                try:
                                    await processing_msg.delete()
                                except (discord.NotFound, discord.HTTPException) as e:
                                    logger.warning(f"Could not remove the processing message: {e}")
                            await interaction.followup.send(
                                _("❌ Donation processing failed: {error}").format(error=donation_result.error_message),
                                ephemeral=True
                            )
                            return

                        new_state = donation_result.new_state
                        donation_booked = True
                        logger.info(f"Donation recorded via unified service: ${amount_dollars:.2f}")
                    else:
                        # Get current state using SERVICE FIRST
                        new_state_request = GetMechStateRequest(include_decimals=False)
                        new_state_result = mech_service.get_mech_state_service(new_state_request)
                        if not new_state_result.success:
                            logger.error("Failed to get new mech state")
                            # Same as above (review E19): a bare return left the
                            # donor at "⏳ Processing..." for ever.
                            await interaction.edit_original_response(
                                content=_("❌ Donation processing failed: {error}").format(
                                    error=_("the mech state could not be read")))
                            return

                    # For donation cases, the new_state is returned from add_donation methods
                    # For non-donation cases, we use the SERVICE FIRST result
                    if 'new_state' not in locals():
                        new_evolution_level = new_state_result.level
                        evolution_occurred = new_evolution_level > old_evolution_level
                        old_power = old_state_result.power
                        new_power = new_state_result.power
                    else:
                        # Check if evolution occurred (donation cases)
                        evolution_occurred = new_state.level > old_evolution_level
                        new_evolution_level = new_state.level
                        old_power = old_state_result.power
                        new_power = new_state.Power

                    if evolution_occurred:
                        logger.info(f"EVOLUTION! Level {old_evolution_level} → {new_evolution_level}")

                    # Force update of mech animation when level OR power changes.
                    # new_power is already set by BOTH branches above (:4866 from
                    # new_state_result, :4872 from new_state), so re-reading it from
                    # new_state here was redundant - and fatal when no amount was named:
                    # that path never assigns new_state, and the UnboundLocalError fell
                    # through both except blocks (:4885 and :4973 list neither), so the
                    # final response at :4964 was never sent and the user kept staring at
                    # "Processing..." while the supporter message never went out.
                    # new_evolution_level is set by both branches, so it is used instead.
                    # SPEC.md Z3.
                    level_changed = new_evolution_level != old_state_result.level
                    power_changed = new_power != old_power

                    if level_changed or power_changed:
                        if level_changed:
                            logger.info(f"Level changed from {old_state_result.level} to {new_evolution_level} - updating mech animations")
                        if power_changed:
                            logger.info(f"Power changed from {old_power} to {new_power} - updating mech animations")

                        # Events are now automatically handled by UnifiedDonationService
                        # No manual event emission needed - prevents duplicate events

                        # REMOVED: Manual update call to prevent duplicate updates
                        # The donation_event already triggers automatic updates via event system
                        # Manual update here caused double-updates and race conditions
                        logger.info("Donation event will trigger automatic overview updates via event system")

                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error processing donation: {e}", exc_info=True)
                    evolution_occurred = False

            # Create broadcast message
            if amount:
                broadcast_text = _("{donor_name} donated {amount} to DDC – thank you so much ❤️").format(
                    donor_name=f"**{donor_name}**",
                    amount=f"**{amount}**"
                )
            else:
                broadcast_text = _("{donor_name} supports DDC – thank you so much ❤️").format(
                    donor_name=f"**{donor_name}**"
                )

            # Create evolution status
            evolution_status = ""
            if evolution_occurred:
                evolution_status = _("**Evolution: Level {old} → {new}!**").format(
                    old=old_evolution_level,
                    new=new_evolution_level
                )
                # Say what happens to the power, otherwise the level-up looks like lost money:
                # on level-up the surplus above the goal becomes the new power (plus $1 on an
                # exact hit), so a donation that just barely reaches the goal leaves the mech
                # near zero and offline immediately afterwards.
                evolution_status += "\n" + _("Surplus carried over as new power: {power}").format(
                    power=f"${new_power:.2f}"
                )

            # Send to channels if sharing publicly
            sent_count = 0
            failed_count = 0

            # "The user named no amount" and "the amount was never processed" are two
            # different things, and conflating them defeated this guard once already:
            # donation_amount_euros is assigned only INSIDE the booking block above,
            # so it stays None whenever booking is skipped - which let an unbooked
            # donation broadcast through. The user's own input decides instead. With
            # an amount a confirmed booking is required; without one there is nothing
            # to book and the "X supports DDC" message may go out. `amount` is also
            # what the message below branches on, so guard and message agree.
            broadcast_allowed = donation_booked or not amount
            if should_share_publicly and not broadcast_allowed:
                logger.warning(
                    "Donation broadcast suppressed: the ledger did not confirm the booking"
                )

            if should_share_publicly and broadcast_allowed:
                config = load_config()
                channels_config = config.get('channel_permissions', {})

                opted_out_count = 0

                for channel_id_str, channel_info in channels_config.items():
                    try:
                        channel_id = int(channel_id_str)
                        channel = interaction.client.get_channel(channel_id)

                        # Same rule the notification loop already applies further
                        # down: a channel that opted out of donation broadcasts gets
                        # nothing. This path used to ignore the flag entirely.
                        if channel and channel_info.get('donation_broadcasts', True):
                            embed = discord.Embed(
                                title=_("💝 Donation received"),
                                description=broadcast_text,
                                color=0x00ff41
                            )

                            if evolution_status:
                                embed.add_field(name=_("Mech Status"), value=evolution_status, inline=False)

                            embed.set_footer(text="https://ddc.bot")
                            await channel.send(embed=embed)
                            sent_count += 1
                        elif channel is not None:
                            # Opted out in the web panel - counted on its own. It used
                            # to raise failed_count like a channel that could not be
                            # reached, and the admin was told deliveries had failed
                            # when nothing had (review B36).
                            opted_out_count += 1
                            logger.info(f"Donation notice not sent to channel {channel_id_str}: "
                                        f"the channel opted out of donation broadcasts")
                        else:
                            failed_count += 1

                    except (discord.errors.DiscordException, RuntimeError) as channel_error:
                        failed_count += 1
                        logger.error(f"Error sending to channel {channel_id_str}: {channel_error}", exc_info=True)

            # Respond to user
            if should_share_publicly and not broadcast_allowed:
                response_text = _("⚠️ **Donation could not be recorded**") + "\n\n"
                response_text += _("Nothing was sent to any channel. Please try again later.")
            elif should_share_publicly:
                # Channels that opted out are neither a delivery nor a failure, so
                # they appear in the log and not in this summary (review B36).
                logger.info(f"Donation broadcast: {sent_count} sent, {failed_count} failed, "
                            f"{opted_out_count} opted out")
                response_text = _("✅ **Donation broadcast sent!**") + "\n\n"
                response_text += _("📢 Sent to **{count}** channels").format(count=sent_count) + "\n"
                if failed_count > 0:
                    response_text += _("⚠️ Failed to send to {count} channels").format(count=failed_count) + "\n"
                response_text += "\n" + _("Thank you **{donor_name}** for your generosity! 🙏").format(donor_name=donor_name)
            else:
                response_text = _("✅ **Donation recorded privately!**") + "\n\n"
                response_text += _("Thank you **{donor_name}** for your generous support! 🙏").format(donor_name=donor_name) + "\n"
                response_text += _("Your donation has been recorded and helps power the Donation Engine.")

            # Replace the processing message with the final result
            await interaction.edit_original_response(content=response_text)

            # Clean up processing message if donation was processed
            if processing_msg:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass  # Ignore if already deleted or expired

        except Exception as e:  # noqa: BLE001
            # Broad on purpose. Everything below this line exists to give the
            # donor an answer and to remove the public "Processing a $X
            # donation" message, and the tuple that stood here - (DiscordException,
            # RuntimeError, ValueError) - did not include what the mech service
            # actually raises: MechStateError -> MechServiceError ->
            # DDCBaseException. So a mech failure left the callback entirely,
            # past the cleanup and past the answer, and the donor watched
            # "⏳ Processing..." for ever (review E19).
            logger.error("Error in donation broadcast modal: %s: %s",
                         type(e).__name__, e, exc_info=True)

            # Clean up processing message even if error occurred
            if processing_msg:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass

            try:
                await interaction.edit_original_response(
                    content=_("❌ Error sending donation broadcast. Please try again later.")
                )
            except (discord.errors.HTTPException, discord.errors.Forbidden) as edit_error:
                logger.error(f"Could not send error response: {edit_error}", exc_info=True)


class AddAdminModal(DDCModal):
    """Modal for adding a new admin user."""

    def __init__(self):
        from .translation_manager import _
        super().__init__(title=_("➕ Add Admin User"))

        # Discord User ID field
        self.user_id_input = discord.ui.InputText(
            label=_("Discord User ID"),
            placeholder=_("Enter the Discord User ID (e.g., 123456789012345678)"),
            style=discord.InputTextStyle.short,
            required=True,
            min_length=17,
            max_length=20
        )
        self.add_item(self.user_id_input)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        from .translation_manager import _
        logger.info(f"=== ADD ADMIN MODAL CALLBACK STARTED ===")
        logger.info(f"User: {interaction.user.name}, Raw input: user_id={self.user_id_input.value}")

        try:
            # Get and validate the user ID
            raw_user_id = self.user_id_input.value.strip()

            # Validate: must be numeric and valid Discord snowflake format
            if not raw_user_id.isdigit():
                await interaction.response.send_message(
                    _("❌ Invalid User ID. Please enter only numbers (e.g., 123456789012345678)."),
                    ephemeral=True
                )
                return

            user_id = raw_user_id

            # Check if ID is in valid Discord snowflake range (>= Discord epoch)
            if int(user_id) < 21154535154122752:  # Minimum valid Discord snowflake
                await interaction.response.send_message(
                    _("❌ Invalid Discord User ID. The ID appears to be too small."),
                    ephemeral=True
                )
                return

            # Get admin service and current admins
            from services.admin.admin_service import get_admin_service
            admin_service = get_admin_service()
            admin_data = admin_service.get_admin_data(force_refresh=True)
            current_admins = admin_data.get('discord_admin_users', [])
            admin_notes = admin_data.get('admin_notes', {})

            # Check if user is already an admin
            if user_id in current_admins:
                await interaction.response.send_message(
                    _("⚠️ This user is already an admin."),
                    ephemeral=True
                )
                return

            # Add the new admin
            current_admins.append(user_id)

            # Save the updated admin list
            success = admin_service.save_admin_data(current_admins, admin_notes)

            if success:
                logger.info(f"Admin added successfully: {user_id} by {interaction.user.id}")
                await interaction.response.send_message(
                    _("✅ Admin added successfully!\n\nUser ID: `{user_id}`\nTotal admins: {count}").format(
                        user_id=user_id,
                        count=len(current_admins)
                    ),
                    ephemeral=True
                )
            else:
                logger.error(f"Failed to save admin data when adding {user_id}")
                await interaction.response.send_message(
                    _("❌ Failed to save admin data. Please try again."),
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in AddAdminModal callback: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        _("❌ An error occurred while adding the admin. Please try again."),
                        ephemeral=True
                    )
            except (discord.errors.DiscordException, RuntimeError):
                pass


# Setup function required for extension loading
def _remove_donation_commands(bot):
    """Take /donate and /donatebroadcast off the bot when donations are switched off.

    Called AFTER bot.add_cog(): only then are the cog's commands on the bot at
    all, and then they are in pending_application_commands - application_commands
    stays empty until Discord has registered them and handed back their ids.

    This used to ask "if cmd_name in bot.application_commands" and delete by
    name. In py-cord 2.6.1 that property builds a new LIST of command objects,
    so a string is never in it: the removal never happened and the line that
    reports it was never reached either. Donations off in the web panel, both
    commands still in Discord (review B18).
    """
    try:
        from services.donation.donation_utils import is_donations_disabled
        if not is_donations_disabled():
            return
        for cmd_name in ('donate', 'donatebroadcast'):
            found = [command for command in
                     list(bot.pending_application_commands) + list(bot.application_commands)
                     if getattr(command, 'name', None) == cmd_name]
            if not found:
                logger.warning(f"/{cmd_name} was not on the bot - nothing to remove")
                continue
            for command in found:
                bot.remove_application_command(command)
            logger.info(f"Removed /{cmd_name} command - donations disabled")
    except (KeyError, AttributeError, RuntimeError) as e:
        logger.error(f"Could not remove donation commands: {e}", exc_info=True)


def setup(bot):
    """Setup function to add the cog to the bot when loaded as an extension.

    IMPORTANT: In PyCord 2.x, setup() must be synchronous (def, not async def).
    Only discord.py 2.0+ supports async setup functions.
    """
    logger.debug("setup() function called - NEW CODE VERSION 0f3d5cb")
    logger.debug("About to load config...")
    from services.config.config_service import get_config_service
    config_manager = get_config_service()
    config = config_manager.get_config()
    logger.debug("Config loaded, about to instantiate DockerControlCog...")
    cog = DockerControlCog(bot, config)
    logger.debug("DockerControlCog instantiated successfully!")

    # Add simple donation notification task
    @tasks.loop(seconds=30)
    async def check_donation_notifications():
        """Check for donation notifications from Web UI"""
        try:
            # SERVICE FIRST: Use notification service instead of direct file access
            from services.donation.notification_service import get_donation_notification_service
            
            service = get_donation_notification_service()
            # This handles file check, reading, JSON parsing, and deletion atomically
            notification = service.check_and_retrieve_notification()

            if notification and notification.get('type') == 'donation':
                donor_name = notification.get('donor', 'Anonymous')
                amount = notification.get('amount', 0)

                logger.info(f"🔔 Processing donation notification: {donor_name} ${amount}")

                try:
                    # Create broadcast message (same as /donate) using configured Discord bot language.
                    # Uses the module-level `_` from .translation_manager (there is no get_translation()).
                    if amount:
                        # Format amount exactly like /donate command: $X.XX
                        formatted_amount = f"${float(amount):.2f}"
                        broadcast_text = _("{donor_name} donated {amount} to DDC – thank you so much ❤️").format(
                            donor_name=f"**{donor_name}**",
                            amount=f"**{formatted_amount}**"
                        )
                    else:
                        broadcast_text = _("{donor_name} supports DDC – thank you so much ❤️").format(
                            donor_name=f"**{donor_name}**"
                        )

                    # Create embed (same style as /donate)
                    embed = discord.Embed(
                        title=_("💝 Donation received"),
                        description=broadcast_text,
                        color=0x00ff41
                    )
                    embed.set_footer(text="https://ddc.bot")

                    logger.info(f"🔔 Created donation embed for {donor_name} ${amount}")

                    # Send to configured Status and Control channels from Web UI (like /donate command)
                    sent_count = 0
                    config = load_config()
                    channels_config = config.get('channel_permissions', {})

                    logger.info(f"🔔 Found {len(channels_config)} configured channels in Web UI")

                    for channel_id_str, channel_info in channels_config.items():
                        try:
                            channel = bot.get_channel(int(channel_id_str))
                            donation_broadcasts = channel_info.get('donation_broadcasts', True)

                            logger.info(f"🔔 Channel {channel_id_str}: found={channel is not None}, broadcasts={donation_broadcasts}")

                            if channel and donation_broadcasts:
                                await channel.send(embed=embed)
                                sent_count += 1
                                logger.info(f"🔔 Successfully sent to channel {channel.name} ({channel_id_str})")
                            else:
                                if not channel:
                                    logger.debug(f"🔔 Channel {channel_id_str} not found")
                                elif not donation_broadcasts:
                                    logger.debug(f"🔔 Donation broadcasts disabled for {channel_id_str}")
                        except (discord.errors.DiscordException, RuntimeError) as channel_error:
                            logger.error(f"🔔 Error sending to channel {channel_id_str}: {channel_error}", exc_info=True)

                    logger.info(f"🔔 Processed Web UI donation: {donor_name} ${amount} - sent to {sent_count} channels")

                except (discord.errors.DiscordException, RuntimeError, ValueError) as embed_error:
                    logger.error(f"🔔 Error creating/sending donation embed: {embed_error}", exc_info=True)

        except Exception as e:
            # Deliberately broad, and ERROR, not DEBUG (SPEC.md Z8). Once
            # check_and_retrieve_notification() has returned, the notification
            # file is deleted - a failure after that loses the announcement for
            # good. This used to catch only three types and log them at DEBUG,
            # so a lost announcement left no visible trace; any other type
            # (TypeError, KeyError, ...) left the body, and a tasks.loop whose
            # body raises stops for good - no web donation was announced again
            # until a restart. This is the loop boundary: log loudly, keep going.
            logger.error(f"Donation notification from the web panel was not announced: {e}",
                         exc_info=True)

    # Start the task and add to cog
    # Same reason as every loop on the cog (review E17): py-cord's default error
    # handler is a print() to stderr, so a loop that stops stops in silence.
    # This one is not an attribute of the class, so _register_loop_error_handlers
    # does not reach it - it is given the same handler by hand.
    async def _donation_loop_stopped(*args):
        exception = args[-1]
        logger.error(
            "BACKGROUND LOOP STOPPED: 'check_donation_notifications' ended with "
            "%s: %s. It will NOT run again until DDC is restarted - donations "
            "made in the web panel are no longer announced in Discord.",
            type(exception).__name__, exception, exc_info=exception)

    check_donation_notifications.error(_donation_loop_stopped)
    check_donation_notifications.start()
    cog.donation_notification_task = check_donation_notifications

    # Start the Mech Status Cache background loop
    cog.start_mech_cache_loop.start()
    logger.info("Mech Status Cache startup task initiated")

    # Start the Initial Animation Cache Warmup
    cog.initial_animation_cache_warmup.start()
    logger.info("Initial Animation Cache Warmup startup task initiated")

    bot.add_cog(cog)
    logger.debug("DockerControlCog added to bot")

    _remove_donation_commands(bot)

    # Start background loops NOW (in setup(), after cog is added)
    # NOTE: Cannot use on_ready() because bot is already ready when cog loads
    # NOTE: Cannot use cog_load() because PyCord 2.x doesn't support it
    logger.debug("Starting background loops directly from setup()...")
    try:
        # Ensure clean loop state
        cog._cancel_existing_loops()
        # Start all background loops
        cog._setup_background_loops()
        cog._background_loops_started = True
        logger.debug("Background loops started successfully!")
    except Exception as e:
        logger.error(f"[SETUP DEBUG] Failed to start background loops: {e}", exc_info=True)
