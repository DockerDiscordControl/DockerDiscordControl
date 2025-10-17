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
import threading
from typing import Dict, Any, List, Optional, Tuple, Union
from io import BytesIO
from pathlib import Path

# Import app_commands using central utility
from utils.app_commands_helper import get_app_commands, get_discord_option
app_commands = get_app_commands()
DiscordOption = get_discord_option()

# Discord services
from services.discord.channel_cleanup_service import get_channel_cleanup_service

# Import our utility functions
from services.config.config_service import load_config, get_config_service
from services.docker_service.docker_utils import get_docker_info, get_docker_stats, docker_action

from utils.time_utils import format_datetime_with_timezone
from utils.logging_utils import setup_logger
from services.docker_service.server_order import load_server_order, save_server_order

# Import scheduler module
from services.scheduling.scheduler import (
    ScheduledTask, add_task, delete_task, update_task, load_tasks,
    get_tasks_for_container, get_next_week_tasks, get_tasks_in_timeframe,
    VALID_CYCLES, VALID_ACTIONS, DAYS_OF_WEEK,
    parse_time_string, parse_month_string, parse_weekday_string,
    CYCLE_ONCE, CYCLE_DAILY, CYCLE_WEEKLY, CYCLE_MONTHLY,
    CYCLE_NEXT_WEEK, CYCLE_NEXT_MONTH, CYCLE_CUSTOM,
    check_task_time_collision
)

# Import outsourced parts
from .translation_manager import _, get_translations
from .control_helpers import get_guild_id, container_select, _channel_has_permission, _get_pending_embed
from .control_ui import ActionButton, ToggleButton, ControlView

# Import the autocomplete handlers that have been moved to their own module
# Note: Task-related autocomplete handlers removed as commands are now UI-based

# Schedule commands mixin removed - task scheduling now handled through UI

# Import the status handlers mixin that contains status-related functionality
from .status_handlers import StatusHandlersMixin

# Import the command handlers mixin that contains Docker action command functionality 
# Command handlers removed - using UI buttons for all container control

# Import central logging function
from services.infrastructure.action_logger import log_user_action

# Configure logger for the cog using utility (INFO for release)
logger = setup_logger('ddc.docker_control', level=logging.INFO)

# Global variable for Docker status cache to allow access from other modules
docker_status_cache = {}
docker_status_cache_lock = threading.Lock()  # Thread safety for global status cache

# DonationView will be defined in this file

