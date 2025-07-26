# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2023-2025 MAX                                                  #
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
from utils.logging_utils import setup_logger, get_module_logger
from utils.docker_utils import get_docker_info, get_docker_stats
from utils.time_utils import format_datetime_with_timezone

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
    
    def _ensure_conditional_cache(self):
        """Ensure conditional update cache is initialized."""
        if not hasattr(self, 'last_sent_content'):
            self.last_sent_content = {}  # Track last sent embed content for conditional updates
            logger.debug("Initialized conditional update cache")
        if not hasattr(self, 'update_stats'):
            self.update_stats = {'skipped': 0, 'sent': 0, 'last_reset': datetime.now(timezone.utc)}
            logger.debug("Initialized update statistics")
    
    def _ensure_performance_system(self):
        """Initialize the adaptive performance learning system."""
        if not hasattr(self, 'container_performance_history'):
            self.container_performance_history = {}
            logger.debug("Initialized adaptive performance system")
        if not hasattr(self, 'performance_learning_config'):
            self.performance_learning_config = {
                'min_timeout': 5000,      # 5 seconds minimum
                'max_timeout': 120000,    # 2 minutes maximum
                'default_timeout': 30000, # 30 seconds default
                'slow_threshold': 8000,   # 8+ seconds = slow container
                'history_window': 20,     # Keep last 20 measurements
                'retry_attempts': 3,      # Maximum retry attempts
                'timeout_multiplier': 2.0 # Timeout = avg_time * multiplier
            }
            logger.debug("Initialized performance learning configuration")
    
    def _get_container_performance_profile(self, container_name: str) -> dict:
        """Get or create performance profile for a container."""
        self._ensure_performance_system()
        
        if container_name not in self.container_performance_history:
            self.container_performance_history[container_name] = {
                'response_times': [],
                'avg_response_time': self.performance_learning_config['default_timeout'],
                'max_response_time': self.performance_learning_config['default_timeout'],
                'min_response_time': 1000,
                'success_rate': 1.0,
                'total_attempts': 0,
                'successful_attempts': 0,
                'is_slow': False,
                'last_updated': datetime.now(timezone.utc)
            }
            logger.debug(f"Created new performance profile for container: {container_name}")
        
        return self.container_performance_history[container_name]
    
    def _update_container_performance(self, container_name: str, response_time: float, success: bool):
        """Update container performance history with new measurement."""
        profile = self._get_container_performance_profile(container_name)
        config = self.performance_learning_config
        
        # Update attempt counters
        profile['total_attempts'] += 1
        if success:
            profile['successful_attempts'] += 1
            profile['response_times'].append(response_time)
        
        # Maintain sliding window
        if len(profile['response_times']) > config['history_window']:
            profile['response_times'] = profile['response_times'][-config['history_window']:]
        
        # Calculate new statistics
        if profile['response_times']:
            profile['avg_response_time'] = sum(profile['response_times']) / len(profile['response_times'])
            profile['max_response_time'] = max(profile['response_times'])
            profile['min_response_time'] = min(profile['response_times'])
        
        profile['success_rate'] = profile['successful_attempts'] / profile['total_attempts']
        profile['is_slow'] = profile['avg_response_time'] > config['slow_threshold']
        profile['last_updated'] = datetime.now(timezone.utc)
        
        if success:
            logger.debug(f"Performance update for {container_name}: avg={profile['avg_response_time']:.0f}ms, "
                        f"success_rate={profile['success_rate']:.2f}, is_slow={profile['is_slow']}")
    
    def _get_adaptive_timeout(self, container_name: str) -> float:
        """Calculate adaptive timeout based on container performance history."""
        profile = self._get_container_performance_profile(container_name)
        config = self.performance_learning_config
        
        # Base timeout on average response time with safety margin
        adaptive_timeout = max(
            profile['avg_response_time'] * config['timeout_multiplier'],
            profile['max_response_time'] * 1.5,  # 1.5x worst recorded time
            config['min_timeout']  # Never go below minimum
        )
        
        # Cap at maximum timeout
        adaptive_timeout = min(adaptive_timeout, config['max_timeout'])
        
        # Add extra time for containers with poor success rate
        if profile['success_rate'] < 0.8:
            adaptive_timeout *= 1.5
            logger.debug(f"Increased timeout for {container_name} due to low success rate: {profile['success_rate']:.2f}")
        
        return adaptive_timeout
    
    def _classify_containers_by_performance(self, container_names: List[str]) -> Tuple[List[str], List[str]]:
        """Classify containers into fast and slow based on performance history."""
        fast_containers = []
        slow_containers = []
        
        for container_name in container_names:
            profile = self._get_container_performance_profile(container_name)
            
            if profile['is_slow'] or profile['success_rate'] < 0.8:
                slow_containers.append(container_name)
                logger.debug(f"Classified {container_name} as slow: avg={profile['avg_response_time']:.0f}ms, "
                           f"success_rate={profile['success_rate']:.2f}")
            else:
                fast_containers.append(container_name)
        
        return fast_containers, slow_containers
    
    async def _fetch_container_with_retries(self, docker_name: str) -> Tuple[str, Any, Any]:
        """Fetch container data with intelligent retry strategy - always gets complete data."""
        start_time = time.time()
        profile = self._get_container_performance_profile(docker_name)
        config = self.performance_learning_config
        
        last_exception = None
        
        for attempt in range(config['retry_attempts']):
            try:
                # Calculate timeout for this attempt (increases with each retry)
                base_timeout = self._get_adaptive_timeout(docker_name)
                current_timeout = base_timeout * (1.5 ** attempt)  # Exponential backoff
                
                logger.debug(f"Fetching {docker_name} - attempt {attempt + 1}/{config['retry_attempts']}, "
                           f"timeout: {current_timeout:.0f}ms")
                
                attempt_start = time.time()
                
                # Fetch info and stats in parallel with adaptive timeout
                info_task = asyncio.create_task(get_docker_info(docker_name))
                stats_task = asyncio.create_task(get_docker_stats(docker_name))
                
                info, stats = await asyncio.wait_for(
                    asyncio.gather(info_task, stats_task, return_exceptions=True),
                    timeout=current_timeout / 1000.0  # Convert to seconds
                )
                
                attempt_time = (time.time() - attempt_start) * 1000
                
                # Update performance history
                self._update_container_performance(docker_name, attempt_time, True)
                
                total_time = (time.time() - start_time) * 1000
                if attempt > 0:
                    logger.info(f"Successfully fetched {docker_name} on attempt {attempt + 1} "
                              f"(attempt: {attempt_time:.1f}ms, total: {total_time:.1f}ms)")
                
                return docker_name, info, stats
                
            except asyncio.TimeoutError as e:
                last_exception = e
                attempt_time = (time.time() - attempt_start) * 1000 if 'attempt_start' in locals() else current_timeout
                
                logger.warning(f"Timeout for {docker_name} on attempt {attempt + 1}/{config['retry_attempts']} "
                             f"after {attempt_time:.1f}ms")
                
                if attempt < config['retry_attempts'] - 1:
                    # Short delay before retry
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                last_exception = e
                logger.error(f"Error fetching {docker_name} on attempt {attempt + 1}: {e}")
                
                if attempt < config['retry_attempts'] - 1:
                    await asyncio.sleep(0.5)
        
        # All retries failed - try emergency fetch without timeout
        logger.warning(f"All retries failed for {docker_name}, attempting emergency fetch")
        return await self._emergency_full_fetch(docker_name, last_exception)
    
    async def _emergency_full_fetch(self, docker_name: str, last_exception: Exception) -> Tuple[str, Any, Any]:
        """Emergency fetch with no timeout limits - last resort to get complete data."""
        try:
            logger.info(f"Emergency full fetch for {docker_name} - no timeout limit")
            
            # NO timeout - wait however long it takes
            info_task = asyncio.create_task(get_docker_info(docker_name))
            stats_task = asyncio.create_task(get_docker_stats(docker_name))
            
            start_emergency = time.time()
            info, stats = await asyncio.gather(info_task, stats_task, return_exceptions=True)
            emergency_time = (time.time() - start_emergency) * 1000
            
            # Mark as slow container for future reference
            profile = self._get_container_performance_profile(docker_name)
            profile['is_slow'] = True
            self._update_container_performance(docker_name, emergency_time, True)
            
            logger.info(f"Emergency fetch successful for {docker_name} after {emergency_time:.1f}ms")
            return docker_name, info, stats
            
        except Exception as e:
            # Even emergency fetch failed - update performance and return error
            self._update_container_performance(docker_name, 0, False)
            logger.error(f"Emergency fetch failed for {docker_name}: {e}")
            return docker_name, last_exception, None
    
    def _get_cached_translations(self, lang: str) -> dict:
        """Cached translations for better performance."""
        if not hasattr(self, 'cached_translations'):
            self.cached_translations = {}
        
        cache_key = f"translations_{lang}"
        
        if cache_key not in self.cached_translations:
            self.cached_translations[cache_key] = {
                'online_text': _("**Online**"),
                'offline_text': _("**Offline**"),
                'cpu_text': _("CPU"),
                'ram_text': _("RAM"),
                'uptime_text': _("Uptime"),
                'detail_denied_text': _("Detailed status not allowed."),
                'last_update_text': _("Last update")
            }
            logger.debug(f"Cached translations for language: {lang}")
        
        return self.cached_translations[cache_key]
    
    def _get_cached_box_elements(self, display_name: str, BOX_WIDTH: int = 28) -> dict:
        """Cached box elements for better performance."""
        if not hasattr(self, 'cached_box_elements'):
            self.cached_box_elements = {}
            
        cache_key = f"box_{display_name}_{BOX_WIDTH}"
        
        if cache_key not in self.cached_box_elements:
            header_text = f"── {display_name} "
            max_name_len = BOX_WIDTH - 4
            if len(header_text) > max_name_len:
                header_text = header_text[:max_name_len-1] + "… "
            padding_width = max(1, BOX_WIDTH - 1 - len(header_text))
            
            self.cached_box_elements[cache_key] = {
                'header_line': f"┌{header_text}{'─' * padding_width}",
                'footer_line': f"└{'─' * (BOX_WIDTH - 1)}"
            }
            logger.debug(f"Cached box elements for: {display_name}")
        
        return self.cached_box_elements[cache_key]
    
    async def bulk_fetch_container_status(self, container_names: List[str]) -> Dict[str, Tuple]:
        """
        Intelligent bulk fetch with adaptive performance learning and complete data collection.
        Uses performance history to optimize timeouts and batching while always collecting full details.
        
        Args:
            container_names: List of Docker container names to fetch
            
        Returns:
            Dict mapping container_name -> (display_name, is_running, cpu, ram, uptime, details_allowed)
        """
        if not container_names:
            return {}
        
        start_time = time.time()
        logger.info(f"[INTELLIGENT_BULK_FETCH] Starting adaptive bulk fetch for {len(container_names)} containers")
        
        # Initialize performance system
        self._ensure_performance_system()
        
        # Classify containers by performance history for intelligent batching
        fast_containers, slow_containers = self._classify_containers_by_performance(container_names)
        
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
            MAX_CONCURRENT_FAST = min(5, len(fast_containers))  # Max 5 concurrent for fast containers
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_FAST)
            
            async def fetch_fast_container(container_name):
                async with semaphore:
                    return await self._fetch_container_with_retries(container_name)
            
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
                container_start = time.time()
                logger.debug(f"[INTELLIGENT_BULK_FETCH] Processing slow container {i+1}/{len(slow_containers)}: {container_name}")
                
                result = await self._fetch_container_with_retries(container_name)
                all_results.append(result)
                
                container_time = (time.time() - container_start) * 1000
                logger.debug(f"[INTELLIGENT_BULK_FETCH] Slow container {container_name} completed in {container_time:.1f}ms")
            
            slow_time = (time.time() - phase2_start) * 1000
            logger.info(f"[INTELLIGENT_BULK_FETCH] Phase 2 completed: {len(slow_containers)} slow containers in {slow_time:.1f}ms")
        
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
            
            # Find server config for this container
            servers = self.config.get('servers', [])
            server_config = next((s for s in servers if s.get('docker_name') == docker_name), None)
            
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
                status_results[docker_name] = (display_name, False, 'N/A', 'N/A', 'N/A', details_allowed)
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
                if details_allowed and not isinstance(stats, Exception) and stats:
                    cpu_stat, ram_stat = stats
                    # We waited for real values - use them!
                    cpu = cpu_stat if cpu_stat is not None else 'N/A'
                    ram = ram_stat if ram_stat is not None else 'N/A'
                elif not details_allowed:
                    cpu = _("Hidden")
                    ram = _("Hidden")
                # If details allowed but stats failed, keep N/A (we tried!)
            
            status_results[docker_name] = (display_name, is_running, cpu, ram, uptime, details_allowed)
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
        
        for docker_name in container_names:
            # Find display name
            servers = self.config.get('servers', [])
            server_config = next((s for s in servers if s.get('docker_name') == docker_name), None)
            if not server_config:
                continue
                
            display_name = server_config.get('name', docker_name)
            cached_entry = self.status_cache.get(display_name)
            
            # ONLY update if cache is completely missing (not just stale)
            # Background loop handles regular updates every 30s
            if not cached_entry:
                containers_needing_update.append(docker_name)
                logger.debug(f"[BULK_UPDATE] {display_name} has no cache entry, scheduling update")
            else:
                # Cache exists - let background loop handle updates
                cache_age = (now - cached_entry['timestamp']).total_seconds()
                logger.debug(f"[BULK_UPDATE] {display_name} has cache (age: {cache_age:.1f}s), background loop handles updates")
        
        if not containers_needing_update:
            logger.debug(f"[BULK_UPDATE] All {len(container_names)} containers have cache entries - background loop provides updates")
            return
        
        logger.info(f"[BULK_UPDATE] Updating cache for {len(containers_needing_update)}/{len(container_names)} containers with missing cache")
        
        # Bulk fetch only the containers with no cache
        bulk_results = await self.bulk_fetch_container_status(containers_needing_update)
        
        # Update cache with results
        for docker_name, status_tuple in bulk_results.items():
            # Find display name
            servers = self.config.get('servers', [])
            server_config = next((s for s in servers if s.get('docker_name') == docker_name), None)
            if server_config:
                display_name = server_config.get('name', docker_name)
                self.status_cache[display_name] = {
                    'data': status_tuple,
                    'timestamp': now
                }
                logger.debug(f"[BULK_UPDATE] Updated missing cache for {display_name}")

    async def get_status(self, server_config: Dict[str, Any]) -> Union[Tuple[str, bool, str, str, str, bool], Exception]:
        """
        Gets the status of a server.
        Returns: (display_name, is_running, cpu, ram, uptime, details_allowed) or Exception
        """
        docker_name = server_config.get('docker_name')
        display_name = server_config.get('name', docker_name)
        details_allowed = server_config.get('allow_detailed_status', True) # Default to True if not set

        if not docker_name:
            return ValueError(_("Missing docker_name in server configuration"))

        try:
            info = await get_docker_info(docker_name)

            if not info:
                # Container does not exist or Docker daemon is unreachable
                logger.warning(f"Container info not found for {docker_name}. Assuming offline.")
                return (display_name, False, 'N/A', 'N/A', 'N/A', details_allowed)

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

                # Fetch CPU and RAM only if allowed
                if details_allowed:
                    stats_tuple = await get_docker_stats(docker_name)
                    if stats_tuple and isinstance(stats_tuple, tuple) and len(stats_tuple) == 2:
                         cpu_stat, ram_stat = stats_tuple
                         cpu = cpu_stat if cpu_stat is not None else 'N/A'
                         ram = ram_stat if ram_stat is not None else 'N/A'
                    else:
                         logger.warning(f"Could not retrieve valid stats tuple for running container {docker_name}")
                         cpu = "N/A"
                         ram = "N/A"
                else:
                    cpu = _("Hidden")
                    ram = _("Hidden")

            return (display_name, is_running, cpu, ram, uptime, details_allowed)

        except Exception as e:
            logger.error(f"Error getting status for {docker_name}: {e}", exc_info=True)
            return e # Return the exception itself
    
    async def _generate_status_embed_and_view(self, channel_id: int, display_name: str, server_conf: dict, current_config: dict, allow_toggle: bool, force_collapse: bool) -> tuple[Optional[discord.Embed], Optional[discord.ui.View], bool]:
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
        """
        lang = current_config.get('language', 'de')
        timezone_str = current_config.get('timezone')
        all_servers_config = current_config.get('servers', [])

        logger.debug(f"[_GEN_EMBED] Generating embed for '{display_name}' in channel {channel_id}, lang={lang}, allow_toggle={allow_toggle}, force_collapse={force_collapse}")
        if not allow_toggle or force_collapse:
             logger.debug(f"[_GEN_EMBED_FLAGS] '{display_name}': allow_toggle={allow_toggle}, force_collapse={force_collapse}. ToggleButton/Expanded view should be suppressed.")
            
        embed = None
        view = None
        running = False # Default running state
        status_result = None
        cached_entry = self.status_cache.get(display_name)
        now = datetime.now(timezone.utc)

        # --- Check for pending action first --- (Moved before status_result processing)
        if display_name in self.pending_actions:
            pending_data = self.pending_actions[display_name]
            pending_timestamp = pending_data['timestamp']
            pending_action = pending_data['action']
            pending_duration = (now - pending_timestamp).total_seconds()
            
            # IMPROVED: Longer timeout and smarter pending logic
            PENDING_TIMEOUT_SECONDS = 120  # 2 minutes timeout instead of 15 seconds
            
            if pending_duration < PENDING_TIMEOUT_SECONDS:
                logger.debug(f"[_GEN_EMBED] '{display_name}' is in pending state (action: {pending_action} at {pending_timestamp}, duration: {pending_duration:.1f}s)")
                embed = _get_pending_embed(display_name) # Uses a standardized pending embed
                return embed, None, False # No view, running status is effectively false for pending display
            else:
                # IMPROVED: Smart timeout - check if container status actually changed based on action
                logger.info(f"[_GEN_EMBED] '{display_name}' pending timeout reached ({pending_duration:.1f}s). Checking if {pending_action} action succeeded...")
                
                # Try to get current container status to see if it changed
                current_server_conf_for_check = next((s for s in all_servers_config if s.get('name', s.get('docker_name')) == display_name), None)
                if current_server_conf_for_check:
                    fresh_status = await self.get_status(current_server_conf_for_check)
                    if not isinstance(fresh_status, Exception) and isinstance(fresh_status, tuple) and len(fresh_status) >= 2:
                        current_running_state = fresh_status[1]  # is_running is second element
                        
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
                            del self.pending_actions[display_name]
                            # Update cache with fresh status
                            self.status_cache[display_name] = {'data': fresh_status, 'timestamp': now}
                        else:
                            # Action might have failed or container takes very long
                            logger.warning(f"[_GEN_EMBED] '{display_name}' {pending_action} action did not succeed after {pending_duration:.1f}s timeout - clearing pending state")
                            del self.pending_actions[display_name]
                    else:
                        logger.warning(f"[_GEN_EMBED] '{display_name}' pending timeout - could not get fresh status, clearing pending state")
                        del self.pending_actions[display_name]
                else:
                    logger.warning(f"[_GEN_EMBED] '{display_name}' pending timeout - no server config found, clearing pending state")
                    del self.pending_actions[display_name]

        # --- Determine status_result (from cache or live) ---
        if cached_entry:
            cache_age = (now - cached_entry['timestamp']).total_seconds()
            # PATIENT APPROACH: ALWAYS use cache if available - background collects fresh data
            # Show cache age when data is older so user knows freshness
            if cache_age < self.cache_ttl_seconds:
                logger.debug(f"[_GEN_EMBED] Using fresh cached status for '{display_name}' (age: {cache_age:.1f}s)")
                cache_age_indicator = ""  # No indicator for fresh data
            else:
                logger.debug(f"[_GEN_EMBED] Using cached status for '{display_name}' (age: {cache_age:.1f}s) - background updating...")
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
            logger.info(f"[_GEN_EMBED] No cache entry for '{display_name}'. This should be rare - background loop will populate cache...")
            current_server_conf_for_fetch = next((s for s in all_servers_config if s.get('name', s.get('docker_name')) == display_name), None)
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
        if status_result is None:
            logger.debug(f"[_GEN_EMBED] Status result for '{display_name}' is None. Showing loading or error status.")
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
            
            # PERFORMANCE OPTIMIZATION: Verwende gecachte Übersetzungen
            cached_translations = self._get_cached_translations(lang)
            online_text = cached_translations['online_text']
            offline_text = cached_translations['offline_text']
            status_text = online_text if running else offline_text
            current_emoji = "🟢" if running else "🔴"

            # Check if we should always collapse
            is_expanded = self.expanded_states.get(display_name, False) and not force_collapse

            # PERFORMANCE OPTIMIZATION: Verwende gecachte Übersetzungen
            cpu_text = cached_translations['cpu_text']
            ram_text = cached_translations['ram_text']
            uptime_text = cached_translations['uptime_text']
            detail_denied_text = cached_translations['detail_denied_text']
            
            # PERFORMANCE OPTIMIZATION: Verwende gecachte Box-Elemente
            BOX_WIDTH = 28
            cached_box = self._get_cached_box_elements(display_name, BOX_WIDTH)
            header_line = cached_box['header_line']
            footer_line = cached_box['footer_line']
            
            # String builder for description - more efficient than multiple concatenations
            description_parts = [
                "```\n",
                header_line,
                f"\n│ {current_emoji} {status_text}"
            ]

            # Add cache age indicator if data is older
            if 'embed_cache_indicator' in locals() and embed_cache_indicator:
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
            current_time = format_datetime_with_timezone(now_footer, timezone_str, fmt="%H:%M:%S")
            
            # Enhanced timestamp with cache age info
            if 'embed_cache_age' in locals() and embed_cache_age > self.cache_ttl_seconds:
                timestamp_line = f"{last_update_text}: {current_time} (data: {int(embed_cache_age)}s ago)"
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

        # Only create ControlView if we have a valid server_conf for it and not a critical error embed
        if embed and server_conf and not (embed.title and embed.title.startswith("🆘")):
            channel_has_control = _channel_has_permission(channel_id, 'control', current_config)
            actual_server_conf = next((s for s in all_servers_config if s.get('name', s.get('docker_name')) == display_name), server_conf)
            view = ControlView(self, actual_server_conf, running, channel_has_control_permission=channel_has_control, allow_toggle=allow_toggle)
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
        logger.debug(f"[SEND_STATUS] Processing server '{display_name}' for channel {channel.id}, allow_toggle={allow_toggle}, force_collapse={force_collapse}")
        msg = None
        try:
            embed, view, _ = await self._generate_status_embed_and_view(channel.id, display_name, server_conf, current_config, allow_toggle, force_collapse)

            if embed:
                existing_msg_id = None
                if channel.id in self.channel_server_message_ids:
                     existing_msg_id = self.channel_server_message_ids[channel.id].get(display_name)
                should_edit = existing_msg_id is not None

                is_pending_check = display_name in self.pending_actions
                if is_pending_check:
                    logger.debug(f"[SEND_STATUS_PENDING_CHECK] Server '{display_name}' is marked as pending. Trying to { 'edit' if should_edit else 'send' } message.")

                if should_edit:
                    try:
                        # PERFORMANCE OPTIMIZATION: Use partial message instead of fetch
                        existing_message = channel.get_partial_message(existing_msg_id)  # No API call
                        await existing_message.edit(embed=embed, view=view if view and view.children else None)
                        msg = existing_message
                        logger.debug(f"[SEND_STATUS] Edited message {existing_msg_id} for '{display_name}' in channel {channel.id}")
                        
                        # Update last edit time
                        if channel.id not in self.last_message_update_time:
                            self.last_message_update_time[channel.id] = {}
                        self.last_message_update_time[channel.id][display_name] = datetime.now(timezone.utc)
                        
                        if is_pending_check: logger.debug(f"[SEND_STATUS_PENDING_CHECK] Successfully edited pending message for '{display_name}'.")
                    except discord.NotFound:
                         logger.warning(f"[SEND_STATUS] Message {existing_msg_id} for '{display_name}' not found. Will send new.")
                         if channel.id in self.channel_server_message_ids and display_name in self.channel_server_message_ids[channel.id]:
                              del self.channel_server_message_ids[channel.id][display_name]
                         existing_msg_id = None
                    except Exception as e:
                         logger.error(f"[SEND_STATUS] Failed to edit message {existing_msg_id} for '{display_name}': {e}", exc_info=True)
                         if is_pending_check: logger.error(f"[SEND_STATUS_PENDING_CHECK] Failed to EDIT pending message for '{display_name}'. Error: {e}")
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
                          
                          if is_pending_check: logger.debug(f"[SEND_STATUS_PENDING_CHECK] Successfully sent new pending message for '{display_name}'.")
                     except Exception as e:
                          logger.error(f"[SEND_STATUS] Failed to send new message for '{display_name}' in channel {channel.id}: {e}", exc_info=True)
                          if is_pending_check: logger.error(f"[SEND_STATUS_PENDING_CHECK] Failed to SEND new pending message for '{display_name}'. Error: {e}")
            else:
                logger.warning(f"[SEND_STATUS] No embed generated for '{display_name}' (likely error in helper?), cannot send/edit.")

        except Exception as e:
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
            logger.debug(f"Updated last_message_update_time for '{display_name}' in {channel_id} to {now}")
        return result

    # =============================================================================
    # ULTRA-PERFORMANCE MESSAGE EDITING WITH BULK CACHE PRELOADING
    # =============================================================================

    async def _edit_single_message(self, channel_id: int, display_name: str, message_id: int, current_config: dict) -> Union[bool, Exception, None]:
        """Edits a single status message based on cache and Pending-Status with conditional updates."""
        start_time = time.time()
        
        # Initialize conditional cache
        self._ensure_conditional_cache()
        
        server_conf = next((s for s in current_config.get('servers', []) if s.get('name', s.get('docker_name')) == display_name), None)
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
            embed, view, _ = await self._generate_status_embed_and_view(channel_id, display_name, server_conf, current_config, allow_toggle=allow_toggle, force_collapse=force_collapse)

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
            last_content = self.last_sent_content.get(cache_key)
            if last_content and last_content == current_content:
                # Content unchanged - skip Discord API call
                self.update_stats['skipped'] += 1
                elapsed_time = (time.time() - start_time) * 1000
                # Enhanced logging for offline containers
                cached_status = getattr(self, 'status_cache', {}).get(server_conf.get('docker_name'))
                is_offline = False
                if cached_status:
                    try:
                        # Handle both cache formats: direct tuple or {'data': tuple, 'timestamp': datetime}
                        if isinstance(cached_status, dict) and 'data' in cached_status:
                            status_data = cached_status['data']
                        else:
                            status_data = cached_status
                        
                        # Check if status_data is valid and has enough elements
                        if (hasattr(status_data, '__getitem__') and hasattr(status_data, '__len__') and 
                            len(status_data) >= 2):
                            is_offline = not status_data[1]  # Second value is is_running
                    except (TypeError, IndexError, KeyError):
                        pass  # Ignore cache format issues for logging
                status_info = " [OFFLINE]" if is_offline else ""
                logger.debug(f"_edit_single_message: SKIPPED edit for '{display_name}'{status_info} - content unchanged ({elapsed_time:.1f}ms)")
                
                # Log performance stats every 50 skipped updates
                if self.update_stats['skipped'] % 50 == 0:
                    total_operations = self.update_stats['skipped'] + self.update_stats['sent']
                    skip_percentage = (self.update_stats['skipped'] / total_operations * 100) if total_operations > 0 else 0
                    logger.info(f"UPDATE_STATS: Skipped {self.update_stats['skipped']} / Sent {self.update_stats['sent']} ({skip_percentage:.1f}% saved)")
                
                return True  # Return success without actual edit
            
            # Content changed or first time - proceed with edit
            # PERFORMANCE OPTIMIZATION: Use cached channel object instead of fetch
            channel = self.bot.get_channel(channel_id)  # Uses bot's internal cache, no API call
            if not channel:
                # Fallback to fetch if not in cache (rare case)
                logger.debug(f"_edit_single_message: Channel {channel_id} not in cache, fetching...")
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
                self.last_sent_content[cache_key] = current_content
                self.update_stats['sent'] += 1  # Count as attempt even if timeout
                return False  # Return failure but don't crash
            
            # Store the new content for future comparison
            self.last_sent_content[cache_key] = current_content
            self.update_stats['sent'] += 1
            
            # Prevent cache from growing too large (cleanup every 100 operations)
            total_ops = self.update_stats['skipped'] + self.update_stats['sent']
            if total_ops % 100 == 0 and len(self.last_sent_content) > 50:
                # Keep only the most recent 25 entries
                sorted_items = list(self.last_sent_content.items())[-25:]
                self.last_sent_content = dict(sorted_items)
                logger.debug(f"Cleaned conditional update cache: kept {len(self.last_sent_content)} entries")
            
            elapsed_time = (time.time() - start_time) * 1000
            
            # Smart performance logging
            if elapsed_time > 1000:  # Over 1 second - critical
                logger.error(f"_edit_single_message: CRITICAL SLOW edit for '{display_name}' took {elapsed_time:.1f}ms")
            elif elapsed_time > 500:  # Over 500ms - warning
                logger.warning(f"_edit_single_message: SLOW edit for '{display_name}' took {elapsed_time:.1f}ms")
            elif elapsed_time < 100:  # Under 100ms - excellent
                logger.info(f"_edit_single_message: FAST edit for '{display_name}' in {elapsed_time:.1f}ms")
            else:
                logger.info(f"_edit_single_message: Updated '{display_name}' in {elapsed_time:.1f}ms")
            
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
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            logger.error(f"_edit_single_message: Failed to edit message {message_id} for '{display_name}' after {elapsed_time:.1f}ms: {e}", exc_info=True)
            return e 