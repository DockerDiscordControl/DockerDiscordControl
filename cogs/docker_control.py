# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2023-2025 MAX                                                  #
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

# Import app_commands using central utility
from utils.app_commands_helper import get_app_commands, get_discord_option
app_commands = get_app_commands()
DiscordOption = get_discord_option()

# Import our utility functions
from utils.config_loader import load_config, DEFAULT_CONFIG
from utils.docker_utils import get_docker_info, get_docker_stats, docker_action
from utils.time_utils import format_datetime_with_timezone
from utils.logging_utils import setup_logger
from utils.server_order import load_server_order, save_server_order

# Import scheduler module
from utils.scheduler import (
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
from .control_ui import ActionButton, ToggleButton, ControlView, TaskDeletePanelView

# Import the autocomplete handlers that have been moved to their own module
from .autocomplete_handlers import (
    schedule_container_select, schedule_action_select, schedule_cycle_select,
    schedule_time_select, schedule_month_select, schedule_weekday_select,
    schedule_day_select, schedule_info_period_select, schedule_year_select,
    schedule_task_id_select
)

# Import the schedule commands mixin that contains schedule command handlers
from .scheduler_commands import ScheduleCommandsMixin

# Import the status handlers mixin that contains status-related functionality
from .status_handlers import StatusHandlersMixin

# Import the command handlers mixin that contains Docker action command functionality 
from .command_handlers import CommandHandlersMixin

# Import central logging function
from utils.action_logger import log_user_action

# Configure logger for the cog using utility
logger = setup_logger('ddc.docker_control', level=logging.DEBUG)

# Global variable for Docker status cache to allow access from other modules
docker_status_cache = {}
docker_status_cache_lock = threading.Lock()  # Thread safety for global status cache

class DockerControlCog(commands.Cog, ScheduleCommandsMixin, StatusHandlersMixin, CommandHandlersMixin):
    """Cog for DockerDiscordControl container management via Discord."""

    def __init__(self, bot: commands.Bot, config: dict):
        """Initializes the DockerDiscordControl Cog."""
        logger.info("Initializing DockerControlCog... [DDC-SETUP]")
        self.bot = bot
        self.config = config
        self.expanded_states = {} 
        self.channel_server_message_ids: Dict[int, Dict[str, int]] = {}
        self.last_message_update_time: Dict[int, Dict[str, datetime]] = {}
        self.initial_messages_sent = False
        self.last_channel_activity: Dict[int, datetime] = {}
        self.status_cache = {}
        self.cache_ttl_seconds = 75
        self.pending_actions: Dict[str, Dict[str, Any]] = {}
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
        self.translations = get_translations()

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

        # Set up the various background loops
        logger.info("Setting up and starting background loops...")
        
        # Start status update loop (30 seconds interval)
        self.bot.loop.create_task(self._start_loop_safely(self.status_update_loop, "Status Update Loop"))
        
        # Start periodic message edit loop (1 minute interval)
        logger.info("Scheduling controlled start of DIRECTLY DEFINED periodic_message_edit_loop...")
        self.bot.loop.create_task(self._start_periodic_message_edit_loop_safely())
        
        # Start inactivity check loop (1 minute interval)
        self.bot.loop.create_task(self._start_loop_safely(self.inactivity_check_loop, "Inactivity Check Loop"))
        
        # PERFORMANCE OPTIMIZATION: Start cache clear loop (5 minute interval)
        self.bot.loop.create_task(self._start_loop_safely(self.performance_cache_clear_loop, "Performance Cache Clear Loop"))
        
        # Start heartbeat loop if enabled (1 minute interval, configurable)
        heartbeat_config = self.config.get('heartbeat', {})
        if heartbeat_config.get('enabled', False):
            self.bot.loop.create_task(self._start_loop_safely(self.heartbeat_send_loop, "Heartbeat Loop"))
        
        # Schedule initial status send with a delay
        logger.info("Re-activating AUTOMATIC INITIAL STATUS SEND.")
        self.bot.loop.create_task(self.send_initial_status_after_delay_and_ready(10))

        # Initialize global status cache
        self.update_global_status_cache()
        
        logger.info("DockerControlCog __init__ complete. Background loops and initial status send scheduled.")

    # --- PERIODIC MESSAGE EDIT LOOP (FULL LOGIC, MOVED DIRECTLY INTO COG) ---
    @tasks.loop(minutes=1, reconnect=True)
    async def periodic_message_edit_loop(self):
        logger.info("--- DIRECT COG periodic_message_edit_loop cycle --- Starting Check --- ")
        if not self.initial_messages_sent:
             logger.debug("Direct Cog Periodic edit loop: Initial messages not sent yet, skipping.")
             return

        logger.info(f"Direct Cog Periodic Edit Loop: Checking {len(self.channel_server_message_ids)} channels with tracked messages.")
        
        # ULTRA-PERFORMANCE: Collect all containers that might need updates for bulk fetching
        all_container_names = set()
        tasks_to_run = []
        now_utc = datetime.now(timezone.utc)
        
        channel_permissions_config = self.config.get('channel_permissions', {})
        # Ensure DEFAULT_CONFIG is accessible here if not already a class/instance variable
        # It was imported at the top of the file: from utils.config_loader import DEFAULT_CONFIG
        default_perms = DEFAULT_CONFIG.get('default_channel_permissions', {})

        for channel_id in list(self.channel_server_message_ids.keys()):
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

            for display_name in list(server_messages_in_channel.keys()):
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
                # IMPROVED: Run message edits in batches to reduce Discord API pressure
                BATCH_SIZE = 3  # Process 3 messages at a time instead of all at once
                logger.info(f"Direct Cog Periodic Edit Loop: Running {total_tasks} message edits in BATCHED mode (batch size: {BATCH_SIZE})")
                
                # Process tasks in batches
                for i in range(0, total_tasks, BATCH_SIZE):
                    batch_tasks = tasks_to_run[i:i + BATCH_SIZE]
                    batch_num = (i // BATCH_SIZE) + 1
                    total_batches = (total_tasks + BATCH_SIZE - 1) // BATCH_SIZE
                    
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
                    if i + BATCH_SIZE < total_tasks:  # Don't delay after last batch
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
            default_recreate_enabled = DEFAULT_CONFIG.get('default_channel_permissions', {}).get('recreate_messages_on_inactivity', True)
            default_timeout_minutes = DEFAULT_CONFIG.get('default_channel_permissions', {}).get('inactivity_timeout_minutes', 10)
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
        # Need to access DEFAULT_CONFIG correctly, it might not be directly available as self.DEFAULT_CONFIG
        # It's imported in this module
        default_perms_inactivity = DEFAULT_CONFIG.get('default_channel_permissions', {}).get('recreate_messages_on_inactivity', True)
        default_perms_timeout = DEFAULT_CONFIG.get('default_channel_permissions', {}).get('inactivity_timeout_minutes', 10)

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
    async def _send_control_panel_and_statuses(self, channel: discord.TextChannel):
        """Sends the main control panel and all server statuses to a channel."""
        config = self.config
        servers = config.get('servers', [])
        lang = config.get('language', 'de')
        logger.info(f"Sending control panel and statuses to channel {channel.name} ({channel.id})")
        # Optional: Send an initial "Control Panel" message if desired
        # await channel.send(_("**Docker Control Panel**"))

        # Get ordered server names directly from the class attribute (loaded from persistent file)
        ordered_docker_names = self.ordered_server_names
        logger.debug(f"Using ordered_server_names from class attribute: {ordered_docker_names}")
        
        # Create a dictionary for quick server lookup by docker_name
        servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
        
        # Create an ordered list of server configurations
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
        
        # Fallback: If ordered_servers is empty, use all servers
        if not ordered_servers:
            ordered_servers = servers
            logger.debug("No server order found, using default order from servers list")
        
        logger.debug(f"Final ordered server list: {[s.get('name', s.get('docker_name')) for s in ordered_servers]}")

        results = []
        for server_conf in ordered_servers:
            try:
                result = await self.send_server_status(channel, server_conf, config, allow_toggle=True, force_collapse=False)
                results.append(result)
            except Exception as e:
                results.append(e)
                logger.error(f"Exception while sending status for {server_conf.get('name', server_conf.get('docker_name'))} to {channel.id}: {e}", exc_info=True)

        # Logging results (optional)
        success_count = 0
        fail_count = 0
        for i, result_item in enumerate(results):
            server_conf_log = ordered_servers[i] # Get corresponding server_conf for logging
            name = server_conf_log.get('name', server_conf_log.get('docker_name', 'Unknown'))
            if isinstance(result_item, Exception):
                fail_count += 1
                # Error already logged above if it was caught directly
            elif isinstance(result_item, discord.Message):
                success_count += 1
            else: # None or other unexpected type
                fail_count += 1
                logger.warning(f"No message object or exception returned for {name} in {channel.id}, result type: {type(result_item)}")

        logger.info(f"Finished sending initial statuses to {channel.name}: {success_count} success, {fail_count} failure.")

    async def _send_all_server_statuses(self, channel: discord.TextChannel, allow_toggle: bool = True, force_collapse: bool = False):
        """Sends or updates status messages for ALL configured servers in a channel.
        Uses send_server_status, which only reads from the cache.
        Accepts allow_toggle to control the display of the toggle button.
        """
        config = self.config
        servers = config.get('servers', [])
        lang = config.get('language', 'de')
        logger.info(f"Sending all server statuses to channel {channel.name} ({channel.id}), allow_toggle={allow_toggle}, force_collapse={force_collapse}")

        # Get ordered server names directly from the class attribute (loaded from persistent file)
        ordered_docker_names = self.ordered_server_names
        logger.debug(f"Using ordered_server_names from class attribute: {ordered_docker_names}")
        
        # Create a dictionary for quick server lookup by docker_name
        servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
        
        # Create an ordered list of server configurations
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
        
        # Fallback: If ordered_servers is empty, use all servers
        if not ordered_servers:
            ordered_servers = servers
            logger.debug("No server order found, using default order from servers list")
        
        logger.debug(f"Final ordered server list: {[s.get('name', s.get('docker_name')) for s in ordered_servers]}")

        results = []
        for server_conf in ordered_servers:
            try:
                result = await self.send_server_status(channel, server_conf, config, allow_toggle, force_collapse)
                results.append(result)
            except Exception as e:
                results.append(e)
                logger.error(f"Exception while sending/updating status for {server_conf.get('name', server_conf.get('docker_name'))} to {channel.id}: {e}", exc_info=True)

        # Logging results (optional)
        success_count = 0
        fail_count = 0
        for i, result_item in enumerate(results):
            server_conf_log = ordered_servers[i] # Get corresponding server_conf for logging
            name = server_conf_log.get('name', server_conf_log.get('docker_name', 'Unknown'))
            if isinstance(result_item, Exception):
                fail_count += 1
                # Error already logged above
            elif isinstance(result_item, discord.Message):
                success_count += 1
            elif result_item is None:
                 logger.debug(f"Status for {name} likely unchanged or failed fetch, no message sent/edited.") # Adjusted log
            else:
                fail_count += 1
                logger.warning(f"Received unexpected result type {type(result_item)} for {name} in {channel.id}") # Adjusted log

        logger.info(f"Finished sending/updating statuses to {channel.name}: {success_count} success, {fail_count} failure.")

    async def _regenerate_channel(self, channel: discord.TextChannel, mode: str):
        """Deletes old bot messages and resends according to the mode."""
        try:
            logger.info(f"Regenerating channel {channel.name} ({channel.id}) in mode '{mode}'")
            
            # Clear message ID cache for this channel
            if channel.id in self.channel_server_message_ids:
                # If we're in status mode, only clear the "overview" key
                if mode == 'status' and "overview" in self.channel_server_message_ids[channel.id]:
                    # Only clear the overview message tracking
                    del self.channel_server_message_ids[channel.id]["overview"]
                    logger.info(f"Cleared 'overview' message ID cache for channel {channel.id}")
                else:
                    # Clear all tracking for this channel
                    del self.channel_server_message_ids[channel.id]
                    logger.info(f"Cleared all message ID cache for channel {channel.id}")
            
            await self.delete_bot_messages(channel, limit=300)
            await asyncio.sleep(1.0)
            if mode == 'control':
                await self._send_control_panel_and_statuses(channel)
            elif mode == 'status':
                # Use serverstatus format (overview message) instead of individual messages
                config = self.config
                servers = config.get('servers', [])
                
                # Sort servers using ordered_server_names
                ordered_docker_names = self.ordered_server_names
                servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
                
                # Create ordered list of servers
                ordered_servers = []
                seen_docker_names = set()
                
                # First add servers in defined order
                for docker_name in ordered_docker_names:
                    if docker_name in servers_by_name:
                        ordered_servers.append(servers_by_name[docker_name])
                        seen_docker_names.add(docker_name)
                
                # Add any remaining servers
                for server in servers:
                    docker_name = server.get('docker_name')
                    if docker_name and docker_name not in seen_docker_names:
                        ordered_servers.append(server)
                        seen_docker_names.add(docker_name)
                
                # Create the overview embed
                embed = await self._create_overview_embed(ordered_servers, config)
                
                # Send the embed
                overview_message = await channel.send(embed=embed)
                
                # Store message ID for later updates
                if channel.id not in self.channel_server_message_ids:
                    self.channel_server_message_ids[channel.id] = {}
                self.channel_server_message_ids[channel.id]["overview"] = overview_message.id
                
                # Set last update time
                if channel.id not in self.last_message_update_time:
                    self.last_message_update_time[channel.id] = {}
                self.last_message_update_time[channel.id]["overview"] = datetime.now(timezone.utc)
                
                logger.info(f"Created overview message for channel {channel.id} during regeneration")
            logger.info(f"Regeneration for channel {channel.name} completed.")
        except Exception as e:
            logger.error(f"Error regenerating channel {channel.name}: {e}", exc_info=True)

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

            current_config = self.config
            initial_post_channels = []
            channel_permissions = current_config.get('channel_permissions', {})
            logger.debug("Searching for channels with initial posting enabled")

            tasks = []
            for channel_id_str, data in channel_permissions.items():
                if channel_id_str.isdigit():
                    channel_id = int(channel_id_str)
                    # Check if initial posting is enabled for this channel (default to False if key missing)
                    if data.get('post_initial', False):
                        # Check permissions and determine mode
                        has_control_perm = _channel_has_permission(channel_id, 'control', current_config)
                        has_status_perm = _channel_has_permission(channel_id, 'serverstatus', current_config)
                        mode_to_regenerate = None
                        
                        if has_control_perm:
                            mode_to_regenerate = 'control'
                            logger.debug(f"Channel {channel_id} has 'control' and 'post_initial'. Mode: control.")
                        elif has_status_perm:
                            mode_to_regenerate = 'status'
                            logger.debug(f"Channel {channel_id} has 'serverstatus' and 'post_initial'. Mode: status.")
                        
                        # If a mode was determined, fetch channel and add task
                        if mode_to_regenerate:
                            try:
                                channel = await self.bot.fetch_channel(channel_id)
                                if isinstance(channel, discord.TextChannel):
                                    logger.info(f"Found channel '{channel.name}' ({channel_id}) for initial post in '{mode_to_regenerate}' mode")
                                    tasks.append(self._regenerate_channel(channel, mode_to_regenerate))
                                else:
                                    logger.warning(f"Channel ID {channel_id} is not a text channel")
                            except discord.NotFound:
                                logger.warning(f"Channel ID {channel_id} not found")
                            except discord.Forbidden:
                                logger.warning(f"Missing permissions to fetch channel {channel_id}")
                            except Exception as e:
                                logger.error(f"Error processing channel {channel_id}: {e}")
                # else: post_initial is False or missing

            if tasks:
                logger.info(f"Regenerating {len(tasks)} channels")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Check results for errors
                error_count = 0
                for result in results:
                    if isinstance(result, Exception):
                        error_count += 1
                        logger.error(f"Error during channel regeneration: {result}")
                if error_count == 0:
                    initial_send_successful = True
                    logger.info("All initial channel regenerations completed successfully")
                else:
                    logger.warning(f"Completed initial channel regenerations with {error_count} errors")
                await asyncio.sleep(0.2) # Sleep if regenerations happened
            else:
                logger.info("No channels configured for initial posting")

        except Exception as e:
            logger.error(f"Critical error during send_initial_status: {e}", exc_info=True)
        finally:
            self.initial_messages_sent = True
            logger.info(f"send_initial_status finished. Initial messages sent flag set to True. Success: {initial_send_successful}")
            # ... (Logging at the end remains the same)

    # _update_single_message WAS REMOVED
    # _update_single_server_message_by_name WAS REMOVED

    async def delete_bot_messages(self, channel: discord.TextChannel, limit: int = 200):
        """Deletes all bot messages in a channel up to the specified limit."""
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"Attempted to delete messages in non-text channel: {channel}")
            return
        logger.info(f"Deleting up to {limit} bot messages in channel {channel.name} ({channel.id})")
        try:
            # Define a check function
            def is_me(m):
                return m.author == self.bot.user

            deleted_count = 0
            async for message in channel.history(limit=limit):
                 if is_me(message):
                     try:
                         await message.delete()
                         deleted_count += 1
                         await asyncio.sleep(0.1) # Small delay for rate limiting
                     except discord.Forbidden:
                         logger.error(f"Missing permissions to delete message {message.id} in {channel.name}.")
                         break # No permission, further attempts are pointless
                     except discord.NotFound:
                         logger.warning(f"Message {message.id} already deleted in {channel.name}.")
                     except Exception as e:
                         logger.error(f"Error deleting message {message.id} in {channel.name}: {e}")

            # Alternative: channel.purge (can be faster, but less control/logging)
            # try:
            #     deleted = await channel.purge(limit=limit, check=is_me)
            #     logger.info(f"Deleted {len(deleted)} bot messages in {channel.name} ({channel.id}) using purge.")
            # except discord.Forbidden:
            #     logger.error(f"Missing permissions to purge messages in {channel.name}.")
            # except discord.HTTPException as e:
            #     logger.error(f"HTTP error during purge in {channel.name}: {e}")

            logger.info(f"Finished deleting bot messages in {channel.name}. Deleted {deleted_count} messages.")
        except Exception as e:
            logger.error(f"An error occurred during message deletion in {channel.name}: {e}", exc_info=True)

    # --- Slash Commands ---
    @commands.slash_command(name="serverstatus", description=_("Shows the status of all containers"), guild_ids=get_guild_id())
    async def serverstatus(self, ctx: discord.ApplicationContext):
        """Shows an overview of all server statuses in a single message."""
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

        # Respond directly without deferring first
        await ctx.respond(translate("Generating overview..."), ephemeral=True)

        config = self.config
        servers = config.get('servers', [])
        if not servers:
            embed = discord.Embed(
                title=translate("⚠️ No Servers"),
                description=translate("No servers are configured for monitoring."),
                color=discord.Color.orange()
            )
            await ctx.channel.send(embed=embed)
            return

        # --- Delete old messages --- #
        try:
            logger.info(f"[/serverstatus] Deleting old bot messages in {ctx.channel.name}...")
            await self.delete_bot_messages(ctx.channel, limit=300) # Limit adjustable
            await asyncio.sleep(1.0) # Short pause after deleting
            logger.info(f"[/serverstatus] Finished deleting messages in {ctx.channel.name}.")
        except Exception as e_delete:
            logger.error(f"[/serverstatus] Error deleting messages in {ctx.channel.name}: {e_delete}")
            # Continue even if deletion fails
        # --- End message deletion --- #

        # Sort servers using ordered_server_names
        ordered_docker_names = self.ordered_server_names
        servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
        
        # Create an ordered list of server configurations
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
        
        # Fallback: If ordered_servers is empty, use all servers
        if not ordered_servers:
            ordered_servers = servers

        # Create the overview embed
        embed = await self._create_overview_embed(ordered_servers, config)
        
        # Send the embed directly to the channel instead of using followup
        overview_message = await ctx.channel.send(embed=embed)
        
        # Store the message ID for later updates
        if ctx.channel.id not in self.channel_server_message_ids:
            self.channel_server_message_ids[ctx.channel.id] = {}
        self.channel_server_message_ids[ctx.channel.id]["overview"] = overview_message.id
        
        # Set last update time for channel activity tracking
        if ctx.channel.id not in self.last_message_update_time:
            self.last_message_update_time[ctx.channel.id] = {}
        self.last_message_update_time[ctx.channel.id]["overview"] = datetime.now(timezone.utc)
        
        # Also update channel activity for inactivity checks
        self.last_channel_activity[ctx.channel.id] = datetime.now(timezone.utc)
        
        logger.info(f"[/serverstatus] Sent overview message {overview_message.id} in channel {ctx.channel.id}")

    @commands.slash_command(name="ss", description=_("Shortcut: Shows the status of all containers"), guild_ids=get_guild_id())
    async def ss(self, ctx):
        """Shortcut for the serverstatus command."""
        await self.serverstatus(ctx)

    async def command(self, ctx: discord.ApplicationContext, 
                     container_name: str, 
                     action: str):
        """
        Slash command to control a Docker container.
        
        The implementation logic has been moved to the CommandHandlersMixin class 
        in command_handlers.py. This command delegates to the _impl_command method there.
        """
        # Simply delegate to the implementation in CommandHandlersMixin
        await self._impl_command(ctx, container_name, action)

    # Decorator adjusted
    @commands.slash_command(name="help", description=_("Displays help for available commands"), guild_ids=get_guild_id())
    async def help_command(self, ctx: discord.ApplicationContext):
        """Displays help information about available commands."""
        embed = discord.Embed(
            title=_("DockerDiscordControl - Help"),
            description=_("Here are the available commands:"),
            color=discord.Color.blue()
        )
        embed.add_field(name="`/serverstatus` or `/ss`", value=_("Displays the status of all configured Docker containers."), inline=False)
        embed.add_field(name="`/command <container> <action>`", value=_("Controls a specific Docker container. Actions: `start`, `stop`, `restart`. Requires permissions."), inline=False)
        embed.add_field(name="`/control`", value=_("(Re)generates the main control panel message in channels configured for it."), inline=False)
        embed.add_field(name="`/help`", value=_("Shows this help message."), inline=False)
        embed.add_field(name="`/ping`", value=_("Checks the bot's latency."), inline=False)
        embed.set_footer(text="https://ddc.bot")

        await ctx.respond(embed=embed, ephemeral=True)

    @commands.slash_command(name="ping", description=_("Shows the bot's latency"), guild_ids=get_guild_id())
    async def ping_command(self, ctx: discord.ApplicationContext):
        latency = round(self.bot.latency * 1000)
        ping_message = _("Pong! Latency: {latency:.2f} ms").format(latency=latency)
        embed = discord.Embed(title="🏓", description=ping_message, color=discord.Color.blurple())
        await ctx.respond(embed=embed)

    async def _create_overview_embed(self, ordered_servers, config):
        """Creates the server overview embed with the status of all servers."""
        # Import translation function locally to ensure it's accessible
        from .translation_manager import _ as translate
        
        # Create the overview embed
        embed = discord.Embed(
            title=translate("Server Overview"),
            color=discord.Color.blue()
        )

        # Build server status lines
        now_utc = datetime.now(timezone.utc)
        timezone_str = config.get('timezone')
        current_time = format_datetime_with_timezone(now_utc, timezone_str, fmt="%H:%M:%S")
        
        # Add timestamp at the top
        last_update_text = translate("Last update")
        
        # Start building the content
        content_lines = [
            f"{last_update_text}: {current_time}",
            "┌── Status ─────────────────"
        ]

        # Collect all server statuses
        for server_conf in ordered_servers:
            display_name = server_conf.get('name', server_conf.get('docker_name'))
            docker_name = server_conf.get('docker_name')
            if not display_name or not docker_name:
                continue
                
            # ULTRA-FAST OPTIMIZATION: Use ONLY cached data
            # No more Docker queries - Background loop (every 30s) provides current data
            cached_entry = self.status_cache.get(display_name)
            status_result = None
            
            if cached_entry and cached_entry.get('data'):
                # ✅ Cache available - use cached data
                status_result = cached_entry['data']
            else:
                # ⚠️ NO cache available - show "Loading" status
                logger.debug(f"[/serverstatus] No cache entry for '{display_name}' - Background loop will update")
                status_result = None
            
            # Process status result
            if status_result and isinstance(status_result, tuple) and len(status_result) == 6:
                _, is_running, _, _, _, _ = status_result
                
                # Determine status icon
                if display_name in self.pending_actions:
                    pending_timestamp = self.pending_actions[display_name]['timestamp']
                    pending_duration = (now_utc - pending_timestamp).total_seconds()
                    if pending_duration < 120:  # Same timeout as in status_handlers.py
                        status_emoji = "🟡"  # Yellow for pending
                        # Use "Pending" status text instead of Online/Offline
                        status_text = translate("Pending")
                    else:
                        # Clear stale pending state
                        del self.pending_actions[display_name]
                        status_emoji = "🟢" if is_running else "🔴"
                        # Normal status text based on is_running
                        status_text = translate("Online") if is_running else translate("Offline")
                else:
                    status_emoji = "🟢" if is_running else "🔴"
                    # Normal status text based on is_running
                    status_text = translate("Online") if is_running else translate("Offline")
                
                # Add status line with proper spacing
                line = f"│ {status_emoji} {status_text:8} {display_name}"
                content_lines.append(line)
            else:
                # No cache data available - show loading status
                status_emoji = "🔄"
                status_text = translate("Loading")
                line = f"│ {status_emoji} {status_text:8} {display_name}"
                content_lines.append(line)

        # Add footer line
        content_lines.append("└───────────────────────────")
        
        # Combine all lines into the description
        embed.description = "```\n" + "\n".join(content_lines) + "\n```"
        
        # Add the footer with the website URL
        embed.set_footer(text="https://ddc.bot")
        
        return embed

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
            # Load the heartbeat configuration
            # First check legacy format with 'heartbeat_channel_id' at root level
            heartbeat_channel_id = self.config.get('heartbeat_channel_id')
            
            # Initialize heartbeat config with defaults
            heartbeat_config = {
                'enabled': bool(heartbeat_channel_id),  # Enabled if channel ID exists
                'method': 'channel',                    # Only channel method is implemented
                'interval': 60,                         # Default: 60 minutes 
                'channel_id': heartbeat_channel_id      # Channel ID from root config
            }
            
            # Override with nested config if it exists (new format)
            if 'heartbeat' in self.config:
                nested_config = self.config.get('heartbeat', {})
                if isinstance(nested_config, dict):
                    heartbeat_config.update(nested_config)
            
            # Check if heartbeat is enabled
            if not heartbeat_config.get('enabled', False):
                logger.debug("Heartbeat monitoring disabled in config.")
                return
    
            # Get the heartbeat method and interval
            method = heartbeat_config.get('method', 'channel')
            interval_minutes = int(heartbeat_config.get('interval', 60))
    
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
        """Periodically updates the internal status cache for all servers."""
        try:
            if not self.bot.is_ready():
                logger.warning("Bot is not ready yet, skipping status update loop iteration")
                return
                
            logger.debug("Running status_update_loop to refresh Docker container status cache")
            
            # OPTIMIZATION: Use the cached config from self.config
            # No need to reload config from disk, we use the instance variable
            servers = self.config.get('servers', [])
            if not servers:
                logger.debug("No servers configured, status cache update skipped")
                return
            
            # PERFORMANCE OPTIMIZATION: Use bulk fetching instead of individual calls
            start_time = time.time()
            now = datetime.now(timezone.utc)
            
            # Extract all container names for bulk fetching
            container_names = []
            for server_conf in servers:
                docker_name = server_conf.get('docker_name')
                if docker_name:
                    container_names.append(docker_name)
            
            if not container_names:
                logger.debug("No valid container names found in server configurations")
                return
            
            logger.info(f"[STATUS_LOOP] Bulk updating cache for {len(container_names)} containers")
            
            # Use the optimized bulk fetch function
            bulk_results = await self.bulk_fetch_container_status(container_names)
            
            # Update cache with bulk results
            update_count = 0
            error_count = 0
            
            for docker_name, status_tuple in bulk_results.items():
                try:
                    # Find the corresponding server config
                    server_config = next((s for s in servers if s.get('docker_name') == docker_name), None)
                    if not server_config:
                        logger.warning(f"[STATUS_LOOP] No server config found for docker_name: {docker_name}")
                        error_count += 1
                        continue
                    
                    display_name = server_config.get('name', docker_name)
                    
                    # Update cache with bulk result
                    self.status_cache[display_name] = {
                        'data': status_tuple,
                        'timestamp': now
                    }
                    update_count += 1
                    
                except Exception as e:
                    logger.error(f"[STATUS_LOOP] Error processing bulk result for {docker_name}: {e}")
                    error_count += 1
            
            # Handle containers that weren't in bulk results (errors or not found)
            for server_conf in servers:
                docker_name = server_conf.get('docker_name')
                display_name = server_conf.get('name', docker_name)
                
                if docker_name and docker_name not in bulk_results:
                    # Container not in bulk results - likely error or offline
                    logger.debug(f"[STATUS_LOOP] Container '{docker_name}' not in bulk results, marking as offline")
                    
                    details_allowed = server_conf.get('allow_detailed_status', True)
                    offline_status = (display_name, False, 'N/A', 'N/A', 'N/A', details_allowed)
                    
                    self.status_cache[display_name] = {
                        'data': offline_status,
                        'timestamp': now
                    }
                    update_count += 1
            
            # Set last cache update timestamp
            self.last_cache_update = time.time()
            
            # Update the global cache after all servers are processed
            self.update_global_status_cache()
            
            elapsed_time = (time.time() - start_time) * 1000
            
            # Performance logging
            if elapsed_time > 10000:  # Over 10 seconds
                logger.error(f"[STATUS_LOOP] CRITICAL: Cache update took {elapsed_time:.1f}ms for {len(container_names)} containers")
            elif elapsed_time > 5000:  # Over 5 seconds
                logger.warning(f"[STATUS_LOOP] SLOW: Cache update took {elapsed_time:.1f}ms for {len(container_names)} containers")
            else:
                logger.info(f"[STATUS_LOOP] Cache updated: {update_count} success, {error_count} errors in {elapsed_time:.1f}ms")
                
        except Exception as e:
            logger.error(f"Error in status_update_loop: {e}", exc_info=True)

    @status_update_loop.before_loop
    async def before_status_update_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()

    # --- Inactivity Check Loop ---
    @tasks.loop(seconds=30)
    async def inactivity_check_loop(self):
        """Checks for inactive channels and regenerates messages if needed."""
        try:
            if not self.initial_messages_sent:
                logger.debug("Inactivity check loop: Initial messages not sent yet, skipping.")
                return

            logger.debug("Inactivity check loop running")
            
            # Get channel permissions from config
            channel_permissions = self.config.get('channel_permissions', {})
            default_recreate_enabled = DEFAULT_CONFIG.get('default_channel_permissions', {}).get('recreate_messages_on_inactivity', True)
            default_timeout_minutes = DEFAULT_CONFIG.get('default_channel_permissions', {}).get('inactivity_timeout_minutes', 10)
            now_utc = datetime.now(timezone.utc)
            
            # Log tracked channels for debugging
            logger.debug(f"Currently tracking {len(self.last_channel_activity)} channels for activity")
            
            # Check each channel we've previously registered activity for
            for channel_id, last_activity_time in list(self.last_channel_activity.items()):
                channel_config = channel_permissions.get(str(channel_id))
                
                logger.debug(f"Checking channel {channel_id}")
                
                # Skip channels with no config
                if not channel_config:
                    logger.debug(f"Channel {channel_id} has no specific config, skipping")
                    continue
                    
                recreate_enabled = channel_config.get('recreate_messages_on_inactivity', default_recreate_enabled)
                timeout_minutes = channel_config.get('inactivity_timeout_minutes', default_timeout_minutes)
                
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
                            has_control_permission = _channel_has_permission(channel_id, 'control', self.config)
                            regeneration_mode = 'control' if has_control_permission else 'status'
                            logger.debug(f"Regeneration mode for empty channel: {regeneration_mode}")
                            await self._regenerate_channel(channel, regeneration_mode)
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
                        has_control_permission = _channel_has_permission(channel_id, 'control', self.config)
                        has_status_permission = _channel_has_permission(channel_id, 'serverstatus', self.config)
                        
                        logger.debug(f"Channel permissions - control: {has_control_permission}, status: {has_status_permission}")
                        
                        regeneration_mode = 'control' if has_control_permission else 'status'
                        
                        # Force the mode to be valid
                        if not has_control_permission and not has_status_permission:
                            logger.warning(f"Channel {channel.name} has neither control nor status permissions. Cannot regenerate")
                            continue
                        
                        logger.debug(f"Will regenerate with mode: {regeneration_mode}")
                        
                        # Attempt channel regeneration
                        await self._regenerate_channel(channel, regeneration_mode)
                        
                        # Reset activity timer
                        self.last_channel_activity[channel_id] = now_utc
                        logger.info(f"Channel {channel.name} ({channel_id}) regenerated due to inactivity. Mode: {regeneration_mode}")
                        
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

    # --- Final Control Command ---
    @commands.slash_command(name="control", description=_("Displays the control panel in the control channel"), guild_ids=get_guild_id())
    async def control_command(self, ctx: discord.ApplicationContext):
        """(Re)generates the control panel message in the current channel if permitted."""
        if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
            return

        if not _channel_has_permission(ctx.channel.id, 'control', self.config):
            await ctx.respond(_("You do not have permission to use this command in this channel, or control panels are disabled here."), ephemeral=True)
            return

        await ctx.defer(ephemeral=False)
        logger.info(f"Control panel regeneration requested by {ctx.author} in {ctx.channel.name}")

        try:
            await ctx.followup.send(_("Regenerating control panel... Please wait."), ephemeral=True)
        except Exception as e_followup:
            logger.error(f"Error sending initial followup for /control command: {e_followup}")

        channel_to_regenerate = ctx.channel
        async def run_regeneration():
            try:
                await self._regenerate_channel(channel_to_regenerate, 'control')
                logger.info(f"Background regeneration for channel {channel_to_regenerate.name} completed.")
            except Exception as e_regen:
                logger.error(f"Error during background regeneration for channel {channel_to_regenerate.name}: {e_regen}")

        self.bot.loop.create_task(run_regeneration())
        
    # --- SCHEDULE COMMANDS ---
    @commands.slash_command(name="task_once", description=_("Schedule a one-time task"), guild_ids=get_guild_id())
    async def schedule_once_command(self, ctx: discord.ApplicationContext, 
                              container_name: str = discord.Option(description=_("The Docker container to schedule"), autocomplete=container_select),
                              action: str = discord.Option(description=_("Action to perform"), autocomplete=schedule_action_select),
                              time: str = discord.Option(description=_("Time in HH:MM format (e.g., 14:30)"), autocomplete=schedule_time_select),
                              day: str = discord.Option(description=_("Day of month (e.g., 15)"), autocomplete=schedule_day_select),
                              month: str = discord.Option(description=_("Month (e.g., 07 or July)"), autocomplete=schedule_month_select),
                              year: str = discord.Option(description=_("Year (e.g., 2024)"), autocomplete=schedule_year_select)):
        """Schedules a one-time task for a Docker container."""
        await self._impl_schedule_once_command(ctx, container_name, action, time, day, month, year)
    
    @commands.slash_command(name="task_daily", description=_("Schedule a daily task"), guild_ids=get_guild_id())
    async def schedule_daily_command(self, ctx: discord.ApplicationContext,
                              container_name: str = discord.Option(description=_("The Docker container to schedule"), autocomplete=container_select),
                              action: str = discord.Option(description=_("Action to perform"), autocomplete=schedule_action_select),
                              time: str = discord.Option(description=_("Time in HH:MM format (e.g., 08:00)"), autocomplete=schedule_time_select)):
        """Schedules a daily task for a Docker container."""
        await self._impl_schedule_daily_command(ctx, container_name, action, time)
    
    @commands.slash_command(name="task_weekly", description=_("Schedule a weekly task"), guild_ids=get_guild_id())
    async def schedule_weekly_command(self, ctx: discord.ApplicationContext, 
                              container_name: str = discord.Option(description=_("The Docker container to schedule"), autocomplete=container_select),
                              action: str = discord.Option(description=_("Action to perform"), autocomplete=schedule_action_select),
                              time: str = discord.Option(description=_("Time in HH:MM format"), autocomplete=schedule_time_select),
                              weekday: str = discord.Option(description=_("Day of the week (e.g., Monday or 1)"), autocomplete=schedule_weekday_select)):
        """Schedules a weekly task for a Docker container."""
        await self._impl_schedule_weekly_command(ctx, container_name, action, time, weekday)
    
    @commands.slash_command(name="task_monthly", description=_("Schedule a monthly task"), guild_ids=get_guild_id())
    async def schedule_monthly_command(self, ctx: discord.ApplicationContext, 
                              container_name: str = discord.Option(description=_("The Docker container to schedule"), autocomplete=container_select),
                              action: str = discord.Option(description=_("Action to perform"), autocomplete=schedule_action_select),
                              time: str = discord.Option(description=_("Time in HH:MM format"), autocomplete=schedule_time_select),
                              day: str = discord.Option(description=_("Day of the month (1-31)"), autocomplete=schedule_day_select)):
        """Schedules a monthly task for a Docker container."""
        await self._impl_schedule_monthly_command(ctx, container_name, action, time, day)
    
    @commands.slash_command(name="task_yearly", description=_("Schedule a yearly task"), guild_ids=get_guild_id())
    async def schedule_yearly_command(self, ctx: discord.ApplicationContext, 
                              container_name: str = discord.Option(description=_("The Docker container to schedule"), autocomplete=container_select),
                              action: str = discord.Option(description=_("Action to perform"), autocomplete=schedule_action_select),
                              time: str = discord.Option(description=_("Time in HH:MM format"), autocomplete=schedule_time_select),
                              month: str = discord.Option(description=_("Month (e.g., 07 or July)"), autocomplete=schedule_month_select),
                              day: str = discord.Option(description=_("Day of month (e.g., 15)"), autocomplete=schedule_day_select)):
        """Schedules a yearly task for a Docker container."""
        await self._impl_schedule_yearly_command(ctx, container_name, action, time, month, day)
    
    @commands.slash_command(name="task", description=_("Shows task command help"), guild_ids=get_guild_id())
    async def schedule_command(self, ctx: discord.ApplicationContext):
        """Shows help for the various scheduling commands."""
        await self._impl_schedule_command(ctx)
    
    @commands.slash_command(name="task_info", description=_("Shows information about scheduled tasks"), guild_ids=get_guild_id())
    async def schedule_info_command(self, ctx: discord.ApplicationContext,
                                  container_name: str = discord.Option(description=_("Container name (or 'all')"), default="all", autocomplete=container_select),
                                  period: str = discord.Option(description=_("Time period (e.g., next_week)"), default="all", autocomplete=schedule_info_period_select)):
        """Shows information about scheduled tasks."""
        await self._impl_schedule_info_command(ctx, container_name, period)

    @commands.slash_command(name="task_delete", description=_("Delete a scheduled task"), guild_ids=get_guild_id())
    async def schedule_delete_command(self, ctx: discord.ApplicationContext,
                                    task_id: str = discord.Option(description=_("Task ID to delete"), autocomplete=schedule_task_id_select)):
        """Deletes a scheduled task."""
        await self._impl_schedule_delete_command(ctx, task_id)

    @commands.slash_command(name="task_delete_panel", description=_("Show active tasks with delete buttons"), guild_ids=get_guild_id())
    async def task_delete_panel_command(self, ctx: discord.ApplicationContext):
        """Shows a panel with all active tasks and delete buttons for each."""
        await self._impl_task_delete_panel_command(ctx)

    # --- SCHEDULE COMMANDS MOVED TO scheduler_commands.py ---
    # All schedule related implementation logic has been moved to 
    # the ScheduleCommandsMixin class in scheduler_commands.py.
    # The command definitions remain here in DockerControlCog for proper registration,
    # but they delegate their actual implementation to methods in the mixin.
    # This includes the following implementation methods:
    # - _format_schedule_embed
    # - _create_scheduled_task
    # - _impl_schedule_once_command
    # - _impl_schedule_daily_command
    # - _impl_schedule_weekly_command
    # - _impl_schedule_monthly_command
    # - _impl_schedule_yearly_command
    # - _impl_schedule_command
    # - _impl_schedule_info_command

    # Implementation for schedule_delete command (implemented directly in Cog)
    async def _impl_schedule_delete_command(self, ctx: discord.ApplicationContext, task_id: str):
        """Deletes a scheduled task."""
        try:
            # Check channel permissions
            if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
                await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
                return
            
            config = self.config
            if not _channel_has_permission(ctx.channel.id, 'schedule', config):
                await ctx.respond(_("You do not have permission to use schedule commands in this channel."), ephemeral=True)
                return
            
            # Import necessary scheduler functions
            from utils.scheduler import load_tasks, delete_task
            from utils.action_logger import log_user_action
            
            # Find the task
            all_tasks = load_tasks()
            task_to_delete = None
            
            for task in all_tasks:
                if task.task_id == task_id:
                    task_to_delete = task
                    break
            
            if not task_to_delete:
                await ctx.respond(_("Task with ID '{task_id}' not found.").format(task_id=task_id), ephemeral=True)
                return
            
            # Delete the task - only channel-level permissions matter
            if delete_task(task_id):
                # Log the action
                log_user_action(
                    action="SCHEDULE_DELETE_CMD", 
                    target=f"{task_to_delete.container_name} ({task_to_delete.action})", 
                    user=str(ctx.author),
                    source="Discord Command",
                    details=f"Deleted task: {task_id}, Cycle: {task_to_delete.cycle}"
                )
                
                await ctx.respond(_("✅ Successfully deleted scheduled task!\n**Task ID:** {task_id}\n**Container:** {container}\n**Action:** {action}\n**Cycle:** {cycle}").format(
                    task_id=task_id,
                    container=task_to_delete.container_name,
                    action=task_to_delete.action,
                    cycle=task_to_delete.cycle
                ), ephemeral=True)
            else:
                await ctx.respond(_("❌ Failed to delete task. The task might not exist or there was an error."), ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error executing schedule_delete command: {e}", exc_info=True)
            await ctx.respond(_("An error occurred: {error}").format(error=str(e)), ephemeral=True)

    async def _impl_task_delete_panel_command(self, ctx: discord.ApplicationContext):
        """Shows a panel with all active tasks and delete buttons for each."""
        try:
            # Check channel permissions
            if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
                await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
                return
            
            config = self.config
            if not _channel_has_permission(ctx.channel.id, 'schedule', config):
                await ctx.respond(_("You do not have permission to use task commands in this channel."), ephemeral=True)
                return
            
            # Import necessary scheduler functions
            from utils.scheduler import load_tasks, CYCLE_ONCE
            from .control_ui import TaskDeletePanelView
            import time
            
            # Load all tasks
            all_tasks = load_tasks()
            if not all_tasks:
                await ctx.respond(_("📅 **Task Delete Panel**\n\nNo scheduled tasks found."), ephemeral=True)
                return
            
            # Filter to only active tasks
            current_time = time.time()
            active_tasks = []
            
            for task in all_tasks:
                # Skip inactive tasks
                if not task.is_active:
                    continue
                    
                # Skip expired one-time tasks
                if task.cycle == CYCLE_ONCE:
                    if task.next_run_ts is None or task.next_run_ts < current_time:
                        continue
                    if getattr(task, 'status', None) == "completed":
                        continue
                
                # Add all active tasks - permission check will be done during deletion
                active_tasks.append(task)
            
            if not active_tasks:
                await ctx.respond(_("📅 **Task Delete Panel**\n\nNo active tasks found."), ephemeral=True)
                return
            
            # Create simple header message (no task list needed since buttons contain task info)
            message_content = f"📅 **{_('Task Delete Panel')}**\n\n{_('Click any button below to delete the corresponding task:')}"
            
            # Add explanation of abbreviations
            message_content += f"\n\n**{_('Legend:** O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly')}"
            
            # Add footer information  
            if len(active_tasks) > 25:
                message_content += f"\n\n_({_('Showing first 25 of {total} tasks').format(total=len(active_tasks))})_"
            else:
                message_content += f"\n\n_({_('Found {total} active tasks').format(total=len(active_tasks))})_"
            
            # Create view with delete buttons
            view = TaskDeletePanelView(self, active_tasks)
            
            # Send the panel as normal message
            await ctx.respond(message_content, view=view, ephemeral=False)
            logger.info(f"Task delete panel shown to {ctx.author} with {len(active_tasks)} active tasks")
            
        except Exception as e:
            logger.error(f"Error executing task_delete_panel command: {e}", exc_info=True)
            await ctx.respond(_("An error occurred: {error}").format(error=str(e)), ephemeral=True)

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
            
            # Create the updated embed
            embed = await self._create_overview_embed(ordered_servers, config)
            
            # Update the message
            await message.edit(embed=embed)
            
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
            
        except Exception as e:
            logger.error(f"Error updating overview message in channel {channel_id}: {e}", exc_info=True)
            return False