class DockerControlCog(commands.Cog, StatusHandlersMixin):
    """Cog for DockerDiscordControl container management via Discord."""

    def __init__(self, bot: commands.Bot, config: dict):
        """Initializes the DockerDiscordControl Cog."""
        logger.info("Initializing DockerControlCog... [DDC-SETUP]")
        
        # Basic initialization
        self.bot = bot
        self.config = config
        
        # Check if donations are disabled and remove donation commands
        try:
            from services.donation.donation_utils import is_donations_disabled
            if is_donations_disabled():
                logger.info("Donations are disabled - removing donation commands")
                # Remove donate and donatebroadcast commands after cog is initialized
                self.donations_disabled = True
        except Exception as e:
            logger.debug(f"Error checking donation status: {e}")
            self.donations_disabled = False
        
        # Initialize Mech State Manager for persistence
        from services.mech.mech_state_manager import get_mech_state_manager
        self.mech_state_manager = get_mech_state_manager()
        
        # Member count updates moved to on-demand (during donations with level-ups)
        
        # Load persisted states
        state_data = self.mech_state_manager.load_state()
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
        self.channel_server_message_ids: Dict[int, Dict[str, int]] = {}
        self.last_message_update_time: Dict[int, Dict[str, datetime]] = {}
        self.initial_messages_sent = False
        self.last_channel_activity: Dict[int, datetime] = {}
        
        # Cache configuration
        self.status_cache = {}
        # Calculate cache TTL from status update loop interval (default 30s * 2.5 = 75s)
        cache_duration = int(os.environ.get('DDC_DOCKER_CACHE_DURATION', '30'))
        self.cache_ttl_seconds = int(cache_duration * 2.5)
        self.pending_actions: Dict[str, Dict[str, Any]] = {}
        self.pending_actions_lock = asyncio.Lock()  # Protect concurrent access

        # Initialize services
        self.cleanup_service = get_channel_cleanup_service(bot)

        # Initialize Mech Status Cache Service
        from services.mech.mech_status_cache_service import get_mech_status_cache_service
        self.mech_status_cache_service = get_mech_status_cache_service()
        logger.info("MechStatusCacheService initialized")

        # Docker query cooldown tracking
        self.last_docker_query = {}  # Track last query time per container
        self.docker_query_cooldown = int(os.environ.get('DDC_DOCKER_QUERY_COOLDOWN', '2'))
        
        # Load server order
        self.ordered_server_names = load_server_order()
        logger.info(f"[Cog Init] Loaded server order from persistent file: {self.ordered_server_names}")
        if not self.ordered_server_names:
            if 'server_order' in config:
                logger.info("[Cog Init] Using server_order from config")
                self.ordered_server_names = config.get('server_order', [])
            else:
                logger.info("[Cog Init] No server_order found, using all server names from config")
                self.ordered_server_names = [s.get('docker_name') for s in config.get('servers', []) if s.get('docker_name')]
            save_server_order(self.ordered_server_names)
            logger.info(f"[Cog Init] Saved default server order: {self.ordered_server_names}")
        
        # Register persistent views for mech buttons
        self._register_persistent_mech_views()
            
        # Initialize translations
        self.translations = get_translations()
        
        # Initialize self as status handler
        self.status_handlers = self
        
        # Initialize performance monitoring
        self._loop_stats = {
            'status_update': {'runs': 0, 'errors': 0, 'last_duration': 0},
            'message_edit': {'runs': 0, 'errors': 0, 'last_duration': 0},
            'inactivity': {'runs': 0, 'errors': 0, 'last_duration': 0},
            'cache_clear': {'runs': 0, 'errors': 0, 'last_duration': 0},
            'heartbeat': {'runs': 0, 'errors': 0, 'last_duration': 0}
        }
        
        # Initialize task tracking
        self._active_tasks = set()
        self._task_lock = asyncio.Lock()
        
        # Ensure clean loop state
        logger.info("Ensuring clean loop state...")
        self._cancel_existing_loops()
        
        # Initialize background loops with proper error handling
        logger.info("Setting up background loops...")
        self._setup_background_loops()

        # PERFORMANCE OPTIMIZATION: Initialize embed cache for StatusHandlersMixin
        self._embed_cache = {
            'translated_terms': {},
            'box_elements': {},
            'last_cache_clear': datetime.now(timezone.utc)
        }
        self._EMBED_CACHE_TTL = 300  # 5 minutes cache for embed elements

        logger.info("Ensuring other potential loops (if any residues from old structure) are cancelled.")
        if hasattr(self, 'heartbeat_send_loop') and self.heartbeat_send_loop.is_running(): self.heartbeat_send_loop.cancel()
        if hasattr(self, 'status_update_loop') and self.status_update_loop.is_running(): self.status_update_loop.cancel()
        if hasattr(self, 'inactivity_check_loop') and self.inactivity_check_loop.is_running(): self.inactivity_check_loop.cancel()

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
        except Exception as e:
            logger.error(f"Task error: {e}", exc_info=True)
        finally:
            async with self._task_lock:
                self._active_tasks.discard(task)
    
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
            
            # Start heartbeat loop if enabled (supports legacy and new config)
            heartbeat_enabled = False
            try:
                # Prefer latest cached config (reflects Web UI changes)
                latest_config = load_config() or {}
            except Exception:
                latest_config = {}

            # New format
            heartbeat_cfg_obj = latest_config.get('heartbeat') if isinstance(latest_config, dict) else None
            if isinstance(heartbeat_cfg_obj, dict):
                heartbeat_enabled = bool(heartbeat_cfg_obj.get('enabled', False))

            # Legacy enable if a numeric channel id exists at root
            legacy_channel_id = (latest_config or self.config).get('heartbeat_channel_id')
            if not heartbeat_enabled and legacy_channel_id is not None:
                legacy_str = str(legacy_channel_id)
                if legacy_str.isdigit():
                    heartbeat_enabled = True

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
                except Exception as e:
                    logger.error(f"Error in initial status send: {e}", exc_info=True)
            
            self.bot.loop.create_task(send_initial_after_delay())
            
        except Exception as e:
            logger.error(f"Error setting up background loops: {e}", exc_info=True)
            raise

        # Initialize global status cache
        self.update_global_status_cache()
        
        logger.info("DockerControlCog __init__ complete. Background loops and initial status send scheduled.")

    # --- PERIODIC MESSAGE EDIT LOOP (FULL LOGIC, MOVED DIRECTLY INTO COG) ---
    @tasks.loop(minutes=1, reconnect=True)
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
        
        # ULTRA-PERFORMANCE: Collect all containers that might need updates for bulk fetching
        all_container_names = set()
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

                should_update = False
                if last_update_time is None:
                    should_update = True
                    logger.info(f"Direct Cog Periodic Edit Loop: Scheduling edit for '{display_name}' in channel {channel_id} (Message ID: {message_id}). Reason: No previous update time recorded.")
                elif (now_utc - last_update_time) >= update_interval_delta:
                    should_update = True
                    logger.info(f"Direct Cog Periodic Edit Loop: Scheduling edit for '{display_name}' in channel {channel_id} (Message ID: {message_id}). Reason: Interval passed (Last: {last_update_time}, Now: {now_utc}, Interval: {update_interval_delta}).")
                else:
                    time_since_last_update = now_utc - last_update_time
                    time_to_next_update = update_interval_delta - time_since_last_update
                    logger.debug(f"Direct Cog Periodic Edit Loop: Skipping edit for '{display_name}' in channel {channel_id} (Message ID: {message_id}). Interval not passed. Time since last: {time_since_last_update}. Next update in: {time_to_next_update}.")

                if should_update:
                    # IMPROVED: Skip refresh for containers in pending state
                    if display_name in self.pending_actions:
                        pending_timestamp = self.pending_actions[display_name]['timestamp']
                        pending_duration = (now_utc - pending_timestamp).total_seconds()
                        if pending_duration < 120:  # Same timeout as in status_handlers.py
                            logger.info(f"Direct Cog Periodic Edit Loop: Skipping edit for '{display_name}' - container is pending (duration: {pending_duration:.1f}s)")
                            continue  # Skip this container
                    
                    # PERFORMANCE OPTIMIZATION: Smart offline container handling
                    current_server_conf = next((s for s in self.config.get('servers', []) if s.get('name', s.get('docker_name')) == display_name), None)
                    if current_server_conf and display_name != "overview":
                        docker_name = current_server_conf.get('docker_name')
                        if docker_name:
                                                         # Check if container is offline from status cache
                             cached_status = self.status_cache.get(docker_name)
                             if cached_status:
                                 try:
                                     # Check cache age with DDC_DOCKER_MAX_CACHE_AGE
                                     import os
                                     max_cache_age = int(os.environ.get('DDC_DOCKER_MAX_CACHE_AGE', '300'))
                                     
                                     # Handle both cache formats: direct tuple or {'data': tuple, 'timestamp': datetime}
                                     if isinstance(cached_status, dict) and 'data' in cached_status:
                                         # Check if cache is still valid
                                         if 'timestamp' in cached_status:
                                             cache_age = (datetime.now(timezone.utc) - cached_status['timestamp']).total_seconds()
                                             if cache_age > max_cache_age:
                                                 logger.debug(f"Cache for {docker_name} expired ({cache_age:.1f}s > {max_cache_age}s)")
                                                 cached_status = None
                                     
                                     if cached_status and isinstance(cached_status, dict) and 'data' in cached_status:
                                         # New format: extract data from dict
                                         status_data = cached_status['data']
                                     else:
                                         status_data = cached_status
                                     
                                     # Ensure status_data is subscriptable (list, tuple, etc.)
                                     if not hasattr(status_data, '__getitem__') or not hasattr(status_data, '__len__'):
                                         logger.debug(f"Cache data for {docker_name} is not subscriptable: {type(status_data)}")
                                         continue
                                     
                                     # Handle different tuple formats: (display_name, is_running, cpu, ram, uptime, details_allowed)
                                     if len(status_data) >= 6:
                                         _, is_running, _, _, _, _ = status_data
                                     elif len(status_data) >= 2:
                                         _, is_running = status_data[:2]  # Take only first 2 values
                                     else:
                                         logger.debug(f"Unexpected cache data format for {docker_name}: {len(status_data)} values")
                                         continue
                                 except (ValueError, TypeError, KeyError, IndexError) as e:
                                     logger.debug(f"Error unpacking cache for {docker_name}: {e}")
                                     continue
                                 
                                 if not is_running:
                                    # For offline containers, use reduced update interval (5 minutes instead of 1)
                                    offline_interval_minutes = 5
                                    last_offline_update = self.last_message_update_time.get(channel_id, {}).get(display_name)
                                    if last_offline_update:
                                        time_since_offline_update = now_utc - last_offline_update
                                        offline_threshold = timedelta(minutes=offline_interval_minutes)
                                        
                                        if time_since_offline_update < offline_threshold:
                                            logger.debug(f"Direct Cog Periodic Edit Loop: Skipping offline container '{display_name}' - last update {time_since_offline_update} ago (offline interval: {offline_interval_minutes}m)")
                                            continue  # Skip offline container update
                    
                    allow_toggle_for_channel = _channel_has_permission(channel_id, 'control', self.config)
                    # Special case for overview message
                    if display_name == "overview":
                        tasks_to_run.append(self._update_overview_message(channel_id, message_id))
                    else:
                        # ULTRA-PERFORMANCE: Collect container names for bulk fetching
                        current_server_conf = next((s for s in self.config.get('servers', []) if s.get('name', s.get('docker_name')) == display_name), None)
                        if current_server_conf:
                            docker_name = current_server_conf.get('docker_name')
                            if docker_name:
                                all_container_names.add(docker_name)
                        
                        # Regular server message
                        tasks_to_run.append(self._edit_single_message_wrapper(channel_id, display_name, message_id, self.config, allow_toggle_for_channel))
            
        if tasks_to_run:
            # ULTRA-PERFORMANCE: Bulk update status cache before processing tasks
            if all_container_names:
                start_bulk_time = datetime.now(timezone.utc)
                logger.info(f"Direct Cog Periodic Edit Loop: Pre-loading cache for {len(all_container_names)} containers before {len(tasks_to_run)} message edits")
                await self.bulk_update_status_cache(list(all_container_names))
                bulk_time = (datetime.now(timezone.utc) - start_bulk_time).total_seconds() * 1000
                logger.info(f"Direct Cog Periodic Edit Loop: Bulk cache update completed in {bulk_time:.1f}ms")
            
            logger.info(f"Direct Cog Periodic Edit Loop: Attempting to run {len(tasks_to_run)} message edit tasks.")
            
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
                        except:
                            fast_tasks.append(task)  # Default to fast if we can't determine
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
                
            except Exception as e:
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
            # Always update the message update time
            now_utc = datetime.now(timezone.utc)
            if channel_id not in self.last_message_update_time:
                self.last_message_update_time[channel_id] = {}
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
        except Exception as e:
            logger.error(f"Error starting {loop_name} via _start_loop_safely: {e}", exc_info=True)

    async def _start_periodic_message_edit_loop_safely(self):
        await self._start_loop_safely(self.periodic_message_edit_loop, "Periodic Message Edit Loop (Direct Cog)")

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

        except Exception as e:
            logger.error(f"❌ CLEAN SWEEP FAILED for channel {channel.id}: {e}", exc_info=True)
            # Don't raise - clean sweep failure shouldn't stop recovery

    async def send_initial_status_after_delay_and_ready(self, delay_seconds: int):
        """Waits for bot readiness, then delays, then sends initial status."""
        try:
            await self.bot.wait_until_ready()
            logger.info(f"Bot is ready. Waiting {delay_seconds}s before send_initial_status.")
            await asyncio.sleep(delay_seconds)
            logger.info(f"Executing send_initial_status from __init__ after delay.")
            await self.send_initial_status()
        except Exception as e:
            logger.error(f"Error in send_initial_status_after_delay_and_ready: {e}", exc_info=True)

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
        """Send control panel and all server statuses to a channel."""
        try:
            current_config = load_config()
            if not current_config:
                logger.error(f"Send Control Panel: Could not load configuration for channel {channel.id}.")
                return

            logger.info(f"Sending control panel and statuses to channel {channel.name} ({channel.id})")
            
            # Get timezone from config
            timezone_str = current_config.get('timezone_str', 'Europe/Berlin')
            
            # Get current time for footer
            now = datetime.now(timezone.utc)
            current_time = format_datetime_with_timezone(now, timezone_str).split()[1]  # Extract only time part

            # Get all server configurations
            servers = current_config.get('servers', [])
            if not servers:
                logger.warning(f"No servers configured for channel {channel.id}")
                return

            # Send server status messages directly without setup message
            try:
                # Get real status data with timeout
                success_count = 0
                fail_count = 0
                
                for server in servers:  # Send all servers
                    try:
                        result = await asyncio.wait_for(
                            self.status_handlers.send_server_status(
                                channel=channel,
                                server_conf=server,
                                current_config=current_config,
                                allow_toggle=True
                            ),
                            timeout=10.0  # 10 second timeout per server
                        )
                        if result:
                            success_count += 1
                        else:
                            fail_count += 1
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout sending status for {server.get('name', 'unknown')}")
                        fail_count += 1
                    except Exception as e:
                        logger.error(f"Error sending status for {server.get('name', 'unknown')}: {e}")
                        fail_count += 1

                logger.info(f"Finished sending initial statuses to {channel.name}: {success_count} success, {fail_count} failure.")
                
            except Exception as e:
                logger.error(f"Error setting up control panel: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in _send_control_panel_and_statuses: {e}", exc_info=True)

    async def _send_all_server_statuses(self, channel: discord.TextChannel, allow_toggle: bool = True, force_collapse: bool = False):
        """Sends only the overview embed to a status channel (no individual server messages)."""
        try:
            config = load_config()
            if not config:
                logger.error(f"Send All Statuses: Could not load configuration for channel {channel.id}.")
                return
                
            servers = config.get('servers', [])
            if not servers:
                logger.warning(f"No servers configured to send status in channel {channel.name}")
                return

            logger.info(f"Sending overview embed to status channel {channel.name} ({channel.id})")
            
            # Send ONLY the overview embed (status channels don't need individual server messages)
            try:
                servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
                
                ordered_servers = []
                seen_docker_names = set()
                
                # First add servers in the defined order
                for docker_name in self.ordered_server_names:
                    if docker_name in servers_by_name:
                        ordered_servers.append(servers_by_name[docker_name])
                        seen_docker_names.add(docker_name)
                
                # Add any servers that weren't in the ordered list
                for server in servers:
                    docker_name = server.get('docker_name')
                    if docker_name and docker_name not in seen_docker_names:
                        ordered_servers.append(server)
                        seen_docker_names.add(docker_name)
                        
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
                
                # Initialize update time tracking for overview only
                if channel.id not in self.last_message_update_time:
                    self.last_message_update_time[channel.id] = {}
                else:
                    # Clear all previous time tracking except for overview
                    self.last_message_update_time[channel.id].clear()
                    
                self.last_message_update_time[channel.id]["overview"] = datetime.now(timezone.utc)
                
                logger.info(f"✅ Successfully sent overview embed to status channel {channel.name}")
                
            except Exception as e:
                logger.error(f"Error sending overview embed to {channel.name}: {e}", exc_info=True)
            
            # NOTE: Individual server status messages removed for status channels
            # Status channels only show the overview embed with all servers
            
        except Exception as e:
            logger.error(f"Error in _send_all_server_statuses: {e}", exc_info=True)

    async def _regenerate_channel(self, channel: discord.TextChannel, mode: str, config: dict):
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
            await self.delete_bot_messages(channel, limit=300) # Limit adjustable
            await asyncio.sleep(1.0) # Short pause after deleting
            logger.info(f"Finished deleting messages in {channel.name}.")
        except Exception as e_delete:
            logger.error(f"Error deleting messages in {channel.name}: {e_delete}")
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

        except Exception as e_send:
            logger.error(f"❌ Error sending new messages to {channel.name} in mode '{mode}': {e_send}", exc_info=True)
            raise RuntimeError(f"Failed to send new messages during regeneration: {e_send}") from e_send

    async def send_initial_status(self):
        """Sends the initial status messages after a short delay."""
        logger.info("Starting send_initial_status")
        initial_send_successful = False
        try:
            await self.bot.wait_until_ready() # Ensure bot is ready before fetching channels
            
            # Directly update the cache before waiting for loops
            logger.info("Running status update once to populate the cache")
            await self.status_update_loop()
            logger.info("Initial cache update completed")

            # --- Added: 5-second delay ---
            wait_seconds = 5
            logger.info(f"Waiting {wait_seconds} seconds for cache loop to potentially run")
            await asyncio.sleep(wait_seconds)
            logger.info("Wait finished. Proceeding with initial status send")
            # --- End delay ---

            current_config = load_config()
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
                        
                        # Delete old messages
                        try:
                            await self.delete_bot_messages(channel)
                            await asyncio.sleep(1)  # Short pause after deletion
                        except Exception as e:
                            logger.error(f"Error deleting messages in {channel.name}: {e}")
                            
                        # Send new messages
                        if mode == 'control':
                            await self._send_control_panel_and_statuses(channel)
                        else:  # mode == 'status'
                            # Create and send overview embed
                            config = load_config()
                            if not config:
                                logger.error("Could not load config for overview embed")
                                return
                                
                            servers = config.get('servers', [])
                            servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
                            
                            ordered_servers = []
                            seen_docker_names = set()
                            
                            # First add servers in the defined order
                            for docker_name in self.ordered_server_names:
                                if docker_name in servers_by_name:
                                    ordered_servers.append(servers_by_name[docker_name])
                                    seen_docker_names.add(docker_name)
                            
                            # Add any servers that weren't in the ordered list
                            for server in servers:
                                docker_name = server.get('docker_name')
                                if docker_name and docker_name not in seen_docker_names:
                                    ordered_servers.append(server)
                                    seen_docker_names.add(docker_name)
                                    
                            # For initial messages, always start in collapsed state
                            channel_id = channel.id
                            self.mech_expanded_states[channel_id] = False
                            self.mech_state_manager.set_expanded_state(channel_id, False)
                            embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
                            
                            # Create MechView with expand/collapse buttons for mech status
                            from .control_ui import MechView
                            view = MechView(self, channel_id)
                            
                            # Send with animation and button if available
                            if animation_file:
                                logger.info(f"✅ Sending initial message with animation and Mechonate button to {channel.name}")
                                message = await self._send_message_with_files(channel, embed, animation_file, view)
                            else:
                                logger.warning(f"⚠️ Sending initial message WITHOUT animation to {channel.name}")
                                message = await self._send_message_with_files(channel, embed, None, view)
                            
                            # Track the overview message
                            if channel.id not in self.channel_server_message_ids:
                                self.channel_server_message_ids[channel.id] = {}
                            self.channel_server_message_ids[channel.id]["overview"] = message.id
                            
                            # Initialize update time tracking
                            if channel.id not in self.last_message_update_time:
                                self.last_message_update_time[channel.id] = {}
                            self.last_message_update_time[channel.id]["overview"] = datetime.now(timezone.utc)
                            
                            logger.info(f"Tracked overview message {message.id} in status channel {channel.id}")
                            
                        # Set initial channel activity time so inactivity tracking works
                        self.last_channel_activity[channel.id] = datetime.now(timezone.utc)
                        logger.info(f"Set initial channel activity time for {channel.name} ({channel.id})")
                        
                        logger.info(f"Successfully regenerated channel {channel.name}")
                        initial_send_successful = True
                    except discord.NotFound:
                        logger.warning(f"Channel {channel_id} not found")
                    except discord.Forbidden:
                        logger.warning(f"Missing permissions for channel {channel_id}")
                    except Exception as e:
                        logger.error(f"Error processing channel {channel_id}: {e}")
                        
                except Exception as e:
                    logger.error(f"Error processing channel config {channel_id_str}: {e}")

        except Exception as e:
            logger.error(f"Critical error during send_initial_status: {e}", exc_info=True)
        finally:
            self.initial_messages_sent = True
            logger.info(f"send_initial_status finished. Initial messages sent flag set to True. Success: {initial_send_successful}")

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

        except Exception as e:
            logger.error(f"❌ CLEANUP FAILED for channel {channel.name}: {e}", exc_info=True)

    # --- Slash Commands ---
    async def _check_spam_protection(self, ctx: discord.ApplicationContext, command_name: str) -> bool:
        """Check spam protection for a command. Returns True if command can proceed, False if on cooldown."""
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_manager = get_spam_protection_service()
        
        if spam_manager.is_enabled():
            cooldown_seconds = spam_manager.get_command_cooldown(command_name)
            if cooldown_seconds > 0:
                import time
                current_time = time.time()
                cooldown_key = f"cmd_{command_name}_{ctx.author.id}"
                
                # Check if user is on cooldown
                if hasattr(spam_manager, '_command_cooldowns'):
                    last_use = spam_manager._command_cooldowns.get(cooldown_key, 0)
                    if current_time - last_use < cooldown_seconds:
                        remaining = int(cooldown_seconds - (current_time - last_use))
                        try:
                            # Check if we need to use followup (for donate commands that defer)
                            if command_name in ['donate', 'donatebroadcast']:
                                await ctx.followup.send(f"❌ Command on cooldown. Try again in {remaining} seconds.")
                            else:
                                await ctx.respond(f"❌ Command on cooldown. Try again in {remaining} seconds.", ephemeral=True)
                        except Exception:
                            # If response fails, still prevent command execution
                            pass
                        return False
                else:
                    spam_manager._command_cooldowns = {}
                
                # Update cooldown
                spam_manager._command_cooldowns[cooldown_key] = current_time
        
        return True

    @commands.slash_command(name="serverstatus", description=_("Shows the status of all containers"), guild_ids=get_guild_id())
    async def serverstatus(self, ctx: discord.ApplicationContext):
        """Shows an overview of all server statuses in a single message."""
        try:
            # Check spam protection first
            if not await self._check_spam_protection(ctx, "serverstatus"):
                return
                
            # Import translation function locally to ensure it's accessible
            from .translation_manager import _ as translate
            
            # Check if the channel has serverstatus permission
            channel_has_status_perm = _channel_has_permission(ctx.channel.id, 'serverstatus', self.config)
            if not channel_has_status_perm:
                embed = discord.Embed(
                    title=translate("⚠️ Permission Denied"),
                    description=translate("You cannot use this command in this channel."),
                    color=discord.Color.red()
                )
                await ctx.respond(embed=embed, ephemeral=True)
                return

            # Defer the response immediately to prevent timeout
            await ctx.defer()

            config = load_config()
            if not config:
                await ctx.followup.send(_("Error: Could not load configuration."), ephemeral=True)
                return

            # DOCKER CONNECTIVITY CHECK: Check before attempting to get container status
            from services.infrastructure.docker_connectivity_service import get_docker_connectivity_service, DockerConnectivityRequest, DockerErrorEmbedRequest

            connectivity_service = get_docker_connectivity_service()
            connectivity_request = DockerConnectivityRequest(timeout_seconds=5.0)
            connectivity_result = await connectivity_service.check_connectivity(connectivity_request)

            if not connectivity_result.is_connected:
                logger.warning(f"[SERVERSTATUS] Docker connectivity failed: {connectivity_result.error_message}")

                # Create Docker connectivity error embed using service
                lang = config.get('language', 'de')
                embed_request = DockerErrorEmbedRequest(
                    error_message=connectivity_result.error_message,
                    language=lang,
                    context='serverstatus'
                )
                embed_result = connectivity_service.create_error_embed_data(embed_request)

                if not embed_result.success:
                    logger.error(f"Failed to create Docker connectivity error embed: {embed_result.error}")
                    await ctx.followup.send(_("Error creating connectivity status message."), ephemeral=True)
                    return

                # Create Discord embed from service result
                embed = discord.Embed(
                    title=embed_result.title,
                    description=embed_result.description,
                    color=embed_result.color
                )
                embed.set_footer(text=embed_result.footer_text)

                await ctx.followup.send(embed=embed)
                return

            # Get all servers and sort them according to ordered_server_names
            servers = config.get('servers', [])
            servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
            
            ordered_servers = []
            seen_docker_names = set()
            
            # First add servers in the defined order
            for docker_name in self.ordered_server_names:
                if docker_name in servers_by_name:
                    ordered_servers.append(servers_by_name[docker_name])
                    seen_docker_names.add(docker_name)
            
            # Add any servers that weren't in the ordered list
            for server in servers:
                docker_name = server.get('docker_name')
                if docker_name and docker_name not in seen_docker_names:
                    ordered_servers.append(server)
                    seen_docker_names.add(docker_name)
            
            # Determine which embed to create based on mech expansion state
            channel_id = ctx.channel.id
            is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
            
            if is_mech_expanded:
                embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
            else:
                embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
            
            # Create MechView with expand/collapse buttons for mech status
            from .control_ui import MechView
            view = MechView(self, channel_id)
            
            # EDGE CASE: Safely send embed with animation and button
            try:
                if animation_file:
                    # Validate file before sending
                    if hasattr(animation_file, 'fp') and animation_file.fp:
                        message = await ctx.followup.send(embed=embed, file=animation_file, view=view)
                        logger.info("✅ Sent /ss with animation and Mechonate button")
                    else:
                        logger.warning("Animation file invalid, sending without animation")
                        message = await ctx.followup.send(embed=embed, view=view)
                else:
                    logger.warning("No animation file attached, sending embed only")
                    message = await ctx.followup.send(embed=embed, view=view)
            except discord.HTTPException as e:
                logger.error(f"Discord error sending animation: {e}")
                # Fallback: Send without animation but with button
                try:
                    message = await ctx.followup.send(embed=embed, view=view)
                except Exception as fallback_error:
                    logger.error(f"Critical: Could not send embed at all: {fallback_error}")
                    await ctx.followup.send(_("Error generating server status overview."), ephemeral=True)
                    return
            
            # Update tracking information
            now_utc = datetime.now(timezone.utc)
            
            # Update message update time
            if ctx.channel.id not in self.last_message_update_time:
                self.last_message_update_time[ctx.channel.id] = {}
            self.last_message_update_time[ctx.channel.id]["overview"] = now_utc
            
            # Track the message ID
            if ctx.channel.id not in self.channel_server_message_ids:
                self.channel_server_message_ids[ctx.channel.id] = {}
            self.channel_server_message_ids[ctx.channel.id]["overview"] = message.id
            
            # Set last channel activity
            self.last_channel_activity[ctx.channel.id] = now_utc
            
        except Exception as e:
            logger.error(f"Error in serverstatus command: {e}", exc_info=True)
            try:
                await ctx.followup.send(_("An error occurred while generating the overview."), ephemeral=True)
            except Exception as e:
                logger.error(f"Error generating overview: {e}")

    @commands.slash_command(name="ss", description=_("Shortcut: Shows the status of all containers"), guild_ids=get_guild_id())
    async def ss(self, ctx):
        """Shortcut for the serverstatus command."""
        # Directly call serverstatus (it has its own spam protection check)
        await self.serverstatus(ctx)

    # Legacy command methods removed - all container control and info editing
    # is now handled through Discord UI buttons for better user experience
    
    # /info_edit command removed - info editing now handled through UI buttons
    

    # Decorator adjusted
    @commands.slash_command(name="help", description=_("Displays help for available commands"), guild_ids=get_guild_id())
    async def help_command(self, ctx: discord.ApplicationContext):
        # IMMEDIATELY defer to prevent timeout - this MUST be first!
        try:
            await ctx.defer(ephemeral=True)
        except:
            # Interaction already expired - nothing we can do
            return
            
        # Check spam protection after deferring
        if not await self._check_spam_protection(ctx, "help"):
            try:
                await ctx.followup.send(".", delete_after=0.1)
            except:
                pass
            return
        """Displays help information about available commands."""
        embed = discord.Embed(
            title=_("DDC Help & Information"),
            color=discord.Color.blue()
        )
        
        # Tip as first field with spacing
        embed.add_field(name=f"**{_('Tip')}**", value=f"{_('Use /info <servername> to get detailed information about containers with ℹ️ indicators.')}" + "\n\u200b", inline=False)
        
        # General Commands (work everywhere)
        embed.add_field(name=f"**{_('General Commands')}**", value=f"`/help` - {_('Shows this help message.')}\n`/ping` - {_('Checks the bot latency.')}\n`/donate` - {_('Shows donation information to support the project.')}" + "\n\u200b", inline=False)
        
        # Status Channel Commands
        embed.add_field(name=f"**{_('Status Channel Commands')}**", value=f"`/serverstatus` or `/ss` - {_('Displays the status of all configured Docker containers.')}\n`/info <container>` - {_('Shows detailed container information.')}" + "\n\u200b", inline=False)
        
        # Control Channel Commands  
        embed.add_field(name=f"**{_('Control Channel Commands')}**", value=f"`/control` - {_('(Re)generates the main control panel message in channels configured for it.')}\n**Container Control:** {_('Click control buttons under container status panels to start, stop, or restart.')}\n**Task Management:** {_('Click ⏰ button under container control panels to add/delete scheduled tasks.')}" + "\n\u200b", inline=False)
        
        # Add status indicators explanation
        embed.add_field(name=f"**{_('Status Indicators')}**", value=f"🟢 {_('Container is online')}\n🔴 {_('Container is offline')}\n🔄 {_('Container status loading')}" + "\n\u200b", inline=False)
        
        # Add info system explanation  
        embed.add_field(name=f"**{_('Info System')}**", value=f"ℹ️ {_('Click for container details')}\n🔒 {_('Protected info (control channels only)')}\n🔓 {_('Public info available')}" + "\n\u200b", inline=False)
        
        # Add task management explanation
        embed.add_field(name=f"**{_('Task Scheduling')}**", value=f"⏰ {_('Click to manage scheduled tasks')}\n➕ **Add Task** - {_('Schedule container actions (daily, weekly, monthly, yearly, once)')}\n❌ **Delete Tasks** - {_('Remove scheduled tasks for the container')}" + "\n\u200b", inline=False)
        
        # Add control buttons explanation (no spacing after last field)
        embed.add_field(name=f"**{_('Control Buttons (Admin Channels)')}**", value=f"📝 {_('Edit container info text')}\n📋 {_('View container logs')}", inline=False)
        embed.set_footer(text="https://ddc.bot")

        try:
            await ctx.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send help message: {e}")
            # Fallback - try to send minimal message
            try:
                await ctx.followup.send(_("Help information is temporarily unavailable."), ephemeral=True)
            except:
                pass

    @commands.slash_command(name="ping", description=_("Shows the bot's latency"), guild_ids=get_guild_id())
    async def ping_command(self, ctx: discord.ApplicationContext):
        # Check spam protection first
        if not await self._check_spam_protection(ctx, "ping"):
            return
        latency = round(self.bot.latency * 1000)
        ping_message = _("Pong! Latency: {latency:.2f} ms").format(latency=latency)
        embed = discord.Embed(title="🏓", description=ping_message, color=discord.Color.blurple())
        await ctx.respond(embed=embed)
    
    @commands.slash_command(name="donate", description="Show donation information to support the project", guild_ids=get_guild_id())
    async def donate_command(self, ctx: discord.ApplicationContext):
        """Show donation links to support DockerDiscordControl development."""
        # IMMEDIATELY defer to prevent timeout - this MUST be first!
        try:
            await ctx.defer(ephemeral=True)
        except:
            # Interaction already expired - nothing we can do
            return
        
        # NOW check if donations are disabled
        try:
            from services.donation.donation_utils import is_donations_disabled
            if is_donations_disabled():
                # Send minimal response via followup since we deferred
                try:
                    await ctx.followup.send(".", delete_after=0.1)
                except Exception as e:
                    logger.debug(f"Followup cleanup failed: {e}")
                return
        except Exception as e:
            logger.debug(f"Donation check failed: {e}")
        
        # Check spam protection
        if not await self._check_spam_protection(ctx, "donate"):
            return
            
        try:
            # Donations enabled - show normal donation UI
            # Check MechService availability
            mech_service_available = False
            try:
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                mech_service_available = True
            except:
                pass
            
            # Create donation embed
            embed = discord.Embed(
                title=_('Support DockerDiscordControl'),
                description=_(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41
            )
            embed.add_field(
                name=_('Choose your preferred method:'),
                value=_('Click one of the buttons below to support DDC development'),
                inline=False
            )
            embed.set_footer(text="https://ddc.bot")
            
            # Send with or without view (use followup since we deferred)
            try:
                view = DonationView(mech_service_available, bot=self.bot)
                message = await ctx.followup.send(embed=embed, view=view)
                # Update view with message reference and start auto-delete timer
                view.message = message
                view.auto_delete_task = asyncio.create_task(view.start_auto_delete_timer())
            except:
                await ctx.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in donate command: {e}", exc_info=True)

    async def _handle_donate_interaction(self, interaction: discord.Interaction):
        """Handle donation button interactions from mech UI."""
        # This should never be called when donations are disabled
        # (buttons shouldn't exist) but check anyway for safety
        try:
            from services.donation.donation_utils import is_donations_disabled
            if is_donations_disabled():
                # Silently ignore
                return
        except:
            pass
            
        try:
            # Immediately defer to prevent interaction expiry
            await interaction.response.defer(ephemeral=True)
            
            # Donations enabled - show normal donation UI
            
            # Check MechService availability
            mech_service_available = False
            try:
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                mech_service_available = True
            except:
                pass
            
            # Create donation embed
            embed = discord.Embed(
                title=_('Support DockerDiscordControl'),
                description=_(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41
            )
            embed.add_field(
                name=_('Choose your preferred method:'),
                value=_('Click one of the buttons below to support DDC development'),
                inline=False
            )
            embed.set_footer(text="https://ddc.bot")
            
            # Send with or without view
            try:
                view = DonationView(mech_service_available, bot=self.bot)
                # Note: Ephemeral messages don't need auto-delete as they're private
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            except:
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except discord.NotFound:
            # Interaction expired - silently ignore
            pass
        except Exception as e:
            # Only log unexpected errors, not Discord timing issues
            if "Unknown interaction" not in str(e):
                logger.error(f"Unexpected error in donate interaction: {e}", exc_info=True)

    @commands.slash_command(name="info", description=_("Show container information"), guild_ids=get_guild_id())
    async def info_command(self, ctx: discord.ApplicationContext,
                           container_name: str = discord.Option(description=_("The Docker container name"), autocomplete=container_select)):
        """Shows container information with appropriate buttons based on channel permissions."""
        # Log command invocation for debugging with unique tracking
        import time
        import uuid
        call_id = str(uuid.uuid4())[:8]
        timestamp = time.time()
        logger.info(f"INFO COMMAND INVOKED: call_id={call_id}, container={container_name}, user={ctx.author.id}, channel={ctx.channel_id}, interaction_id={ctx.interaction.id if hasattr(ctx, 'interaction') else 'unknown'}, timestamp={timestamp}")
        
        try:
            # Check spam protection first
            if not await self._check_spam_protection(ctx, "info"):
                return
                
            # Try to defer immediately, but handle timeout gracefully
            deferred = False
            try:
                if not ctx.response.is_done():
                    await ctx.response.defer(ephemeral=True)
                    deferred = True
                    logger.debug(f"Successfully deferred /info command for {container_name}")
                else:
                    logger.debug(f"Interaction response already done for /info command, will use followup")
                    deferred = True  # We'll use followup
            except discord.errors.NotFound:
                # Interaction already timed out, but we can still try to respond
                logger.debug(f"Interaction already timed out for /info command, attempting direct response")
                deferred = False
            except Exception as e:
                logger.warning(f"Failed to defer /info command: {e}")
                deferred = False
            
            # Check if this channel has 'info' permission
            from .control_helpers import _channel_has_permission
            config = self.config
            has_info_permission = _channel_has_permission(ctx.channel_id, 'info', config) if config else False
            
            if not has_info_permission:
                if deferred:
                    await ctx.followup.send(_("You do not have permission to use the info command in this channel."), ephemeral=True)
                else:
                    await ctx.respond(_("You do not have permission to use the info command in this channel."), ephemeral=True)
                return
            
            # Check if container exists in config
            servers = config.get('servers', [])
            server_config = next((s for s in servers if s.get('docker_name') == container_name), None)
            if not server_config:
                if deferred:
                    await ctx.followup.send(_("Container '{container}' not found in configuration.").format(container=container_name), ephemeral=True)
                else:
                    await ctx.respond(_("Container '{container}' not found in configuration.").format(container=container_name), ephemeral=True)
                return
            
            # Load container info to check if info is enabled
            from services.infrastructure.container_info_service import get_container_info_service
            info_service = get_container_info_service()
            info_result = info_service.get_container_info(container_name)
            
            # More robust checking with better error handling
            if not info_result.success:
                logger.warning(f"Failed to load container info for {container_name}: {info_result.error if hasattr(info_result, 'error') else 'Unknown error'}")
                if deferred:
                    await ctx.followup.send(_("Could not load container information for '{container}'.").format(container=container_name), ephemeral=True)
                else:
                    await ctx.respond(_("Could not load container information for '{container}'.").format(container=container_name), ephemeral=True)
                return
            
            if not info_result.data:
                logger.warning(f"No container info data found for {container_name}")
                if deferred:
                    await ctx.followup.send(_("Container information is not configured for '{container}'.").format(container=container_name), ephemeral=True)
                else:
                    await ctx.respond(_("Container information is not configured for '{container}'.").format(container=container_name), ephemeral=True)
                return
                
            # Debug the enabled flag
            enabled_value = info_result.data.enabled
            logger.info(f"DEBUG INFO COMMAND: {call_id} - Container {container_name} enabled value: {enabled_value} (type: {type(enabled_value)})")
            
            if not enabled_value:
                logger.info(f"Container info is disabled for {container_name} - call_id: {call_id}")
                if deferred:
                    await ctx.followup.send(_("Container information is not enabled for '{container}'.").format(container=container_name), ephemeral=True)
                else:
                    await ctx.respond(_("Container information is not enabled for '{container}'.").format(container=container_name), ephemeral=True)
                return
            
            # Convert ContainerInfo to dict for compatibility
            info_config = info_result.data.to_dict()
            
            # Check if this is a control channel
            has_control = _channel_has_permission(ctx.channel_id, 'control', config) if config else False
            
            # Generate info embed using the same logic as StatusInfoButton
            from .status_info_integration import StatusInfoButton
            info_button = StatusInfoButton(self, server_config, info_config)
            embed = await info_button._generate_info_embed(include_protected=has_control)
            
            # Create view with appropriate buttons based on channel type
            view = None
            if has_control:
                # Control channel: Show admin buttons (Edit Info, Protected Info Edit, Debug)
                from .status_info_integration import ContainerInfoAdminView
                view = ContainerInfoAdminView(self, server_config, info_config)
            else:
                # Status channel: Show protected info button if enabled
                if info_config.get('protected_enabled', False):
                    from .status_info_integration import ProtectedInfoOnlyView
                    view = ProtectedInfoOnlyView(self, server_config, info_config)
            
            # Send response - check for race condition with autocomplete first
            try:
                # Check if interaction has already been acknowledged (race condition with autocomplete)
                if ctx.interaction.response.is_done():
                    logger.warning(f"Interaction already acknowledged for /info {container_name} - call_id: {call_id}. Using followup instead.")
                    if view:
                        await ctx.followup.send(embed=embed, view=view, ephemeral=True)
                    else:
                        await ctx.followup.send(embed=embed, ephemeral=True)
                elif deferred:
                    logger.debug(f"Sending followup response for /info {container_name}")
                    if view:
                        await ctx.followup.send(embed=embed, view=view, ephemeral=True)
                    else:
                        await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    logger.debug(f"Sending direct response for /info {container_name}")
                    if view:
                        await ctx.respond(embed=embed, view=view, ephemeral=True)
                    else:
                        await ctx.respond(embed=embed, ephemeral=True)
            except discord.errors.NotFound:
                logger.warning(f"Interaction expired for /info {container_name}, cannot send response")
                return
            except discord.errors.HTTPException as e:
                logger.error(f"HTTP error sending /info response for {container_name}: {e}")
                return
            
            logger.info(f"INFO COMMAND COMPLETED: call_id={call_id}, container={container_name}, user={ctx.author.id}, channel={ctx.channel_id}, info={has_info_permission}, control={has_control}, deferred={deferred}, timestamp={time.time()}")
            return  # Important: Return here to prevent fall-through to error handling
            
        except Exception as e:
            logger.error(f"Error in info command for {container_name}: {e}", exc_info=True)
            # Try to send error message if possible
            try:
                if 'deferred' in locals() and deferred:
                    await ctx.followup.send(_("An error occurred while retrieving container information."), ephemeral=True)
                else:
                    await ctx.respond(_("An error occurred while retrieving container information."), ephemeral=True)
            except:
                pass  # If we can't send error message, just log it

    # NOTE: Old _create_overview_embed method was removed
    # Use _create_overview_embed_expanded or _create_overview_embed_collapsed instead

    async def _create_overview_embed_expanded(self, ordered_servers, config):
        """Creates the server overview embed with EXPANDED mech status details.
        
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
            display_name = server_conf.get('name', server_conf.get('docker_name'))
            docker_name = server_conf.get('docker_name')
            if not display_name or not docker_name:
                continue
                
            # Use cached data only (same as original)
            cached_entry = self.status_cache.get(display_name)
            status_result = None
            
            if cached_entry and cached_entry.get('data'):
                import os
                max_cache_age = int(os.environ.get('DDC_DOCKER_MAX_CACHE_AGE', '300'))
                
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
            except Exception as e:
                logger.debug(f"Could not check info status for {docker_name}: {e}")
            
            # Process status result (same as original)
            if status_result and isinstance(status_result, tuple) and len(status_result) == 6:
                _, is_running, _, _, _, _ = status_result
                
                # Determine status icon (same logic as original)
                if display_name in self.pending_actions:
                    pending_timestamp = self.pending_actions[display_name]['timestamp']
                    pending_duration = (now_utc - pending_timestamp).total_seconds()
                    if pending_duration < 120:
                        status_emoji = "🟡"
                        status_text = translate("Pending")
                    else:
                        del self.pending_actions[display_name]
                        status_emoji = "🟢" if is_running else "🔴"
                else:
                    status_emoji = "🟢" if is_running else "🔴"
                
                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                # Add status line with proper spacing and info indicator (match original format)
                line = f"│ {status_emoji} {truncated_name}{info_indicator}"
                content_lines.append(line)
            else:
                # No cache data available - show loading status
                status_emoji = "🔄"
                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                line = f"│ {status_emoji} {truncated_name}{info_indicator}"
                content_lines.append(line)
        
        # Close server status box
        content_lines.append("└───────────────────────────")
        
        # Combine all lines into the description
        embed.description = "```\n" + "\n".join(content_lines) + "\n```"
        
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
        except Exception as e:
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
                import os
                # Add project root to Python path for service imports
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                # SERVICE FIRST: Use MechStatusCacheService for instant response
                from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
                cache_service = get_mech_status_cache_service()
                cache_request = MechStatusCacheRequest(include_decimals=True)
                mech_cache_result = cache_service.get_cached_status(cache_request)

                if not mech_cache_result.success:
                    logger.error(f"Failed to get cached mech status: {mech_cache_result.error_message}")
                    return

                logger.info(f"CACHE: Using cached mech data (age: {mech_cache_result.cache_age_seconds:.1f}s)")

                # Get clean data from CACHED result
                current_Power = mech_cache_result.power  # Already includes decimals from request
                total_donations_received = mech_cache_result.total_donated
                logger.info(f"CACHE: Power=${current_Power:.2f}, total_donations=${total_donations_received}, level={mech_cache_result.level} ({mech_cache_result.name})")

                # Evolution info from cached service with next_name for UI
                from services.mech.mech_service import MECH_LEVELS
                next_name = None
                if mech_cache_result.threshold is not None and mech_cache_result.threshold > 0:
                    # For Level 10 ONLY: use corrupted name (Level 11 should have no next_name)
                    if mech_cache_result.level == 10:
                        next_name = "ERR#R: [DATA_C0RR*PTED]"
                    elif mech_cache_result.level < 10:
                        # Find next level name from MECH_LEVELS for normal levels (1-9)
                        for level_info in MECH_LEVELS:
                            if level_info.threshold == mech_cache_result.threshold:
                                next_name = level_info.name
                                break
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
                    from services.mech.mech_animation_service import get_mech_animation_service
                    mech_service = get_mech_animation_service()
                    # Use CACHED data for animation
                    animation_file = await mech_service.create_collapsed_status_animation_async(
                        current_Power, total_donations_received
                    )
                except Exception as e:
                    logger.warning(f"Animation service failed (graceful degradation): {e}")
                    animation_file = None
                    # Add fallback visual indicator in embed
                    if not embed.footer or not embed.footer.text:
                        embed.set_footer(text="🎬 Animation service temporarily unavailable")
                    else:
                        embed.set_footer(text=f"{embed.footer.text} | 🎬 Animation unavailable")

                # Use clean progress bar data from CACHE - NO MORE MANUAL CALCULATION! 🎯
                # For Level 1, use decimal Power for accurate percentage
                if mech_cache_result.level == 1:
                    Power_current = current_Power  # Use decimal value for Level 1
                else:
                    Power_current = mech_cache_result.bars.Power_current  # Use integer for Level 2+
                Power_max = mech_cache_result.bars.Power_max_for_level
                evolution_current = mech_cache_result.bars.mech_progress_current
                evolution_max = mech_cache_result.bars.mech_progress_max

                logger.info(f"CACHE BARS: Power={Power_current}/{Power_max}, evolution={evolution_current}/{evolution_max}")
                
                # Calculate percentages from clean data
                if Power_max > 0:
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

                # Get level-specific decay rate
                from services.mech.evolution_config_manager import get_evolution_config_manager
                config_mgr = get_evolution_config_manager()
                evolution_info = config_mgr.get_evolution_level(mech_cache_result.level)
                decay_per_day = evolution_info.decay_per_day if evolution_info else 1.0

                Power_consumption_text = translate("Power Consumption")
                if decay_per_day == 0:
                    mech_status += f"{Power_consumption_text}: ⚡ {translate('No decay')}\n\n"
                else:
                    per_day_suffix = translate("per_day_suffix")
                    mech_status += f"{Power_consumption_text}: 🔻 {decay_per_day}{per_day_suffix}\n\n"

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
                    
            except Exception as e:
                logger.error(f"Could not load expanded mech status for /ss: {e}", exc_info=True)
        else:
            # Donations disabled - no mech components
            animation_files = None
            logger.info("Donations disabled - skipping mech status for /ss")

        # Add website URL as footer for better spacing
        embed.set_footer(text="https://ddc.bot")

        # Return tuple (embed, animation_file) - single file for expanded view
        return embed, animation_file

    async def _create_overview_embed_collapsed(self, ordered_servers, config):
        """Creates the server overview embed with COLLAPSED mech status (animation only).
        
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

        # Add server statuses (copy from original method - same logic)
        for server_conf in ordered_servers:
            display_name = server_conf.get('name', server_conf.get('docker_name'))
            docker_name = server_conf.get('docker_name')
            if not display_name or not docker_name:
                continue
                
            # Use cached data only (same as original)
            cached_entry = self.status_cache.get(display_name)
            status_result = None
            
            if cached_entry and cached_entry.get('data'):
                import os
                max_cache_age = int(os.environ.get('DDC_DOCKER_MAX_CACHE_AGE', '300'))
                
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
            except Exception as e:
                logger.debug(f"Could not check info status for {docker_name}: {e}")
            
            # Process status result (same as original)
            if status_result and isinstance(status_result, tuple) and len(status_result) == 6:
                _, is_running, _, _, _, _ = status_result
                
                # Determine status icon (same logic as original)
                if display_name in self.pending_actions:
                    pending_timestamp = self.pending_actions[display_name]['timestamp']
                    pending_duration = (now_utc - pending_timestamp).total_seconds()
                    if pending_duration < 120:
                        status_emoji = "🟡"
                        status_text = translate("Pending")
                    else:
                        del self.pending_actions[display_name]
                        status_emoji = "🟢" if is_running else "🔴"
                else:
                    status_emoji = "🟢" if is_running else "🔴"
                
                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                # Add status line with proper spacing and info indicator (match original format)
                line = f"│ {status_emoji} {truncated_name}{info_indicator}"
                content_lines.append(line)
            else:
                # No cache data available - show loading status
                status_emoji = "🔄"
                # Truncate display name for mobile (max 20 chars)
                truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name
                line = f"│ {status_emoji} {truncated_name}{info_indicator}"
                content_lines.append(line)
        
        # Close server status box
        content_lines.append("└───────────────────────────")
        
        # Combine all lines into the description
        embed.description = "```\n" + "\n".join(content_lines) + "\n```"
        
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
        except Exception as e:
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
                import os
                # Add project root to Python path for service imports
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                # SERVICE FIRST: Use MechStatusCacheService for instant response
                from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
                cache_service = get_mech_status_cache_service()
                cache_request = MechStatusCacheRequest(include_decimals=True)
                mech_cache_result = cache_service.get_cached_status(cache_request)

                if not mech_cache_result.success:
                    logger.error(f"Failed to get cached mech status for animation: {mech_cache_result.error_message}")
                    return

                current_Power = mech_cache_result.power
                logger.info(f"CACHE (collapsed): Using cached power data: {current_Power} (age: {mech_cache_result.cache_age_seconds:.1f}s)")
                
                # Create mech animation with fallback
                try:
                    from services.mech.mech_animation_service import get_mech_animation_service
                    mech_service = get_mech_animation_service()
                    # Use CACHED data for animation
                    total_donated = mech_cache_result.total_donated
                    animation_file = await mech_service.create_collapsed_status_animation_async(
                        current_Power, total_donated
                    )
                except Exception as e:
                    logger.warning(f"Animation service failed (graceful degradation): {e}")
                    animation_file = None
                    # Add fallback visual indicator in embed
                    if not embed.footer or not embed.footer.text:
                        embed.set_footer(text="🎬 Animation service temporarily unavailable")
                    else:
                        embed.set_footer(text=f"{embed.footer.text} | 🎬 Animation unavailable")

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
                
            except Exception as e:
                logger.error(f"Could not load collapsed mech status for /ss: {e}", exc_info=True)
        else:
            # Donations disabled - no mech components
            animation_files = None
            logger.info("Donations disabled - skipping collapsed mech status for /ss")

        # Add website URL as footer for better spacing
        embed.set_footer(text="https://ddc.bot")

        # Return tuple (embed, animation_file) - single file for collapsed view
        return embed, animation_file

    def _create_progress_bar(self, percentage: float, length: int = 30) -> str:
        """Create a text progress bar with consistent character widths for monospace."""
        filled = int((percentage / 100) * length)
        empty = length - filled
        # Use █ and ░ - these work best in monospace code blocks
        bar = "█" * filled + "░" * empty
        return bar

    async def _send_message_with_files(self, target, embed, file, view=None):
        """Helper to send messages with either single file or no files."""
        if file:
            # WEBP EMBEDDING SUCCESS: Use combined method (embed + file in same message)
            # The fix was preserving .webp extension instead of forcing .gif
            logger.debug(f"Sending combined message with WebP animation: {file.filename}")

            # Combined method (single message with embed + file)
            if view:
                return await target.send(embed=embed, file=file, view=view)
            else:
                return await target.send(embed=embed, file=file)
        else:
            # No files
            if view:
                return await target.send(embed=embed, view=view)
            else:
                return await target.send(embed=embed)

    async def _handle_donate_interaction(self, interaction):
        """Handle Mechonate button interaction - shows donation options."""
        try:
            
            # Check if MechService is available
            try:
                from services.mech.mech_service import get_mech_service
                # Test if we can get the service
                mech_service = get_mech_service()
                mech_service_available = True
                logger.info("MechService is available for donations")
            except Exception as e:
                mech_service_available = False
                logger.warning(f"MechService not available: {e}")
            
            # Check if donations are disabled by premium key (now use config service)
            try:
                from services.config.config_service import get_config_service
                config_service = get_config_service()
                config = config_service.get_config()
                donations_disabled = bool(config.get('donation_disable_key'))
            except:
                donations_disabled = False
                
            if donations_disabled:
                embed = discord.Embed(
                    title="🔐 Premium Features Active",
                    description="Donations are disabled via premium key. Thank you for supporting DDC!",
                    color=0xFFD700  # Gold color
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Create donation embed (same as /donate command)
            embed = discord.Embed(
                title=_('Support DockerDiscordControl'),
                description=_(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41
            )
            embed.add_field(
                name=_('Choose your preferred method:'),
                value=_('Click one of the buttons below to support DDC development'),
                inline=False
            )
            embed.set_footer(text="https://ddc.bot")
            
            # Create view with donation buttons
            try:
                view = DonationView(mech_service_available, bot=self.bot)
                # Note: Ephemeral messages don't need auto-delete as they're private
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                logger.info(f"Mechonate button used by user {interaction.user.name} ({interaction.user.id})")
            except Exception as view_error:
                logger.error(f"Error creating DonationView: {view_error}")
                # Fallback without view
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in _handle_donate_interaction: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ Error",
                    description=_("An error occurred while showing donation information. Please try again later."),
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except:
                # If we can't respond, it means the interaction was already responded to
                pass

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
                            
                        servers = config.get('servers', [])
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
                            else:
                                current_glvl = 0
                        except Exception as e:
                            logger.debug(f"Could not get current Glvl: {e}")
                        
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
                        if (glvl_changed or power_depleted) and not force_recreate:
                            # Check rate limit before allowing force_recreate
                            if self.mech_state_manager.should_force_recreate(channel_id):
                                force_recreate = True
                                self.mech_state_manager.mark_force_recreate(channel_id)
                                from .translation_manager import _
                                if power_depleted:
                                    upgrade_text = _("Upgrading to force_recreate=True due to power depletion (offline mech)")
                                else:
                                    upgrade_text = _("Upgrading to force_recreate=True due to significant Glvl change")
                                logger.info(f"{upgrade_text}")
                            else:
                                logger.debug(f"Rate limited force_recreate for channel {channel_id} (Glvl change or power depletion)")
                                force_recreate = False
                        
                        # Create updated embed based on expansion state
                        is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
                        logger.info(f"AUTO-UPDATE: Channel {channel_id} is_expanded={is_mech_expanded}, force_recreate={force_recreate}")
                        if is_mech_expanded:
                            logger.info(f"AUTO-UPDATE: Creating expanded embed for channel {channel_id}")
                            embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
                        else:
                            logger.info(f"AUTO-UPDATE: Creating collapsed embed for channel {channel_id}")
                            embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
                        
                        if force_recreate:
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
                            logger.info(f"🔄 AUTO-UPDATE: Successfully recreated /ss message in {channel.name} with new animation")
                        else:
                            # Just edit the embed (for expand/collapse - no new animation)
                            from .control_ui import MechView
                            view = MechView(self, channel_id)
                            await message.edit(embed=embed, view=view)
                            logger.info(f"✏️ AUTO-UPDATE: Successfully edited /ss message in {channel.name}")
                        
                        updated_count += 1
                        
                    except Exception as e:
                        logger.error(f"AUTO-UPDATE ERROR: Could not update /ss message in channel {channel_id}: {e}", exc_info=True)
            
            if updated_count > 0:
                logger.info(f"✅ Auto-updated {updated_count} /ss messages after donation")
            else:
                logger.debug("No /ss messages found to update")
                
        except Exception as e:
            logger.error(f"Error in _auto_update_ss_messages: {e}")
    
    async def _edit_only_ss_messages(self, reason: str):
        """Edit-only update for /ss messages (used for expand/collapse)"""
        await self._auto_update_ss_messages(reason, force_recreate=False)

    # --- Heartbeat Loop ---
    @tasks.loop(minutes=1)
    async def heartbeat_send_loop(self):
        """[BETA] Sends a heartbeat signal if enabled in config.
        
        This feature is in BETA and allows the bot to send periodic heartbeat messages
        to a specified Discord channel. These messages can be monitored by an external
        script to check if the bot is still operational.
        
        The heartbeat configuration is loaded from the bot's config and can be configured
        through the web UI.
        """
        try:
            # Load the heartbeat configuration from latest cache (fallback to initial config)
            current_config = load_config() or self.config or {}

            # First check legacy format with 'heartbeat_channel_id' at root level
            heartbeat_channel_id = current_config.get('heartbeat_channel_id')

            # Initialize heartbeat config with defaults
            heartbeat_config = {
                'enabled': bool(str(heartbeat_channel_id).isdigit()) if heartbeat_channel_id is not None else False,
                'method': 'channel',
                'interval': 60,
                'channel_id': heartbeat_channel_id
            }

            # Override with nested config if it exists (new format)
            if 'heartbeat' in current_config:
                nested_config = current_config.get('heartbeat', {})
                if isinstance(nested_config, dict):
                    heartbeat_config.update(nested_config)
            
            # Check if heartbeat is enabled
            if not heartbeat_config.get('enabled', False):
                logger.debug("Heartbeat monitoring disabled in config.")
                return
    
            # Get the heartbeat method and interval
            method = heartbeat_config.get('method', 'channel')
            try:
                interval_minutes = int(heartbeat_config.get('interval', 60))
            except (ValueError, TypeError):
                logger.warning(f"Invalid heartbeat interval, using default 60 minutes")
                interval_minutes = 60
    
            # Dynamically change interval if needed
            if self.heartbeat_send_loop.minutes != interval_minutes:
                try:
                    self.heartbeat_send_loop.change_interval(minutes=interval_minutes)
                    logger.info(f"[BETA] Heartbeat interval updated to {interval_minutes} minutes.")
                except Exception as e:
                    logger.error(f"[BETA] Failed to update heartbeat interval: {e}")
    
            logger.debug("[BETA] Heartbeat loop running.")
            
            # Handle different heartbeat methods
            if method == 'channel':
                # Get the channel ID from either nested config or root config
                channel_id_str = heartbeat_config.get('channel_id') or heartbeat_channel_id
                
                if not channel_id_str:
                    logger.error("[BETA] Heartbeat method is 'channel' but no channel_id is configured.")
                    return
                    
                if not str(channel_id_str).isdigit():
                    logger.error(f"[BETA] Heartbeat channel ID '{channel_id_str}' is not a valid numeric ID.")
                    return
                
                channel_id = int(channel_id_str)
                try:
                    # Fetch the channel
                    channel = await self.bot.fetch_channel(channel_id)
                    
                    if not isinstance(channel, discord.TextChannel):
                        logger.warning(f"[BETA] Heartbeat channel ID {channel_id} is not a text channel.")
                        return
                        
                    # Send the heartbeat message with timestamp
                    timestamp = datetime.now(timezone.utc).isoformat()
                    await channel.send(_("❤️ Heartbeat signal at {timestamp}").format(timestamp=timestamp))
                    logger.info(f"[BETA] Heartbeat sent to channel {channel_id}.")
                    
                except discord.NotFound:
                    logger.error(f"[BETA] Heartbeat channel ID {channel_id} not found. Please check your configuration.")
                except discord.Forbidden:
                    logger.error(f"[BETA] Missing permissions to send heartbeat message to channel {channel_id}.")
                except discord.HTTPException as http_err:
                    logger.error(f"[BETA] HTTP error sending heartbeat to channel {channel_id}: {http_err}")
                except Exception as e:
                    logger.error(f"[BETA] Error sending heartbeat to channel {channel_id}: {e}")
            elif method == 'api':
                # API method is not implemented yet
                logger.warning("[BETA] API heartbeat method is not yet implemented.")
            else:
                logger.warning(f"[BETA] Unknown heartbeat method specified in config: '{method}'. Supported methods: 'channel'")
        except Exception as e:
            logger.error(f"[BETA] Error in heartbeat_send_loop: {e}", exc_info=True)

    @heartbeat_send_loop.before_loop
    async def before_heartbeat_loop(self):
       """Wait until the bot is ready before starting the heartbeat loop."""
       await self.bot.wait_until_ready()
       logger.info("[BETA] Heartbeat monitoring loop is ready to start.")

    # --- Status Cache Update Loop ---
    @tasks.loop(seconds=30)
    async def status_update_loop(self):
        """Periodically updates the cache with the latest container statuses."""
        # Load configuration first
        config = load_config()
        if not config:
            logger.error("Status Update Loop: Could not load configuration. Skipping cycle.")
            return
        
        # Get cache duration from environment
        cache_duration = int(os.environ.get('DDC_DOCKER_CACHE_DURATION', '30'))
        
        # Update cache TTL based on current interval
        calculated_ttl = int(cache_duration * 2.5)
        if self.cache_ttl_seconds != calculated_ttl:
            self.cache_ttl_seconds = calculated_ttl
            logger.info(f"[STATUS_LOOP] Cache TTL updated to {calculated_ttl} seconds (interval: {cache_duration}s)")
        
        # Dynamically change the loop interval if needed
        if self.status_update_loop.seconds != cache_duration:
            try:
                self.status_update_loop.change_interval(seconds=cache_duration)
                logger.info(f"[STATUS_LOOP] Cache update interval changed to {cache_duration} seconds")
            except Exception as e:
                logger.error(f"[STATUS_LOOP] Failed to change interval: {e}")
        
        # Configuration already loaded and validated above
        servers = config.get('servers', [])
        if not servers:
            return # No servers to update
            
        container_names = [s.get('docker_name') for s in servers if s.get('docker_name')]
            
        logger.info(f"[STATUS_LOOP] Bulk updating cache for {len(container_names)} containers")
        start_time = time.time()
            
        try:
            # This function now guarantees a dict with 3-element tuples as values
            results = await self.bulk_fetch_container_status(container_names)
            
            success_count = 0
            error_count = 0
            
            # This loop is now safe and will not cause a ValueError
            for name, (status, data, error) in results.items():
                if status == 'success':
                    self.status_cache[name] = {
                        'data': data,
                        'timestamp': datetime.now(timezone.utc)
                    }
                    success_count += 1
                else:
                    logger.warning(f"[STATUS_LOOP] Failed to fetch status for {name}. Error: {error}")
                    error_count += 1
            
            duration_ms = (time.time() - start_time) * 1000
            logger.info(f"[STATUS_LOOP] Cache updated: {success_count} success, {error_count} errors in {duration_ms:.1f}ms")
                
        except Exception as e:
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
        except Exception as e:
            logger.error(f"Failed to start MechStatusCacheService background loop: {e}", exc_info=True)

    @start_mech_cache_loop.before_loop
    async def before_start_mech_cache_loop(self):
        """Wait until the bot is ready before starting the mech cache."""
        await self.bot.wait_until_ready()

    # --- Animation Cache Maintenance Loop ---
    @tasks.loop(count=1)  # Only run once to start the background maintenance loop
    async def start_animation_maintenance_loop(self):
        """Start the Animation Cache Maintenance background loop (4-hour intervals)."""
        try:
            from services.mech.animation_cache_service import get_animation_cache_service
            animation_cache = get_animation_cache_service()

            logger.info("Starting Animation Cache Maintenance background loop...")
            await animation_cache.start_maintenance_loop()
            logger.info("Animation Cache Maintenance background loop started successfully")
        except Exception as e:
            logger.error(f"Failed to start Animation Cache Maintenance background loop: {e}", exc_info=True)

    @start_animation_maintenance_loop.before_loop
    async def before_start_animation_maintenance_loop(self):
        """Wait until the bot is ready before starting the animation maintenance."""
        await self.bot.wait_until_ready()

    # --- Inactivity Check Loop ---
    @tasks.loop(seconds=30)
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
                        if history[0].author.id == self.bot.user.id:
                            # If the last message is from our bot, we should not regenerate
                            # Reset the timer instead, since the bot was the last to post
                            self.last_channel_activity[channel_id] = now_utc
                            logger.debug(f"Last message in channel {channel.name} ({channel_id}) is from the bot, resetting inactivity timer")
                            continue
                            
                        # The last message is not from our bot, regenerate
                        logger.info(f"Last message in channel {channel.name} is NOT from our bot. Will regenerate")
                        
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

                        # Attempt channel regeneration with improved error handling
                        try:
                            logger.info(f"Starting inactivity regeneration for {channel.name} ({channel_id}) in mode '{regeneration_mode}'")
                            await self._regenerate_channel(channel, regeneration_mode, config)

                            # Reset activity timer only on successful regeneration
                            self.last_channel_activity[channel_id] = now_utc
                            logger.info(f"✅ Channel {channel.name} ({channel_id}) successfully regenerated due to inactivity. Mode: {regeneration_mode}")

                        except Exception as regen_error:
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
                    except Exception as e:
                        logger.error(f"Error during inactivity check for channel {channel_id}: {e}", exc_info=True)
                else:
                    logger.debug(f"Channel {channel_id} - Inactivity threshold not reached yet")
        except Exception as e:
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
            
        except Exception as e:
            logger.error(f"Error in performance_cache_clear_loop: {e}", exc_info=True)

    @performance_cache_clear_loop.before_loop
    async def before_performance_cache_clear_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()
    
    # Member count updates moved to on-demand during level-ups only

    # --- Final Control Command ---
    @commands.slash_command(name="control", description=_("Displays the control panel in the control channel"), guild_ids=get_guild_id())
    async def control_command(self, ctx: discord.ApplicationContext):
        """(Re)generates the control panel message in the current channel if permitted."""
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
        except Exception as e_followup:
            logger.error(f"Error sending initial followup for /control command: {e_followup}")

        # Run regeneration directly instead of as background task for better user experience
        try:
            await self._regenerate_channel(ctx.channel, 'control', self.config)
            logger.info(f"Control panel regeneration completed for channel {ctx.channel.name}")
            # Send success confirmation
            try:
                await ctx.followup.send(_("✅ Control panel regenerated successfully!"), ephemeral=True)
            except:
                pass  # Followup might have already been used or expired
        except Exception as e_regen:
            logger.error(f"Error during control panel regeneration: {e_regen}")
            try:
                await ctx.followup.send(_("❌ Error regenerating control panel. Check logs for details."), ephemeral=True)
            except:
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
        logger.info("All direct Cog loops cancellation attempted.")

        # PERFORMANCE OPTIMIZATION: Clear all caches on unload
        try:
            from .control_ui import _clear_caches
            _clear_caches()
            logger.info("Performance caches cleared on cog unload")
        except Exception as e:
            logger.error(f"Error clearing performance caches on unload: {e}")

    # Method to update global docker status cache from instance cache
    def update_global_status_cache(self):
        """Updates the global docker_status_cache from the instance's status_cache."""
        global docker_status_cache
        try:
            # Thread-safe update of global status cache
            with docker_status_cache_lock:
                docker_status_cache = self.status_cache.copy()
                logger.debug(f"Updated global docker_status_cache with {len(docker_status_cache)} entries")
        except Exception as e:
            logger.error(f"Error updating global docker_status_cache: {e}")

    # Accessor method to get the current status cache
    def get_status_cache(self) -> Dict[str, Any]:
        """Returns the current status cache."""
        return self.status_cache.copy()

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

                                servers = config.get('servers', [])
                                ordered_servers = []
                                seen_docker_names = set()

                                # Apply server ordering
                                from services.docker_service.server_order import load_server_order
                                ordered_server_names = load_server_order()

                                # Build ordered servers list (same logic as serverstatus command)
                                servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
                                for docker_name in ordered_server_names:
                                    if docker_name in servers_by_name:
                                        ordered_servers.append(servers_by_name[docker_name])
                                        seen_docker_names.add(docker_name)
                                for server in servers:
                                    docker_name = server.get('docker_name')
                                    if docker_name and docker_name not in seen_docker_names:
                                        ordered_servers.append(server)
                                        seen_docker_names.add(docker_name)

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
                                now_utc = datetime.now(timezone.utc)
                                if channel_id not in self.last_message_update_time:
                                    self.last_message_update_time[channel_id] = {}
                                self.last_message_update_time[channel_id]['overview'] = now_utc

                                logger.info(f"✅ RECOVERY SUCCESS: Generated new overview message {new_message.id} to replace missing {message_id} in channel {channel_id}")
                                continue

                            except Exception as recovery_error:
                                logger.error(f"❌ RECOVERY FAILED: Could not regenerate overview message for channel {channel_id}: {recovery_error}")
                                # Remove from tracking since we can't recover
                                if channel_id in self.channel_server_message_ids and 'overview' in self.channel_server_message_ids[channel_id]:
                                    del self.channel_server_message_ids[channel_id]['overview']
                                continue

                        # Get fresh server data
                        config = load_config()
                        if not config:
                            continue

                        servers = config.get('servers', [])
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
                        except:
                            pass

                        updated_count += 1
                        logger.info(f"Updated overview message in channel {channel_id} after donation")
                    except Exception as e:
                        logger.error(f"Failed to update overview in channel {channel_id}: {e}")

            logger.info(f"Successfully updated {updated_count} overview messages after donation")

        except Exception as e:
            logger.error(f"Error updating overview messages after donation: {e}")

    async def _update_overview_message(self, channel_id: int, message_id: int) -> bool:
        """
        Updates the overview message with current server statuses.
        
        Args:
            channel_id: Discord channel ID
            message_id: Discord message ID to update
            
        Returns:
            bool: Success or failure
        """
        logger.debug(f"Updating overview message {message_id} in channel {channel_id}")
        try:
            # Get channel
            channel = await self.bot.fetch_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"Channel {channel_id} is not a text channel, cannot update overview.")
                return False
                
            # Get message using partial message for better performance
            try:
                # PERFORMANCE OPTIMIZATION: Use partial message instead of fetch
                message = channel.get_partial_message(message_id)  # No API call
            except discord.NotFound:
                logger.warning(f"Overview message {message_id} in channel {channel_id} not found. Removing from tracking.")
                if channel_id in self.channel_server_message_ids and "overview" in self.channel_server_message_ids[channel_id]:
                    del self.channel_server_message_ids[channel_id]["overview"]
                return False
                
            # Get all servers
            config = self.config
            servers = config.get('servers', [])
            
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
            
            # Create the updated embed based on expansion state
            is_mech_expanded = self.mech_expanded_states.get(channel_id, False)
            if is_mech_expanded:
                embed, animation_file = await self._create_overview_embed_expanded(ordered_servers, config)
            else:
                embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config)
            
            # Update the message (note: can't add files to edit, only embed)
            # Also need to update the view to maintain button states
            from .control_ui import MechView
            view = MechView(self, channel_id)
            await message.edit(embed=embed, view=view)
            
            # Update message update timestamp, but NOT channel activity
            now_utc = datetime.now(timezone.utc)
            if channel_id not in self.last_message_update_time:
                self.last_message_update_time[channel_id] = {}
            self.last_message_update_time[channel_id]["overview"] = now_utc
            
            # DO NOT update channel activity
            # This is commented out to fix the Recreate feature
            # self.last_channel_activity[channel_id] = now_utc
            
            logger.debug(f"Successfully updated overview message {message_id} in channel {channel_id}")
            return True
            
        except discord.errors.NotFound:
            # Message was deleted - RECOVERY: Recreate it automatically
            logger.warning(f"Overview message {message_id} in channel {channel_id} not found (likely deleted). ATTEMPTING AUTOMATIC RECOVERY.")

            # Remove from old tracking system
            if hasattr(self, 'overview_message_ids') and channel_id in self.overview_message_ids:
                del self.overview_message_ids[channel_id]

            # CRITICAL FIX: Automatically recreate the message to prevent corruption
            try:
                # Generate new overview message as recovery
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

                # Update tracking with new message ID
                if channel_id in self.channel_server_message_ids:
                    self.channel_server_message_ids[channel_id]['overview'] = new_message.id

                now_utc = datetime.now(timezone.utc)
                if channel_id not in self.last_message_update_time:
                    self.last_message_update_time[channel_id] = {}
                self.last_message_update_time[channel_id]['overview'] = now_utc

                logger.info(f"✅ RECOVERY SUCCESS: Auto-recreated overview message {new_message.id} to replace deleted {message_id} in channel {channel_id}")
                return True  # Recovery successful

            except Exception as recovery_error:
                logger.error(f"❌ RECOVERY FAILED: Could not auto-recreate overview message for channel {channel_id}: {recovery_error}")
                # Remove from tracking since we can't recover
                if channel_id in self.channel_server_message_ids and 'overview' in self.channel_server_message_ids[channel_id]:
                    del self.channel_server_message_ids[channel_id]['overview']
                return False
            
        except Exception as e:
            logger.error(f"Error updating overview message in channel {channel_id}: {e}", exc_info=True)
            return False
    
    def _register_persistent_mech_views(self):
        """Register persistent views for mech buttons to work after bot restart."""
        try:
            from .control_ui import (MechExpandButton, MechCollapseButton, MechDonateButton,
                                   MechDisplayButton, ReadStoryButton, PlaySongButton, EpilogueButton,
                                   MechHistoryButton)
            import discord

            # Create persistent views for mech buttons
            # These views will persist across bot restarts
            class PersistentMechExpandView(discord.ui.View):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    self.add_item(MechExpandButton(cog_instance, 0))  # Pass cog_instance correctly

            class PersistentMechCollapseView(discord.ui.View):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    self.add_item(MechCollapseButton(cog_instance, 0))  # Pass cog_instance correctly

            class PersistentMechDonateView(discord.ui.View):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    self.add_item(MechDonateButton(cog_instance, 0))  # Pass cog_instance correctly

            class PersistentMechHistoryView(discord.ui.View):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    self.add_item(MechHistoryButton(cog_instance, 0))  # Pass cog_instance correctly

            # Create persistent views for mech selection buttons (levels 1-11)
            class PersistentMechSelectionView(discord.ui.View):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    # Add buttons for all possible mech levels (1-11)
                    for level in range(1, 12):
                        self.add_item(MechDisplayButton(cog_instance, level, f"{level}", True))
                    # Add epilogue button
                    self.add_item(EpilogueButton(cog_instance))

            # Create persistent views for story buttons (levels 1-11)
            class PersistentMechStoryView(discord.ui.View):
                def __init__(self, cog_instance):
                    super().__init__(timeout=None)
                    # Add story and music buttons for all possible levels (1-11)
                    for level in range(1, 12):
                        self.add_item(ReadStoryButton(cog_instance, level))
                        self.add_item(PlaySongButton(cog_instance, level))

            # Register persistent views with proper cog instance
            self.bot.add_view(PersistentMechExpandView(self))
            self.bot.add_view(PersistentMechCollapseView(self))
            self.bot.add_view(PersistentMechDonateView(self))
            self.bot.add_view(PersistentMechHistoryView(self))
            self.bot.add_view(PersistentMechSelectionView(self))
            self.bot.add_view(PersistentMechStoryView(self))
            
            logger.info("✅ Registered persistent mech views for button persistence")
        except Exception as e:
            logger.warning(f"⚠️ Could not register persistent mech views: {e}")

class DonationView(discord.ui.View):
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
                except Exception as e:
                    logger.error(f"Error deleting donation message on timeout: {e}")
        except Exception as e:
            logger.error(f"Error in DonationView.on_timeout: {e}")
    
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
                except Exception as e:
                    logger.error(f"Error auto-deleting donation message: {e}")
        except asyncio.CancelledError:
            logger.debug("Auto-delete timer cancelled")
        except Exception as e:
            logger.error(f"Error in auto-delete timer: {e}")
    
    async def broadcast_clicked(self, interaction: discord.Interaction):
        """Handle Broadcast Donation button click."""
        try:
            # Show modal for donation details
            modal = DonationBroadcastModal(self.donation_manager_available, interaction.user.name, self.bot)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Error in broadcast_clicked: {e}")

class DonationBroadcastModal(discord.ui.Modal):
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
        
        # Amount field (optional)
        self.amount_input = discord.ui.InputText(
            label=_("💰 Donation Amount (optional)"),
            placeholder=_("10.50 (numbers only, $ will be added automatically)"),
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
                        return
                    old_evolution_level = old_state_result.level
                    
                    # Parse amount if provided
                    if amount:
                        amount_match = re.search(r'(\d+(?:\.\d+)?)', amount)
                        if amount_match:
                            donation_amount_euros = float(amount_match.group(1))
                    
                    # Record donation if amount > 0
                    if donation_amount_euros and donation_amount_euros > 0:
                        amount_dollars = int(donation_amount_euros)
                        
                        # Quick feedback to user first (store message to delete later)
                        processing_msg = await interaction.followup.send(
                            _("💰 Processing ${amount} donation...").format(amount=amount_dollars),
                            ephemeral=False  # Make it visible so we can delete it
                        )
                        
                        # Process donation (may take a few seconds for member count)
                        try:
                            if self.bot:
                                new_state = await mech_service.add_donation_with_bot(
                                    username=f"Discord:{interaction.user.name}",
                                    amount=amount_dollars,
                                    bot=self.bot
                                )
                                logger.info(f"Donation recorded: ${amount_dollars}")
                            else:
                                # Fallback if no bot instance available
                                new_state = mech_service.add_donation(
                                    username=f"Discord:{interaction.user.name}",
                                    amount=amount_dollars
                                )
                                logger.info(f"Donation recorded (no bot instance): ${amount_dollars}")
                        except Exception as donation_error:
                            logger.error(f"Error processing donation: {donation_error}")
                            # Fallback to regular donation without bot
                            new_state = mech_service.add_donation(
                                username=f"Discord:{interaction.user.name}",
                                amount=amount_dollars
                            )
                            logger.info(f"Fallback donation recorded: ${amount_dollars}")
                    else:
                        # Get current state using SERVICE FIRST
                        new_state_request = GetMechStateRequest(include_decimals=False)
                        new_state_result = mech_service.get_mech_state_service(new_state_request)
                        if not new_state_result.success:
                            logger.error("Failed to get new mech state")
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

                    # Force update of mech animation when level OR power changes
                    new_power = new_state.Power
                    level_changed = new_state.level != old_state_result.level
                    power_changed = new_power != old_power

                    if level_changed or power_changed:
                        if level_changed:
                            logger.info(f"Level changed from {old_state_result.level} to {new_state.level} - updating mech animations")
                        if power_changed:
                            logger.info(f"Power changed from {old_power} to {new_power} - updating mech animations")

                        # Trigger immediate update of all overview messages
                        cog = interaction.client.get_cog('DockerControlCog')
                        if cog:
                            task = asyncio.create_task(cog._update_all_overview_messages_after_donation())
                            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

                except Exception as e:
                    logger.error(f"Error processing donation: {e}")
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
            
            # Send to channels if sharing publicly
            sent_count = 0
            failed_count = 0
            
            if should_share_publicly:
                config = load_config()
                channels_config = config.get('channel_permissions', {})
                
                for channel_id_str, channel_info in channels_config.items():
                    try:
                        channel_id = int(channel_id_str)
                        channel = interaction.client.get_channel(channel_id)
                        
                        if channel:
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
                        else:
                            failed_count += 1
                            
                    except Exception as channel_error:
                        failed_count += 1
                        logger.error(f"Error sending to channel {channel_id_str}: {channel_error}")
            
            # Respond to user
            if should_share_publicly:
                response_text = _("✅ **Donation broadcast sent!**") + "\n\n"
                response_text += _("📢 Sent to **{count}** channels").format(count=sent_count) + "\n"
                if failed_count > 0:
                    response_text += _("⚠️ Failed to send to {count} channels").format(count=failed_count) + "\n"
                response_text += "\n" + _("Thank you **{donor_name}** for your generosity! 🙏").format(donor_name=donor_name)
            else:
                response_text = _("✅ **Donation recorded privately!**") + "\n\n"
                response_text += _("Thank you **{donor_name}** for your generous support! 🙏").format(donor_name=donor_name) + "\n"
                response_text += _("Your donation has been recorded and helps fuel the Donation Engine.")
            
            # Replace the processing message with the final result
            await interaction.edit_original_response(content=response_text)

            # Clean up processing message if donation was processed
            if processing_msg:
                try:
                    await processing_msg.delete()
                except:
                    pass  # Ignore if already deleted or expired

        except Exception as e:
            logger.error(f"Error in donation broadcast modal: {e}")

            # Clean up processing message even if error occurred
            if processing_msg:
                try:
                    await processing_msg.delete()
                except:
                    pass

            try:
                await interaction.edit_original_response(
                    content=_("❌ Error sending donation broadcast. Please try again later.")
                )
            except Exception as edit_error:
                logger.error(f"Could not send error response: {edit_error}")

# Setup function required for extension loading
def setup(bot):
    """Setup function to add the cog to the bot when loaded as an extension."""
    from services.config.config_service import get_config_service
    config_manager = get_config_service()
    config = config_manager.get_config()
    cog = DockerControlCog(bot, config)
    
    # Remove donation commands if donations are disabled
    try:
        from services.donation.donation_utils import is_donations_disabled
        if is_donations_disabled():
            # Remove the donate and donatebroadcast commands
            commands_to_remove = ['donate', 'donatebroadcast']
            for cmd_name in commands_to_remove:
                if cmd_name in bot.application_commands:
                    del bot.application_commands[cmd_name]
                    logger.info(f"Removed /{cmd_name} command - donations disabled")
    except Exception as e:
        logger.debug(f"Could not remove donation commands: {e}")
    
    # Add simple donation notification task
    @tasks.loop(seconds=30)
    async def check_donation_notifications():
        """Check for donation notifications from Web UI"""
        try:
            import json
            import os
            notification_file = "/app/config/donation_notification.json"
            
            logger.debug(f"Checking for donation notification file: {notification_file}")
            
            if os.path.exists(notification_file):
                logger.info(f"Found donation notification file!")
                with open(notification_file, 'r') as f:
                    notification = json.load(f)
                
                logger.info(f"🔔 Notification data: {notification}")
                
                if notification.get('type') == 'donation':
                    donor_name = notification.get('donor', 'Anonymous')
                    amount = notification.get('amount', 0)
                    
                    logger.info(f"🔔 Processing donation notification: {donor_name} ${amount}")
                    
                    try:
                        # Create broadcast message (same as /donate) using configured Discord bot language
                        try:
                            from cogs.translation_manager import get_translation
                            _ = get_translation()
                        except:
                            # Fallback if translation fails
                            def _(text):
                                return text
                        
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
                            except Exception as channel_error:
                                logger.error(f"🔔 Error sending to channel {channel_id_str}: {channel_error}")
                        
                        logger.info(f"🔔 Processed Web UI donation: {donor_name} ${amount} - sent to {sent_count} channels")
                        
                    except Exception as embed_error:
                        logger.error(f"🔔 Error creating/sending donation embed: {embed_error}", exc_info=True)
                
                # Delete file after processing
                os.remove(notification_file)
                
        except Exception as e:
            logger.debug(f"Error checking donation notifications: {e}")
    
    # Start the task and add to cog
    check_donation_notifications.start()
    cog.donation_notification_task = check_donation_notifications

    # Start the Mech Status Cache background loop
    cog.start_mech_cache_loop.start()
    logger.info("Mech Status Cache startup task initiated")

    # Start the Animation Cache Maintenance background loop
    cog.start_animation_maintenance_loop.start()
    logger.info("Animation Cache Maintenance startup task initiated")

    bot.add_cog(cog)