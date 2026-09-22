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
from .channel_lifecycle import ChannelLifecycleMixin
# The donation views and the /addadmin modal live in donation_ui.py since the
# Phase 3 split; the names stay importable from here (admin_overview uses them).
from .donation_ui import AddAdminModal, DonationBroadcastModal, DonationView  # noqa: F401
from .message_updates import MessageUpdatesMixin
from .background_loops import BackgroundLoopsMixin
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


# Background loops: one bad cycle must not be the last one (review E17). The two
# helpers live in loop_safety.py since the Phase 3 cog split, so the loop mixin
# can use them without importing this module; the names stay available here.
from .loop_safety import _register_loop_error_handlers, survives_one_bad_cycle  # noqa: E402,F401


class DockerControlCog(commands.Cog, StatusHandlersMixin, OverviewEmbedsMixin, SlashCommandsMixin, BackgroundLoopsMixin, MessageUpdatesMixin, ChannelLifecycleMixin):
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
                # _auto_update_ss_messages handles the overview messages, under the
                # per-channel lock. (A second, unlocked poster for this event was
                # removed on 2026-09-22: it was unreachable and would have posted
                # duplicates the day it was wired back up.)
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
                                                allow_toggle=True, force_collapse=False
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
            # Everything that is waiting, not one per cycle: donations
            # booked in the panel within the same 30 seconds each have
            # their own file now, and waiting a cycle per file would put
            # a thank-you minutes behind the donation. The cap keeps one
            # cycle finite; whatever is left is taken by the next one.
            for _announcement in range(20):
                # Reads the oldest file, parses it and deletes it.
                notification = service.check_and_retrieve_notification()
                if not notification:
                    break

                if notification.get('type') == 'donation':
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
