# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Module containing status handler functions for Docker containers.
These are implemented as a mixin class to be used with the main DockerControlCog.
"""
import logging
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union
import discord

# Import necessary utilities
from utils.logging_utils import get_module_logger
from services.infrastructure.container_status_service import get_docker_info_dict_service_first, get_docker_stats_service_first
from utils.time_utils import format_datetime_with_timezone
from services.config.server_config_service import get_server_config_service
from services.docker_status import get_performance_service, get_fetch_service, ContainerStatusResult
from services.discord import get_conditional_cache_service, get_embed_helper_service

# Import helper functions
from .control_helpers import _channel_has_permission, _get_pending_embed
from .control_ui import ControlView

# Import translation function
from .translation_manager import _

# Configure logger for this module
logger = get_module_logger('status_handlers')

class StatusHandlersMixin:
    """
    Mixin class containing status handler functionality for DockerControlCog.
    Handles retrieving, processing, and displaying Docker container statuses.
    """

    async def bulk_fetch_container_status(self, container_names: List[str]) -> Dict[str, ContainerStatusResult]:
        """
        Intelligent bulk fetch with adaptive performance learning and complete data collection.
        Uses performance history to optimize timeouts and batching while always collecting full details.

        Args:
            container_names: List of Docker container names to fetch

        Returns:
            Dict mapping container_name -> ContainerStatusResult
        """
        if not container_names:
            return {}

        # DOCKER CONNECTIVITY CHECK: Abort early if Docker is not accessible
        from services.infrastructure.docker_connectivity_service import get_docker_connectivity_service, DockerConnectivityRequest

        connectivity_service = get_docker_connectivity_service()
        connectivity_request = DockerConnectivityRequest(timeout_seconds=5.0)
        connectivity_result = await connectivity_service.check_connectivity(connectivity_request)

        if not connectivity_result.is_connected:
            logger.error(f"[INTELLIGENT_BULK_FETCH] Docker connectivity failed: {connectivity_result.error_message}")

            # Return error status for all requested containers
            error_results = {}
            for docker_name in container_names:
                # Create an exception with the connectivity error details
                error_exception = RuntimeError(f"Docker connectivity error: {connectivity_result.error_message}")
                error_results[docker_name] = ContainerStatusResult.error_result(
                    docker_name=docker_name,
                    error=error_exception,
                    error_type='connectivity'
                )

            return error_results

        start_time = time.time()
        logger.info(f"[INTELLIGENT_BULK_FETCH] Starting adaptive bulk fetch for {len(container_names)} containers")

        # Classify containers by performance history for intelligent batching
        perf_service = get_performance_service()
        classification = perf_service.classify_containers(container_names)
        fast_containers = classification.fast_containers
        slow_containers = classification.slow_containers
        
        if fast_containers and slow_containers:
            logger.info(f"[INTELLIGENT_BULK_FETCH] Smart batching: {len(fast_containers)} fast, {len(slow_containers)} slow containers")
        elif slow_containers:
            logger.info(f"[INTELLIGENT_BULK_FETCH] All {len(slow_containers)} containers classified as slow - using patient processing")
        else:
            logger.info(f"[INTELLIGENT_BULK_FETCH] All {len(fast_containers)} containers classified as fast - using parallel processing")
        
        # Process containers with intelligent strategies
        all_results = []
        
        # Phase 1: Process fast containers in parallel (if any)
        if fast_containers:
            logger.debug(f"[INTELLIGENT_BULK_FETCH] Phase 1: Processing {len(fast_containers)} fast containers in parallel")
            
            # Use semaphore for controlled concurrency
            MAX_CONCURRENT_FAST = min(3, len(fast_containers))  # Max 3 concurrent to match Docker pool capacity
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_FAST)
            
            async def fetch_fast_container(container_name):
                async with semaphore:
                    fetch_service = get_fetch_service()
                    return await fetch_service.fetch_with_retries(container_name)
            
            fast_tasks = [fetch_fast_container(name) for name in fast_containers]
            fast_results = await asyncio.gather(*fast_tasks, return_exceptions=True)
            all_results.extend(fast_results)
            
            fast_time = (time.time() - start_time) * 1000
            logger.info(f"[INTELLIGENT_BULK_FETCH] Phase 1 completed: {len(fast_containers)} fast containers in {fast_time:.1f}ms")
        
        # Phase 2: Process slow containers individually with patience (if any)
        if slow_containers:
            phase2_start = time.time()
            logger.debug(f"[INTELLIGENT_BULK_FETCH] Phase 2: Processing {len(slow_containers)} slow containers individually")

            for i, container_name in enumerate(slow_containers):
                fetch_service = get_fetch_service()
                result = await fetch_service.fetch_with_retries(container_name)
                all_results.append(result)
                # No per-container logging - only log phase completion to avoid spam
            
            slow_time = (time.time() - phase2_start) * 1000
            logger.info(f"[INTELLIGENT_BULK_FETCH] Phase 2 completed: {len(slow_containers)} slow containers in {slow_time:.1f}ms")
        
        # PERFORMANCE: Cache server configs before processing - avoid repeated lookups
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()
        servers_by_docker_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}

        # Process all results into status tuples - ALWAYS WITH COMPLETE DATA
        status_results = {}
        successful_fetches = 0
        failed_fetches = 0

        for result in all_results:
            if isinstance(result, Exception):
                logger.error(f"[INTELLIGENT_BULK_FETCH] Exception in fetch result: {result}")
                failed_fetches += 1
                continue

            docker_name, info, stats = result

            # Find server config for this container (cached lookup)
            server_config = servers_by_docker_name.get(docker_name)
            
            if not server_config:
                logger.warning(f"[INTELLIGENT_BULK_FETCH] No server config found for {docker_name}")
                failed_fetches += 1
                continue
            
            # Process the fetched data - ALWAYS COMPLETE DETAILS
            display_name = server_config.get('name', docker_name)
            details_allowed = server_config.get('allow_detailed_status', True)
            
            if isinstance(info, Exception) or info is None:
                # Container offline or error - still provide complete status structure
                logger.debug(f"[INTELLIGENT_BULK_FETCH] {docker_name} appears offline or error: {info}")
                status_results[docker_name] = ContainerStatusResult.offline_result(
                    docker_name=docker_name,
                    display_name=display_name,
                    details_allowed=details_allowed
                )
                successful_fetches += 1  # Still a successful status determination
                continue
            
            # Process container info - COMPLETE DATA COLLECTION
            is_running = info.get('State', {}).get('Running', False)
            uptime = "N/A"
            cpu = "N/A"
            ram = "N/A"
            
            if is_running:
                # Calculate uptime from container start time
                started_at_str = info.get('State', {}).get('StartedAt')
                if started_at_str:
                    try:
                        started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc)
                        delta = now - started_at
                        
                        days = delta.days
                        hours, remainder = divmod(delta.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        uptime_parts = []
                        if days > 0:
                            uptime_parts.append(f"{days}d")
                        if hours > 0:
                            uptime_parts.append(f"{hours}h")
                        if minutes > 0 or (days == 0 and hours == 0):
                            uptime_parts.append(f"{minutes}m")
                        uptime = " ".join(uptime_parts) if uptime_parts else "< 1m"
                    except ValueError as e:
                        logger.error(f"[INTELLIGENT_BULK_FETCH] Could not parse StartedAt for {docker_name}: {e}")
                        uptime = "Error"
                
                # Process stats - ALWAYS COLLECT IF ALLOWED (never skip for performance)
                if details_allowed:
                    # Try to get computed values from new SERVICE FIRST format first
                    if info and '_computed' in info:
                        computed = info['_computed']
                        cpu = f"{computed['cpu_percent']:.1f}%" if computed['cpu_percent'] is not None else 'N/A'
                        ram = f"{computed['memory_usage_mb']:.0f}MB" if computed['memory_usage_mb'] is not None else 'N/A'
                        # Use uptime from SERVICE FIRST if available
                        if computed['uptime_seconds'] > 0:
                            uptime_sec = computed['uptime_seconds']
                            days = uptime_sec // 86400
                            hours = (uptime_sec % 86400) // 3600
                            minutes = (uptime_sec % 3600) // 60
                            uptime_parts = []
                            if days > 0:
                                uptime_parts.append(f"{days}d")
                            if hours > 0:
                                uptime_parts.append(f"{hours}h")
                            if minutes > 0 or (days == 0 and hours == 0):
                                uptime_parts.append(f"{minutes}m")
                            uptime = " ".join(uptime_parts) if uptime_parts else "< 1m"
                    # Fallback to old stats method if SERVICE FIRST data not available
                    elif not isinstance(stats, Exception) and stats:
                        cpu_stat, ram_stat = stats
                        cpu = cpu_stat if cpu_stat is not None else 'N/A'
                        ram = ram_stat if ram_stat is not None else 'N/A'
                    else:
                        # No stats available
                        pass  # Keep N/A values set above
                elif not details_allowed:
                    cpu = _("Hidden")
                    ram = _("Hidden")
                # If details allowed but stats failed, keep N/A (we tried!)

            status_results[docker_name] = ContainerStatusResult.success_result(
                docker_name=docker_name,
                display_name=display_name,
                is_running=is_running,
                cpu=cpu,
                ram=ram,
                uptime=uptime,
                details_allowed=details_allowed
            )
            successful_fetches += 1
        
        total_elapsed = (time.time() - start_time) * 1000
        
        # Enhanced performance reporting
        success_rate = (successful_fetches / len(container_names)) * 100 if container_names else 0
        
        if total_elapsed > 60000:  # Over 1 minute
            logger.info(f"[INTELLIGENT_BULK_FETCH] Completed adaptive fetch in {total_elapsed:.1f}ms: "
                       f"{successful_fetches}/{len(container_names)} successful ({success_rate:.1f}%), "
                       f"{failed_fetches} failed. Patient processing for complete data.")
        elif total_elapsed > 30000:  # Over 30 seconds
            logger.info(f"[INTELLIGENT_BULK_FETCH] Completed adaptive fetch in {total_elapsed:.1f}ms: "
                       f"{successful_fetches}/{len(container_names)} successful ({success_rate:.1f}%)")
        else:
            logger.info(f"[INTELLIGENT_BULK_FETCH] Fast adaptive fetch completed in {total_elapsed:.1f}ms: "
                       f"{successful_fetches}/{len(container_names)} containers with complete data")

        return status_results

    async def bulk_update_status_cache(self, container_names: List[str]):
        """
        Updates the status cache for multiple containers using bulk fetching.
        Optimized to work with 30-second background status_update_loop.
        """
        if not container_names:
            return
        
        # PERFORMANCE OPTIMIZATION: Only update completely missing cache entries
        # The 30-second status_update_loop handles regular cache updates
        now = datetime.now(timezone.utc)
        containers_needing_update = []
        
        # Pre-process server configurations
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()
        servers_by_docker_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
        
        for docker_name in container_names:
            server_config = servers_by_docker_name.get(docker_name)
            if not server_config:
                continue

            # CRITICAL: Use docker_name as cache key (not display_name!)
            cached_entry = self.status_cache_service.get(docker_name)

            # ONLY update if cache is completely missing (not just stale)
            # Background loop handles regular updates every 30s
            if not cached_entry:
                containers_needing_update.append(docker_name)

        if not containers_needing_update:
            # All containers cached - silent return (this is the expected happy path)
            return
        
        logger.info(f"[BULK_UPDATE] Updating cache for {len(containers_needing_update)}/{len(container_names)} containers with missing cache")
        
        try:
            # Bulk fetch only the containers with no cache
            bulk_results = await self.bulk_fetch_container_status(containers_needing_update)
            
            # Update cache with results
            for docker_name, result in bulk_results.items():
                server_config = servers_by_docker_name.get(docker_name)
                if server_config:
                    display_name = server_config.get('name', docker_name)
                    if result.success:
                        # CRITICAL: Cache with docker_name as key (not display_name!)
                        self.status_cache_service.set(docker_name, result, now)
                    else:
                        # CRITICAL: Cache error with docker_name as key (not display_name!)
                        self.status_cache_service.set_error(docker_name, result.error or Exception(result.error_message))
                        logger.warning(f"[BULK_UPDATE] Failed to update {display_name}: {result.error_message}")
        except (RuntimeError, asyncio.CancelledError, KeyError, TypeError) as e:
            logger.error(f"[BULK_UPDATE] Error during bulk update: {e}", exc_info=True)

    async def get_status(self, server_config: Dict[str, Any]) -> ContainerStatusResult:
        """
        Gets the status of a server.
        Returns: ContainerStatusResult object with all status information
        """
        docker_name = server_config.get('docker_name')

        # Handle display_name - could be a string or list (legacy format)
        display_name_raw = server_config.get('display_name', docker_name)
        if isinstance(display_name_raw, list):
            display_name = display_name_raw[0] if len(display_name_raw) > 0 else docker_name
        else:
            display_name = display_name_raw if display_name_raw else docker_name

        details_allowed = server_config.get('allow_detailed_status', True) # Default to True if not set

        if not docker_name:
            return ContainerStatusResult.error_result(
                docker_name="unknown",
                error=ValueError(_("Missing docker_name in server configuration")),
                error_type='config_error'
            )

        try:
            info = await get_docker_info_dict_service_first(docker_name)

            if not info:
                # Container does not exist or Docker daemon is unreachable
                logger.warning(f"Container info not found for {docker_name}. Assuming offline.")
                return ContainerStatusResult.offline_result(
                    docker_name=docker_name,
                    display_name=display_name,
                    details_allowed=details_allowed
                )

            is_running = info.get('State', {}).get('Running', False)
            uptime = "N/A"
            cpu = "N/A"
            ram = "N/A"

            if is_running:
                # Calculate uptime (requires the start date)
                started_at_str = info.get('State', {}).get('StartedAt')
                if started_at_str:
                    try:
                        # Adjust Docker time format (ISO 8601 with nanoseconds and Z)
                        started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc)
                        delta = now - started_at

                        days = delta.days
                        hours, remainder = divmod(delta.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        uptime_parts = []
                        if days > 0:
                            uptime_parts.append(f"{days}d")
                        if hours > 0:
                            uptime_parts.append(f"{hours}h")
                        if minutes > 0 or (days == 0 and hours == 0):
                            uptime_parts.append(f"{minutes}m")
                        uptime = " ".join(uptime_parts) if uptime_parts else "< 1m"

                    except ValueError as e:
                        logger.error(f"Could not parse StartedAt timestamp '{started_at_str}' for {docker_name}: {e}")
                        uptime = "Error"

                # Fetch CPU and RAM only if allowed (SERVICE FIRST)
                if details_allowed:
                    stats_dict = await get_docker_stats_service_first(docker_name)
                    if stats_dict and isinstance(stats_dict, dict):
                        cpu_percent = stats_dict.get('cpu_percent', 0.0)
                        memory_mb = stats_dict.get('memory_usage_mb', 0.0)
                        cpu = f"{cpu_percent:.1f}%" if cpu_percent is not None else 'N/A'
                        ram = f"{memory_mb:.1f} MB" if memory_mb is not None else 'N/A'
                    else:
                        logger.warning(f"Could not retrieve valid stats dict for running container {docker_name}")
                        cpu = "N/A"
                        ram = "N/A"
                else:
                    cpu = _("Hidden")
                    ram = _("Hidden")

            return ContainerStatusResult.success_result(
                docker_name=docker_name,
                display_name=display_name,
                is_running=is_running,
                cpu=cpu,
                ram=ram,
                uptime=uptime,
                details_allowed=details_allowed
            )

        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error getting status for {docker_name}: {e}", exc_info=True)
            return ContainerStatusResult.error_result(
                docker_name=docker_name,
                error=e,
                error_type=type(e).__name__.lower()
            )
    
    async def _generate_status_embed_and_view(self, channel_id: int, display_name: str,
                                       server_conf: Dict[str, Any], current_config: Dict[str, Any],
                                       allow_toggle: bool = True,
                                       force_collapse: bool = False,
                                       show_cache_age: bool = False) -> Tuple[discord.Embed, Optional[discord.ui.View], bool]:
        """
        Generates the status embed and view based on cache and settings.
        Returns: (embed, view, running_status)
        
        Parameters:
        - channel_id: The ID of the channel where the embed will be displayed
        - display_name: The display name of the server to show
        - server_conf: The configuration of the specific server
        - current_config: The full bot configuration
        - allow_toggle: Whether to allow the toggle button in the view
        - force_collapse: Whether to force the status to be collapsed
        - show_cache_age: Whether to show cache age indicator (for debug/serverstatus)
        """
        lang = current_config.get('language', 'de')
        # Get timezone from config (format_datetime_with_timezone will handle fallbacks)
        timezone_str = current_config.get('timezone_str', 'Europe/Berlin')
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        all_servers_config = server_config_service.get_all_servers()

        # Silent embed generation - this is called very frequently
        embed = None
        view = None
        running = False # Default running state
        status_result = None

        # IMPORTANT: Use docker_name for all internal lookups (cache, pending_actions, etc.)
        # display_name is ONLY for display purposes!
        docker_name = server_conf.get('docker_name') or server_conf.get('name')
        if not docker_name:
            logger.error(f"[_GEN_EMBED] No docker_name found in server_conf for display_name '{display_name}'!")
            docker_name = display_name  # Fallback to display_name if no docker_name available

        cached_entry = self.status_cache_service.get(docker_name)
        now = datetime.now(timezone.utc)

        # --- Check for pending action first --- (Moved before status_result processing)
        if docker_name in self.pending_actions:
            pending_data = self.pending_actions[docker_name]
            pending_timestamp = pending_data['timestamp']
            pending_action = pending_data['action']
            pending_duration = (now - pending_timestamp).total_seconds()

            # IMPROVED: Longer timeout and smarter pending logic
            PENDING_TIMEOUT_SECONDS = 120  # 2 minutes timeout instead of 15 seconds

            if pending_duration < PENDING_TIMEOUT_SECONDS:
                # Silent pending state - this is expected behavior
                embed = _get_pending_embed(display_name) # Uses a standardized pending embed
                return embed, None, False # No view, running status is effectively false for pending display
            else:
                # IMPROVED: Smart timeout - check if container status actually changed based on action
                logger.info(f"[_GEN_EMBED] '{display_name}' pending timeout reached ({pending_duration:.1f}s). Checking if {pending_action} action succeeded...")
                
                # Try to get current container status to see if it changed
                current_server_conf_for_check = next((s for s in all_servers_config if s.get('docker_name') == docker_name), None)
                if current_server_conf_for_check:
                    fresh_status = await self.get_status(current_server_conf_for_check)
                    if fresh_status.success:
                        current_running_state = fresh_status.is_running
                        
                        # ACTION-AWARE SUCCESS DETECTION
                        action_succeeded = False
                        if pending_action == 'start':
                            # Start succeeds when container is running
                            action_succeeded = current_running_state
                        elif pending_action == 'stop':
                            # Stop succeeds when container is NOT running
                            action_succeeded = not current_running_state
                        elif pending_action == 'restart':
                            # Restart succeeds when container is running (after stop+start cycle)
                            action_succeeded = current_running_state
                        
                        if action_succeeded:
                            logger.info(f"[_GEN_EMBED] '{display_name}' {pending_action} action succeeded - clearing pending state")
                            del self.pending_actions[docker_name]
                            # Update cache with fresh status (ContainerStatusResult)
                            self.status_cache_service.set(docker_name, fresh_status, now)
                        else:
                            # Action might have failed or container takes very long
                            logger.warning(f"[_GEN_EMBED] '{display_name}' {pending_action} action did not succeed after {pending_duration:.1f}s timeout - clearing pending state")
                            del self.pending_actions[docker_name]
                    else:
                        logger.warning(f"[_GEN_EMBED] '{display_name}' pending timeout - could not get fresh status, clearing pending state")
                        del self.pending_actions[docker_name]
                else:
                    logger.warning(f"[_GEN_EMBED] '{display_name}' pending timeout - no server config found, clearing pending state")
                    del self.pending_actions[docker_name]

        # --- Determine status_result (from cache or live) ---
        if cached_entry:
            cache_age = (now - cached_entry['timestamp']).total_seconds()
            # PATIENT APPROACH: ALWAYS use cache if available - background collects fresh data
            # Show cache age when data is older so user knows freshness
            if cache_age < self.cache_ttl_seconds:
                cache_age_indicator = ""  # No indicator for fresh data
            else:
                # Add age indicator for older data
                if cache_age < 120:  # Less than 2 minutes
                    cache_age_indicator = f" ({int(cache_age)}s ago)"
                elif cache_age < 3600:  # Less than 1 hour
                    cache_age_indicator = f" ({int(cache_age/60)}m ago)"
                else:
                    cache_age_indicator = f" ({int(cache_age/3600)}h ago)"
            
            status_result = cached_entry['data']
            # Store cache age for later use in embed
            embed_cache_age = cache_age
            embed_cache_indicator = cache_age_indicator
        else:
            # ONLY fetch directly if absolutely no cache exists (rare case during startup)
            logger.info(f"[_GEN_EMBED] No cache entry for '{docker_name}' (display: '{display_name}'). This should be rare - background loop will populate cache...")
            current_server_conf_for_fetch = next((s for s in all_servers_config if s.get('docker_name') == docker_name), None)
            if current_server_conf_for_fetch:
                # EMERGENCY FALLBACK: Show loading status instead of blocking UI
                logger.info(f"[_GEN_EMBED] Showing loading status for '{display_name}' while background fetches data")
                status_result = None  # Will trigger loading display
                embed_cache_age = 0
                embed_cache_indicator = " (loading...)"
            else:
                logger.warning(f"[_GEN_EMBED] No server configuration found for '{display_name}' during emergency fetch. status_result remains None.")
                status_result = None
                embed_cache_age = 0
                embed_cache_indicator = " (config error)"

        # --- Process status_result and generate embed ---
        # Cache now stores ContainerStatusResult objects
        if status_result is None:
            # Check if we have cache age indicator to determine type of message
            if 'embed_cache_indicator' in locals() and 'loading' in embed_cache_indicator:
                # Loading status
                embed = discord.Embed(
                    description="```\n┌── Loading Status ───────────\n│ 🔄 Fetching container data...\n│ ⏱️ Background process running\n│ 📊 Please wait for fresh data\n└─────────────────────────────\n```",
                    color=0x3498db
                )
                embed.set_footer(text="Background data collection in progress • https://ddc.bot")
            else:
                # Error status
                embed = discord.Embed(
                    title=f"⚠️ {display_name}", 
                    description=_("Error: Could not retrieve status. Configuration missing or initial fetch failed."), 
                    color=discord.Color.red()
                )
            # running remains False, view remains None

        elif isinstance(status_result, ContainerStatusResult):
            # --- Handle ContainerStatusResult objects (new cache format) ---
            if not status_result.success:
                logger.error(f"[_GEN_EMBED] Status for '{display_name}' failed: {status_result.error_message}", exc_info=False)
                embed = discord.Embed(
                    title=f"⚠️ {display_name}",
                    description=_("Error: An exception occurred while fetching status. Background process will retry."),
                    color=discord.Color.red()
                )
                # running remains False, view remains None
            else:
                # Successful result - extract fields for embed generation
                display_name_from_status = status_result.display_name
                running = status_result.is_running
                cpu = status_result.cpu
                ram = status_result.ram
                uptime = status_result.uptime
                details_allowed = status_result.details_allowed
                status_color = 0x00b300 if running else 0xe74c3c

                # Continue with box embed generation (same as tuple case)
                # PERFORMANCE OPTIMIZATION: Use cached translations
                embed_helper = get_embed_helper_service()
                cached_translations = embed_helper.get_translations(lang)
                online_text = cached_translations['online_text']
                offline_text = cached_translations['offline_text']
                status_text = online_text if running else offline_text
                current_emoji = "🟢" if running else "🔴"

                # Check if we should always collapse
                is_expanded = self.expanded_states.get(display_name, False) and not force_collapse

                # PERFORMANCE OPTIMIZATION: Use cached translations
                cpu_text = cached_translations['cpu_text']
                ram_text = cached_translations['ram_text']
                uptime_text = cached_translations['uptime_text']
                detail_denied_text = cached_translations['detail_denied_text']

                # PERFORMANCE OPTIMIZATION: Use cached box elements
                BOX_WIDTH = 28
                embed_helper = get_embed_helper_service()
                cached_box = embed_helper.get_box_elements(display_name, BOX_WIDTH)
                header_line = cached_box['header_line']
                footer_line = cached_box['footer_line']

                # String builder for description - more efficient than multiple concatenations
                description_parts = [
                    "```\n",
                    header_line,
                    f"\n│ {current_emoji} {status_text}"
                ]

                # Add cache age indicator if data is older (only if show_cache_age is True)
                if show_cache_age and 'embed_cache_indicator' in locals() and embed_cache_indicator:
                    description_parts.append(embed_cache_indicator)

                description_parts.append("\n")

                # Build status box content
                if running and details_allowed:
                    if is_expanded:
                        description_parts.extend([
                            f"│ {cpu_text}: {cpu}\n",
                            f"│ {ram_text}: {ram}\n",
                            f"│ {uptime_text}: {uptime}\n"
                        ])
                    else:
                        description_parts.append(f"│ \u2022 ▼ Expand for details\n")
                elif running and not details_allowed:
                    description_parts.append(f"│ {detail_denied_text}\n")
                elif not running:
                    description_parts.append(f"│ {uptime_text}: N/A\n")

                description_parts.extend([
                    footer_line,
                    "\n```"
                ])

                embed = discord.Embed(
                    description="".join(description_parts),
                    color=status_color
                )
                embed.set_footer(text="https://ddc.bot")

                # Create view with toggle button only if allowed and container is running and has details
                if allow_toggle and running and details_allowed:
                    view = ControlView(
                        self, server_conf, is_running=running,
                        channel_has_control_permission=_channel_has_permission(channel_id, server_conf)
                    )
                else:
                    view = None

        elif isinstance(status_result, Exception):
            logger.error(f"[_GEN_EMBED] Status for '{display_name}' is an exception: {status_result}", exc_info=False)
            embed = discord.Embed(
                title=f"⚠️ {display_name}",
                description=_("Error: An exception occurred while fetching status. Background process will retry."),
                color=discord.Color.red()
            )
            # running remains False, view remains None

        elif isinstance(status_result, tuple) and len(status_result) == 6:
            # --- Valid Data: Generate Box Embed with Cache Age Info ---
            display_name_from_status, running, cpu, ram, uptime, details_allowed = status_result # 'running' is updated here
            status_color = 0x00b300 if running else 0xe74c3c
            
            # PERFORMANCE OPTIMIZATION: Use cached translations
            embed_helper = get_embed_helper_service()
            cached_translations = embed_helper.get_translations(lang)
            online_text = cached_translations['online_text']
            offline_text = cached_translations['offline_text']
            status_text = online_text if running else offline_text
            current_emoji = "🟢" if running else "🔴"

            # Check if we should always collapse
            is_expanded = self.expanded_states.get(display_name, False) and not force_collapse

            # PERFORMANCE OPTIMIZATION: Use cached translations
            cpu_text = cached_translations['cpu_text']
            ram_text = cached_translations['ram_text']
            uptime_text = cached_translations['uptime_text']
            detail_denied_text = cached_translations['detail_denied_text']
            
            # PERFORMANCE OPTIMIZATION: Use cached box elements
            BOX_WIDTH = 28
            embed_helper = get_embed_helper_service()
            cached_box = embed_helper.get_box_elements(display_name, BOX_WIDTH)
            header_line = cached_box['header_line']
            footer_line = cached_box['footer_line']
            
            # String builder for description - more efficient than multiple concatenations
            description_parts = [
                "```\n",
                header_line,
                f"\n│ {current_emoji} {status_text}"
            ]

            # Add cache age indicator if data is older (only if show_cache_age is True)
            if show_cache_age and 'embed_cache_indicator' in locals() and embed_cache_indicator:
                description_parts.append(embed_cache_indicator)

            # Add different lines depending on status and state
            if running:
                if details_allowed and is_expanded:
                    description_parts.extend([
                        f"\n│ {cpu_text}: {cpu}",
                        f"\n│ {ram_text}: {ram}",
                        f"\n│ {uptime_text}: {uptime}",
                        f"\n{footer_line}"
                    ])
                elif not details_allowed and is_expanded:
                    description_parts.extend([
                        f"\n│ ⚠️ *{detail_denied_text}*",
                        f"\n│ {uptime_text}: {uptime}",
                        f"\n{footer_line}"
                    ])
                else:
                    description_parts.append(f"\n{footer_line}")
            else:  # Offline
                description_parts.append(f"\n{footer_line}")
            
            description_parts.append("\n```")
            
            # Combine description
            description = "".join(description_parts)

            # Use passed config
            current_server_conf = next((s for s in all_servers_config if s.get('docker_name') == server_conf.get('docker_name')), None)
            has_control_rights = False
            if current_server_conf:
                has_control_rights = any(action in current_server_conf.get('allowed_actions', []) for action in ["start", "stop", "restart"])

            if not running and not details_allowed and not has_control_rights:
                description += f"\n⚠️ *{detail_denied_text}*"

            embed = discord.Embed(description=description, color=status_color)
            now_footer = datetime.now(timezone.utc)
            last_update_text = cached_translations['last_update_text']
            # Get formatted time using the new time_only parameter
            current_time = format_datetime_with_timezone(now_footer, timezone_str, time_only=True)
            
            # Enhanced timestamp with cache age info
            if 'embed_cache_age' in locals() and embed_cache_age > self.cache_ttl_seconds:
                timestamp_line = f"{last_update_text}: {current_time} (data: {int(embed_cache_age)}s alt)"
            else:
                timestamp_line = f"{last_update_text}: {current_time}"
            
            embed.description = f"{timestamp_line}\n{description}" # Place timestamp before the description
            
            # Adjusted footer: Only the URL now
            embed.set_footer(text=f"https://ddc.bot")
            # --- End Valid Data Embed ---
        else:
            # Fallback for any other unexpected type of status_result
            logger.error(f"[_GEN_EMBED] Unexpected data type for status_result for '{display_name}': {type(status_result)}")
            embed = discord.Embed(
                title=f"⚠️ {display_name}", 
                description=_("Internal error: Unexpected data format for server status."), 
                color=discord.Color.orange()
            )
            # running remains False, view remains None

        # --- Generate View (only if embed exists) ---
        # Embed should ideally always be set by this point due to the comprehensive handling above.
        if embed is None: # Should ideally not be reached
             logger.critical(f"[_GEN_EMBED] CRITICAL: Embed is None for '{display_name}' after all status processing. This indicates a flaw in embed generation logic.")
             embed = discord.Embed(title=f"🆘 {display_name}", description=_("Critical internal error generating status display. Please contact support or check logs immediately."), color=discord.Color.dark_red())
             view = None # No view for critical error
        elif not (isinstance(status_result, tuple) and len(status_result) == 6 and running is True): # Only add full controls if running and status is valid tuple
            # For error embeds or offline statuses, we might want a simplified or no view.
            # If status_result was an error or None, 'running' is False. If it was a valid tuple but server offline, 'running' is False.
            # For now, ControlView handles 'running' status to show appropriate buttons. If view is problematic for errors, adjust here.
            pass # Let ControlView decide based on 'running' status for now.

        # SMART STATUS INFO INTEGRATION: Determine view type based on channel permissions
        if embed and server_conf and not (embed.title and embed.title.startswith("🆘")):
            channel_has_control = _channel_has_permission(channel_id, 'control', current_config)

            # REMOVED unnecessary config reload - just use the passed server_conf
            # This avoids losing temporary flags like _is_admin_control
            # actual_server_conf = next((s for s in all_servers_config if s.get('name', s.get('docker_name')) == display_name), server_conf)

            # Import here to avoid circular imports
            from .status_info_integration import should_show_info_in_status_channel, StatusInfoView, create_enhanced_status_embed

            # Check if this is a status-only channel that should show info integration
            # Skip info integration for admin control messages
            is_admin_control = server_conf.get('_is_admin_control', False)

            show_info_integration = should_show_info_in_status_channel(channel_id, current_config) and not is_admin_control

            if show_info_integration and not channel_has_control:
                # STATUS-ONLY CHANNEL: Use StatusInfoView and enhance embed
                view = StatusInfoView(self, server_conf, running)

                # Enhance embed with info indicators if info is available
                embed = create_enhanced_status_embed(embed, server_conf, info_indicator=True)

            else:
                # CONTROL CHANNEL: Use standard ControlView
                view = ControlView(self, server_conf, running, channel_has_control_permission=channel_has_control, allow_toggle=allow_toggle)
        else:
            view = None # Ensure view is None if server_conf is missing or critical error

        return embed, view, running
        
    async def send_server_status(self, channel: discord.TextChannel, server_conf: Dict[str, Any], current_config: dict, allow_toggle: bool = True, force_collapse: bool = False) -> Optional[discord.Message]:
        """
        Sends or updates status information for a server in a channel.
        ALWAYS reads from the cache and respects pending status.

        Parameters:
        - channel: The Discord text channel to send the message to
        - server_conf: Configuration for the specific server
        - current_config: The full bot configuration
        - allow_toggle: Whether to allow toggle button in the view
        - force_collapse: Whether to force the status to be collapsed

        Returns:
        - The sent/edited Discord message, or None if no message was sent/edited
        """
        display_name = server_conf.get('name', server_conf.get('docker_name'))
        if not display_name:
             logger.error("[SEND_STATUS] Server config missing name or docker_name.")
             return None

        # DOCKER CONNECTIVITY CHECK: Check before attempting to get/send status
        from services.infrastructure.docker_connectivity_service import get_docker_connectivity_service, DockerConnectivityRequest, DockerErrorEmbedRequest

        connectivity_service = get_docker_connectivity_service()
        connectivity_request = DockerConnectivityRequest(timeout_seconds=5.0)
        connectivity_result = await connectivity_service.check_connectivity(connectivity_request)

        if not connectivity_result.is_connected:
            logger.warning(f"[SEND_STATUS] Docker connectivity failed for '{display_name}': {connectivity_result.error_message}")

            # Create Docker connectivity error embed using service
            lang = current_config.get('language', 'de')
            embed_request = DockerErrorEmbedRequest(
                error_message=connectivity_result.error_message,
                language=lang,
                context='individual_container'
            )
            embed_result = connectivity_service.create_error_embed_data(embed_request)

            if not embed_result.success:
                logger.error(f"Failed to create Docker connectivity error embed: {embed_result.error}")
                return None

            # Create Discord embed from service result
            embed = discord.Embed(
                title=embed_result.title,
                description=embed_result.description,
                color=embed_result.color
            )
            embed.set_footer(text=embed_result.footer_text)
            view = None  # No controls available during connectivity issues

            # Send/edit with connectivity error embed
            msg = None
            try:
                existing_msg_id = None
                if channel.id in self.channel_server_message_ids:
                     existing_msg_id = self.channel_server_message_ids[channel.id].get(display_name)
                should_edit = existing_msg_id is not None

                if should_edit:
                    try:
                        existing_message = channel.get_partial_message(existing_msg_id)
                        await existing_message.edit(embed=embed, view=None)
                        msg = existing_message
                        logger.info(f"[SEND_STATUS] Updated message {existing_msg_id} with Docker connectivity error for '{display_name}'")
                    except discord.NotFound:
                        logger.warning(f"[SEND_STATUS] Message {existing_msg_id} not found, sending new connectivity error message")
                        existing_msg_id = None
                    except (discord.HTTPException, discord.Forbidden, RuntimeError) as e:
                        logger.error(f"[SEND_STATUS] Failed to edit connectivity error message: {e}", exc_info=True)
                        existing_msg_id = None

                if not existing_msg_id:
                    msg = await channel.send(embed=embed, view=None)
                    if channel.id not in self.channel_server_message_ids:
                        self.channel_server_message_ids[channel.id] = {}
                    self.channel_server_message_ids[channel.id][display_name] = msg.id
                    logger.info(f"[SEND_STATUS] Sent new Docker connectivity error message {msg.id} for '{display_name}'")

            except (discord.HTTPException, discord.Forbidden, RuntimeError, KeyError) as e:
                logger.error(f"[SEND_STATUS] Failed to send Docker connectivity error message for '{display_name}': {e}", exc_info=True)

            return msg

        msg = None
        try:
            embed, view, _ = await self._generate_status_embed_and_view(channel.id, display_name, server_conf, current_config, allow_toggle, force_collapse, show_cache_age=False)

            if embed:
                existing_msg_id = None
                if channel.id in self.channel_server_message_ids:
                     existing_msg_id = self.channel_server_message_ids[channel.id].get(display_name)
                should_edit = existing_msg_id is not None

                if should_edit:
                    try:
                        # PERFORMANCE OPTIMIZATION: Use partial message instead of fetch
                        existing_message = channel.get_partial_message(existing_msg_id)  # No API call
                        await existing_message.edit(embed=embed, view=view if view and view.children else None)
                        msg = existing_message

                        # Update last edit time
                        if channel.id not in self.last_message_update_time:
                            self.last_message_update_time[channel.id] = {}
                        self.last_message_update_time[channel.id][display_name] = datetime.now(timezone.utc)
                    except discord.NotFound:
                         logger.warning(f"[SEND_STATUS] Message {existing_msg_id} for '{display_name}' not found. Will send new.")
                         if channel.id in self.channel_server_message_ids and display_name in self.channel_server_message_ids[channel.id]:
                              del self.channel_server_message_ids[channel.id][display_name]
                         existing_msg_id = None
                    except (discord.HTTPException, discord.Forbidden, RuntimeError, KeyError) as e:
                         logger.error(f"[SEND_STATUS] Failed to edit message {existing_msg_id} for '{display_name}': {e}", exc_info=True)
                         existing_msg_id = None

                if not existing_msg_id:
                     try:
                          msg = await channel.send(embed=embed, view=view if view and view.children else None)
                          if channel.id not in self.channel_server_message_ids:
                               self.channel_server_message_ids[channel.id] = {}
                          self.channel_server_message_ids[channel.id][display_name] = msg.id
                          logger.info(f"[SEND_STATUS] Sent new message {msg.id} for '{display_name}' in channel {channel.id}")
                          
                          # Set last edit time for new messages
                          if channel.id not in self.last_message_update_time:
                              self.last_message_update_time[channel.id] = {}
                          self.last_message_update_time[channel.id][display_name] = datetime.now(timezone.utc)
                     except (discord.HTTPException, discord.Forbidden, RuntimeError, KeyError) as e:
                          logger.error(f"[SEND_STATUS] Failed to send new message for '{display_name}' in channel {channel.id}: {e}", exc_info=True)
            else:
                logger.warning(f"[SEND_STATUS] No embed generated for '{display_name}' (likely error in helper?), cannot send/edit.")

        except (RuntimeError, asyncio.CancelledError, KeyError, TypeError) as e:
            logger.error(f"[SEND_STATUS] Outer error processing server '{display_name}' for channel {channel.id}: {e}", exc_info=True)
        return msg

    # Wrapper to set the update time (must accept allow_toggle)
    async def _edit_single_message_wrapper(self, channel_id: int, display_name: str, message_id: int, current_config: dict, allow_toggle: bool):
        result = await self._edit_single_message(channel_id, display_name, message_id, current_config)
        if result is True:
            now = datetime.now(timezone.utc)
            if channel_id not in self.last_message_update_time:
                self.last_message_update_time[channel_id] = {}
            self.last_message_update_time[channel_id][display_name] = now
        return result

    # =============================================================================
    # ULTRA-PERFORMANCE MESSAGE EDITING WITH BULK CACHE PRELOADING
    # =============================================================================

    async def _edit_single_message(self, channel_id: int, display_name: str, message_id: int, current_config: dict) -> Union[bool, Exception, None]:
        """Edits a single status message based on cache and Pending-Status with conditional updates."""
        start_time = time.time()

        # Get conditional cache service
        cache_service = get_conditional_cache_service()
        
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()
        server_conf = next((s for s in servers if s.get('name', s.get('docker_name')) == display_name), None)
        if not server_conf:
            logger.warning(f"[_EDIT_SINGLE] Config for '{display_name}' not found during edit.")
            if channel_id in self.channel_server_message_ids and display_name in self.channel_server_message_ids[channel_id]:
                del self.channel_server_message_ids[channel_id][display_name]
            return False

        try:
            # Set flags based on channel permissions
            channel_has_control_permission = _channel_has_permission(channel_id, 'control', current_config)
            allow_toggle = channel_has_control_permission  # Only allow toggle in control channels
            force_collapse = not channel_has_control_permission # Force collapse in non-control channels

            # Pass flags to the generation function
            embed, view, _ = await self._generate_status_embed_and_view(channel_id, display_name, server_conf, current_config, allow_toggle=allow_toggle, force_collapse=force_collapse, show_cache_age=False)

            if not embed:
                logger.warning(f"_edit_single_message: No embed generated for '{display_name}', cannot edit.")
                return None

            # ✨ CONDITIONAL UPDATE CHECK - Only edit if content changed
            cache_key = f"{channel_id}:{display_name}"

            # Create a comparable content hash from embed + view
            current_content = {
                'description': embed.description,
                'color': embed.color.value if embed.color else None,
                'footer': embed.footer.text if embed.footer else None,
                'view_children_count': len(view.children) if view else 0
            }

            # Check if content actually changed
            if not cache_service.has_content_changed(cache_key, current_content):
                # Content unchanged - skip Discord API call (silent skip, no logging)
                # This is the HAPPY PATH and happens very frequently - don't spam logs
                return True  # Return success without actual edit
            
            # Content changed or first time - proceed with edit
            # PERFORMANCE OPTIMIZATION: Use cached channel object instead of fetch
            channel = self.bot.get_channel(channel_id)  # Uses bot's internal cache, no API call
            if not channel:
                # Fallback to fetch if not in cache (rare case - no logging needed)
                channel = await self.bot.fetch_channel(channel_id)
            
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"_edit_single_message: Channel {channel_id} is not a text channel.")
                if channel_id in self.channel_server_message_ids and display_name in self.channel_server_message_ids[channel_id]:
                     del self.channel_server_message_ids[channel_id][display_name]
                return TypeError(f"Channel {channel_id} not text channel")

            # PERFORMANCE OPTIMIZATION: Use partial message instead of fetch
            # This creates a message object without API call - edit() works on partial messages
            message_to_edit = channel.get_partial_message(message_id)  # No API call

            # PERFORMANCE FIX: Add timeout to prevent slow Discord API calls from blocking the system
            try:
                await asyncio.wait_for(
                    message_to_edit.edit(embed=embed, view=view if view and view.children else None),
                    timeout=5.0  # 5 second timeout for Discord API calls
                )
            except asyncio.TimeoutError:
                elapsed_time = (time.time() - start_time) * 1000
                logger.error(f"_edit_single_message: TIMEOUT for '{display_name}' after 5000ms (total time: {elapsed_time:.1f}ms)")
                # For timeout cases, still update the cache to prevent immediate retry
                cache_service.update_content(cache_key, current_content)
                return False  # Return failure but don't crash

            # Store the new content for future comparison
            cache_service.update_content(cache_key, current_content)

            # Performance logging - only log slow operations to avoid spam
            elapsed_time = (time.time() - start_time) * 1000
            if elapsed_time > 1000:  # Over 1 second - critical
                logger.error(f"_edit_single_message: CRITICAL SLOW edit for '{display_name}' took {elapsed_time:.1f}ms")
            elif elapsed_time > 500:  # Over 500ms - warning
                logger.warning(f"_edit_single_message: SLOW edit for '{display_name}' took {elapsed_time:.1f}ms")
            # Fast/normal operations (<500ms) are silent - this is the expected behavior
            
            # REMOVED: await asyncio.sleep(0.2) - This was blocking true parallelization
            # Discord API rate limiting is handled by py-cord internally
            return True # Success

        except discord.NotFound:
            logger.warning(f"_edit_single_message: Message {message_id} or Channel {channel_id} not found. Removing from cache.")
            if channel_id in self.channel_server_message_ids and display_name in self.channel_server_message_ids[channel_id]:
                del self.channel_server_message_ids[channel_id][display_name]
            return False # NotFound
        except discord.Forbidden:
            logger.error(f"_edit_single_message: Missing permissions to fetch/edit message {message_id} in channel {channel_id}.")
            return discord.Forbidden(f"Permissions error for {message_id}")
        except (discord.HTTPException, RuntimeError, asyncio.CancelledError, KeyError, TypeError, ValueError) as e:
            elapsed_time = (time.time() - start_time) * 1000
            logger.error(f"_edit_single_message: Failed to edit message {message_id} for '{display_name}' after {elapsed_time:.1f}ms: {e}", exc_info=True)
            return e 