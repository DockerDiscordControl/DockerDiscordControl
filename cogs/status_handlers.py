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
import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union
import discord

# Import necessary utilities
from utils.logging_utils import get_module_logger
from services.infrastructure.container_status_service import (
    get_docker_info_dict_service_first, get_docker_stats_service_first, get_container_status_service)
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

# Parallel Docker fetches per bulk status run. stats(stream=False) takes ~1.7 s per running
# container (34 containers: 3 parallel -> 21 s, 8 parallel -> 8 s). Status fetches don't use
# the DockerClientService pool (get_docker_client_async opens its own client per fetch), but
# each one blocks a default-executor thread (asyncio.to_thread) for that time.
BULK_FETCH_MAX_CONCURRENCY = 6


def _bulk_fetch_concurrency() -> int:
    """Parallel fetches for one bulk run: up to 6, but keep 2 default-executor threads free
    for other asyncio.to_thread work (e.g. the auto-action regex check has a 0.5 s budget)."""
    cpu_count = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    default_workers = min(32, cpu_count + 4)  # ThreadPoolExecutor default used by to_thread
    return max(3, min(BULK_FETCH_MAX_CONCURRENCY, default_workers - 2))

def _age_hint_threshold_seconds(handler) -> float:
    """From when on a cached status is old enough to deserve an age hint in the embed.

    The status loop refreshes every ``status_refresh_interval_seconds``, so an age anywhere
    between zero and one interval is entirely normal. The hint should therefore say "a refresh
    was missed", not "we are somewhere inside the normal cycle" - hence one and a half intervals.

    Both display sites used to compare against ``cache_ttl_seconds``, which is ``interval * 2.5``.
    With the 120 s interval configured on a real installation that meant data of up to five
    minutes was shown without any hint that it was old.

    Falls back to ``cache_ttl_seconds`` - the previous behaviour - when no interval has been
    published, e.g. for a bare mixin in tests.
    """
    interval = getattr(handler, 'status_refresh_interval_seconds', None)
    ttl = getattr(handler, 'cache_ttl_seconds', 0) or 0
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
        return ttl
    return interval * 1.5


def format_uptime(days: int, seconds: int) -> str:
    """"2d 3h 5m" from whole days and the seconds of the last day.

    The one place for this text - the status handlers used to build it three
    times (tests/spec/test_uptime_is_formatted_in_one_place.py).
    """
    hours, remainder = divmod(seconds, 3600)
    # Don't unpack into `_` - that would shadow the translation function
    minutes = remainder // 60
    uptime_parts = []
    if days > 0:
        uptime_parts.append(f"{days}d")
    if hours > 0:
        uptime_parts.append(f"{hours}h")
    if minutes > 0 or (days == 0 and hours == 0):
        uptime_parts.append(f"{minutes}m")
    return " ".join(uptime_parts) if uptime_parts else "< 1m"


def _watch_fields(info: Dict[str, Any]) -> Dict[str, Any]:
    """What the watchdog and the stack view read from the cache: State.Health.Status
    and RestartCount (Phase 4a), CPU and memory as percentages (Phase 4b), and the
    Compose stack label (Phase 4c)."""
    computed = info.get('_computed') or {}
    usage, limit = computed.get('memory_usage_mb'), computed.get('memory_limit_mb')
    return {
        "health": (info.get('State', {}).get('Health') or {}).get('Status'),
        "restart_count": info.get('RestartCount'),
        "cpu_percent": computed.get('cpu_percent'),
        "memory_percent": (usage / limit * 100) if usage is not None and limit else None,
        # The second memory yardstick, for containers started without --memory:
        # the usage itself, and the flag that says which of the two applies.
        "memory_mb": usage,
        "memory_limited": computed.get('memory_limited'),
        "compose_project": ((info.get('Config') or {}).get('Labels') or {}).get('com.docker.compose.project'),
    }


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
        logger.debug(f"[INTELLIGENT_BULK_FETCH] Starting adaptive bulk fetch for {len(container_names)} containers")

        # Classify containers by performance history for intelligent batching
        perf_service = get_performance_service()
        classification = perf_service.classify_containers(container_names)
        fast_containers = classification.fast_containers
        slow_containers = classification.slow_containers
        unknown_containers = classification.unknown_containers

        # Treat unknown containers as fast (parallel processing) since we don't have perf data yet
        if unknown_containers:
            logger.debug(f"[INTELLIGENT_BULK_FETCH] {len(unknown_containers)} containers have no performance history - treating as fast")
            fast_containers.extend(unknown_containers)

        if fast_containers and slow_containers:
            logger.debug(f"[INTELLIGENT_BULK_FETCH] Smart batching: {len(fast_containers)} fast, {len(slow_containers)} slow containers")
        elif slow_containers:
            logger.debug(f"[INTELLIGENT_BULK_FETCH] All {len(slow_containers)} containers classified as slow - using patient processing")
        else:
            logger.debug(f"[INTELLIGENT_BULK_FETCH] All {len(fast_containers)} containers classified as fast - using parallel processing")

        # Process containers with intelligent strategies
        all_results = []

        # Phase 1: Process fast containers in parallel (if any)
        if fast_containers:
            logger.debug(f"[INTELLIGENT_BULK_FETCH] Phase 1: Processing {len(fast_containers)} fast containers in parallel")

            # Use semaphore for controlled concurrency (see _bulk_fetch_concurrency)
            MAX_CONCURRENT_FAST = min(_bulk_fetch_concurrency(), len(fast_containers))
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_FAST)

            async def fetch_fast_container(container_name):
                async with semaphore:
                    fetch_service = get_fetch_service()
                    return await fetch_service.fetch_with_retries(container_name)

            fast_tasks = [fetch_fast_container(name) for name in fast_containers]
            fast_results = await asyncio.gather(*fast_tasks, return_exceptions=True)
            all_results.extend(fast_results)

            fast_time = (time.time() - start_time) * 1000
            logger.debug(f"[INTELLIGENT_BULK_FETCH] Phase 1 completed: {len(fast_containers)} fast containers in {fast_time:.1f}ms")

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
            logger.debug(f"[INTELLIGENT_BULK_FETCH] Phase 2 completed: {len(slow_containers)} slow containers in {slow_time:.1f}ms")

        # PERFORMANCE: Cache server configs before processing - avoid repeated lookups
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()
        servers_by_docker_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}

        # Process all results into status tuples - ALWAYS WITH COMPLETE DATA
        status_results = {}
        successful_fetches = 0
        failed_fetches = 0

        # all_results holds the fast containers in order, then the slow ones, so a
        # result that came back as an exception can still be named. It used to be
        # logged and dropped, and the container was simply missing from the answer -
        # against this function's own promise of complete data, and impossible for a
        # caller to tell from "never asked" (review B25).
        fetched_names = list(fast_containers) + list(slow_containers)

        for fetched_name, result in zip(fetched_names, all_results):
            if isinstance(result, Exception):
                logger.error(f"[INTELLIGENT_BULK_FETCH] Exception in fetch result for "
                             f"{fetched_name}: {result}")
                status_results[fetched_name] = ContainerStatusResult.error_result(
                    docker_name=fetched_name,
                    error=result,
                    error_type='fetch'
                )
                failed_fetches += 1
                continue

            docker_name, info, stats = result

            # Find server config for this container (cached lookup)
            server_config = servers_by_docker_name.get(docker_name)

            if not server_config:
                # An ANSWER, not a silent gap: dropped, it was cached neither as
                # a status nor as an error and stayed on the loading icon
                logger.warning(f"[INTELLIGENT_BULK_FETCH] No server config found for {docker_name}")
                status_results[docker_name] = ContainerStatusResult.error_result(
                    docker_name=docker_name, error_type='no_config',
                    error=RuntimeError("no server configuration"))
                failed_fetches += 1
                continue

            # Process the fetched data - ALWAYS COMPLETE DETAILS
            display_name = server_config.get('name', docker_name)
            details_allowed = server_config.get('allow_detailed_status', True)

            # "not info", like the single-container path a few hundred lines down:
            # an answer that is empty but not None used to be read as offline here
            # and as "not found" there, so one container had two verdicts depending
            # on which loop last touched it (review B37). What decides either way is
            # is_container_not_found(), which asks Docker itself.
            if not info and get_container_status_service().is_container_not_found(docker_name):
                # Docker answered "no such container" (deleted/renamed/being recreated): cached
                # like offline, but shown as "not found" instead of 🔴 / an endless 🔄
                status_results[docker_name] = ContainerStatusResult.not_found_result(
                    docker_name=docker_name,
                    display_name=display_name,
                    details_allowed=details_allowed
                )
                successful_fetches += 1
                continue

            if isinstance(info, Exception) or info is None:
                # NOT offline - a stopped container answers inspect normally, so
                # nothing was measured. Z3: never report that as "not running".
                logger.warning(f"[INTELLIGENT_BULK_FETCH] {docker_name} could not be asked: {info}")
                status_results[docker_name] = ContainerStatusResult.error_result(
                    docker_name=docker_name, error_type='fetch',
                    error=info if isinstance(info, Exception) else RuntimeError("no answer from Docker"))
                failed_fetches += 1
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

                        uptime = format_uptime(delta.days, delta.seconds)
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
                            uptime = format_uptime(uptime_sec // 86400, uptime_sec % 86400)
                    # Fallback to old stats method if SERVICE FIRST data not available
                    elif isinstance(stats, dict) and stats:
                        # get_docker_stats_service_first() returns a dict, same as in get_status()
                        cpu_percent = stats.get('cpu_percent')
                        memory_mb = stats.get('memory_usage_mb')
                        cpu = f"{cpu_percent:.1f}%" if cpu_percent is not None else 'N/A'
                        ram = f"{memory_mb:.0f}MB" if memory_mb is not None else 'N/A'
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
                details_allowed=details_allowed, **_watch_fields(info)
            )
            successful_fetches += 1

        # Optional game-server player-count enrichment (opengsq). Runs as a separate,
        # timeout-guarded bulk query AFTER the docker fetch and never affects status.
        await self._enrich_status_with_player_counts(status_results, servers_by_docker_name)
        # Background support detection (probes online containers to gate the web UI's
        # "Spieler" checkbox). Fire-and-forget so it never adds latency to the status loop.
        self._schedule_support_probes(status_results, servers_by_docker_name)

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

    async def _enrich_status_with_player_counts(self, status_results: Dict[str, ContainerStatusResult],
                                                servers_by_docker_name: Dict[str, Any]) -> None:
        """Add live game-server player counts to running, query-enabled containers (opengsq).

        Controlled per-container via ``query_enabled`` (the player-count checkbox column in the web UI). The
        DDC_ENABLE_OPENGSQ setting is a global kill-switch (default ON, read dynamically) so
        ops can disable all querying without unchecking every container. Fully best-effort:
        any failure leaves players_online=None and never affects the status results.
        """
        try:
            from app.utils.web_helpers import _get_advanced_setting
            if not _get_advanced_setting('DDC_ENABLE_OPENGSQ', True, bool):
                return  # global kill-switch off -> zero work, no opengsq import

            from services.infrastructure.game_query_service import (
                get_game_query_service, GameQueryRequest, DEFAULT_QUERY_TIMEOUT_SECONDS,
                TOKEN_PROTOCOLS)
            svc = get_game_query_service()

            targets = []
            for docker_name, result in status_results.items():
                if not (isinstance(result, ContainerStatusResult) and result.success and result.is_running):
                    continue
                cfg = servers_by_docker_name.get(docker_name) or {}
                if not cfg.get('query_enabled'):
                    continue
                # Effective protocol: for auto-probeable protocols (source/minecraft) trust the
                # one that actually answered during support detection, so a Minecraft server is
                # queried as minecraft without the user setting anything. Token protocols
                # (satisfactory) always use the user's explicit choice.
                proto = cfg.get('query_protocol', 'source')
                try:
                    from services.infrastructure.game_query_support_service import get_game_query_support_service
                    support = get_game_query_support_service()
                    # Skip servers the support detection already found unreachable. Querying one
                    # costs a full timeout every single cycle and can never succeed (finding P1:
                    # with 6 enabled containers and one dead server that was ~10 s of every
                    # status cycle). Nothing is lost if it comes back: a non-final verdict keeps
                    # being re-probed by _run_support_probes on its own schedule, and a final one
                    # is re-checked through the manual "test now" button. An unknown container
                    # yields None here and is queried normally.
                    if support.is_supported(docker_name) is False:
                        continue
                    if proto not in TOKEN_PROTOCOLS:
                        detected = support.get_protocol(docker_name)
                        if detected:
                            proto = detected
                except (ImportError, RuntimeError, AttributeError):
                    pass
                host, ports = await svc.resolve_query_candidates(
                    docker_name, cfg.get('query_host', ''), cfg.get('query_port', 0), proto)
                if not host or not ports:
                    continue
                targets.append(GameQueryRequest(
                    container_name=docker_name,
                    protocol=proto,
                    host=host, port=ports[0], candidate_ports=tuple(ports[1:4]),  # cap fallbacks
                    timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                    token=cfg.get('query_token', ''),
                ))

            if not targets:
                return

            # Overall best-effort budget: a batch of dead multi-port servers can't stall the
            # status loop (per-port wait_for already bounds each individual query).
            try:
                query_results = await asyncio.wait_for(svc.get_bulk_game_queries(targets), timeout=20.0)
            except asyncio.TimeoutError:
                logger.debug("[GAME_QUERY] Player-count enrichment exceeded budget; skipping cycle")
                return
            # Report the outcome back to the verdict store. A positive verdict is otherwise never
            # re-checked, so a server that used to answer and no longer does kept costing a full
            # timeout every cycle (finding P1b). Repeated failures put it back into probing.
            try:
                from services.infrastructure.game_query_support_service import get_game_query_support_service
                verdicts = get_game_query_support_service()
            except (ImportError, RuntimeError, AttributeError):
                verdicts = None

            for docker_name, q in query_results.items():
                if q.success and q.players_online is not None and docker_name in status_results:
                    status_results[docker_name].players_online = q.players_online
                    status_results[docker_name].max_players = q.max_players
                if verdicts is not None:
                    if q.success:
                        verdicts.note_query_success(docker_name)
                    elif q.error_type in ('timeout', 'unreachable'):
                        verdicts.note_query_failure(docker_name)
        except (ImportError, RuntimeError, AttributeError, KeyError, TypeError) as e:
            logger.debug(f"[GAME_QUERY] Player-count enrichment skipped: {e}")

    def _schedule_support_probes(self, status_results: Dict[str, ContainerStatusResult],
                                 servers_by_docker_name: Dict[str, Any]) -> None:
        """Fire-and-forget background task that probes online containers for query support
        (gates the web UI checkbox). Single-flight; never blocks or breaks the status loop."""
        try:
            existing = getattr(self, '_support_probe_task', None)
            if existing is not None and not existing.done():
                return  # a probe pass is still running
            online = [n for n, r in status_results.items()
                      if isinstance(r, ContainerStatusResult) and r.success and r.is_running]
            online_set = set(online)
            offline = [n for n in status_results.keys() if n not in online_set]
            if not online and not offline:
                return
            self._support_probe_task = asyncio.create_task(
                self._run_support_probes(online, offline, dict(servers_by_docker_name)))
        except RuntimeError:
            pass  # no running event loop (e.g. unit tests) -> skip silently

    async def _run_support_probes(self, online_names: List[str], offline_names: List[str],
                                  servers_by_docker_name: Dict[str, Any]) -> None:
        """Reset the probe window for offline containers, then probe each due online one."""
        try:
            from app.utils.web_helpers import _get_advanced_setting
            if not _get_advanced_setting('DDC_ENABLE_OPENGSQ', True, bool):
                return  # global kill-switch off
            from services.infrastructure.game_query_service import get_game_query_service
            from services.infrastructure.game_query_support_service import get_game_query_support_service
            svc = get_game_query_service()
            support = get_game_query_support_service()
            # Pick up externally-written verdicts (web-process manual re-test) before deciding
            # what to probe or recording, so the bot never reverts them.
            support.reload()

            # Offline containers get a fresh 15-min window on their next boot.
            for name in offline_names:
                support.note_offline(name)

            now = time.monotonic()
            semaphore = asyncio.Semaphore(3)

            async def _probe(name: str) -> None:
                if not support.should_probe(name, now):
                    return
                cfg = servers_by_docker_name.get(name) or {}
                async with semaphore:
                    support.mark_probed(name, time.monotonic())
                    ok, proto, port = await svc.detect_support(
                        name, cfg.get('query_host', ''), cfg.get('query_port', 0))
                support.record_result(name, ok, proto, port)

            await asyncio.gather(*[_probe(n) for n in online_names], return_exceptions=True)
        except (ImportError, RuntimeError, AttributeError, KeyError, TypeError) as e:
            logger.debug(f"[QUERY_SUPPORT] Support-probe pass skipped: {e}")

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

        logger.debug(f"[BULK_UPDATE] Updating cache for {len(containers_needing_update)}/{len(container_names)} containers with missing cache")

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
        # A cancellation is not an error - it is how asyncio says "stop". Caught
        # and logged like a failure, the task reported itself finished although it
        # had been told to stop: on shutdown the bot waited for work that was
        # already ending, and a caller's wait_for no longer stopped what it timed
        # out on (review B30).
        except asyncio.CancelledError:
            raise
        except (RuntimeError, KeyError, TypeError) as e:
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

            if not info and get_container_status_service().is_container_not_found(docker_name):
                # Same "not found" state as bulk_fetch_container_status (keeps it on refreshes)
                return ContainerStatusResult.not_found_result(
                    docker_name=docker_name,
                    display_name=display_name,
                    details_allowed=details_allowed
                )

            if not info:
                # Nothing measured, and Docker did not say it is gone (above)
                logger.warning(f"Container info for {docker_name} could not be read - reported as unknown")
                return ContainerStatusResult.error_result(
                    docker_name=docker_name, error_type='fetch',
                    error=RuntimeError("no answer from Docker"))

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

                        uptime = format_uptime(delta.days, delta.seconds)

                    except ValueError as e:
                        logger.error(f"Could not parse StartedAt timestamp '{started_at_str}' for {docker_name}: {e}")
                        uptime = "Error"

                # Fetch CPU and RAM only if allowed (SERVICE FIRST)
                if details_allowed:
                    stats_dict = await get_docker_stats_service_first(docker_name)
                    if stats_dict and isinstance(stats_dict, dict):
                        # No default: a key that is not there was not measured, and the
                        # line below turns that into 'N/A'. With 0.0 it used to read like
                        # an idle container instead - a number nobody measured, and one the
                        # bulk path shows as N/A for the same answer (review B20).
                        cpu_percent = stats_dict.get('cpu_percent')
                        memory_mb = stats_dict.get('memory_usage_mb')
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
                details_allowed=details_allowed, **_watch_fields(info)
            )

        except Exception as e:  # noqa: BLE001
            # Broad on purpose. This is the SINGLE-container path - the refresh
            # button on a container panel - and its whole job is to come back
            # with a ContainerStatusResult, a failed one included, so the panel
            # can show the failure in place.
            #
            # The tuple that stood here listed five types and not the one the
            # chain underneath actually produces (review E16):
            #   get_docker_info_dict_service_first -> get_container_status
            #     -> _fetch_container_status -> get_docker_client_async,
            # which raises DockerConnectionError when the daemon is gone. The
            # button raised instead of showing a failed container.
            #
            # The bulk path is not affected: it asks check_connectivity first,
            # and review B25 turns an exception in a gathered result into a
            # named error result. This path has neither, which is why the same
            # sentence had to be answered twice.
            logger.error("Error getting status for %s: %s: %s",
                         docker_name, type(e).__name__, e, exc_info=True)
            return ContainerStatusResult.error_result(
                docker_name=docker_name,
                error=e,
                error_type=type(e).__name__.lower()
            )

    async def _generate_status_embed_and_view(self, channel_id: int, display_name: str,
                                       server_conf: Dict[str, Any], current_config: Dict[str, Any],
                                       allow_toggle: bool = True,
                                       force_collapse: bool = False) -> Tuple[discord.Embed, Optional[discord.ui.View], bool]:
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
        # Read AFTER the pending handling above: it fetches the container's current
        # status when a pending action passes its timeout and writes it into the
        # cache. Reading the entry before that block meant the message showed the
        # state from BEFORE the action - or "loading" when there was no entry at all
        # (review B9).
        cached_entry = self.status_cache_service.get(docker_name)
        if cached_entry:
            cache_age = (now - cached_entry['timestamp']).total_seconds()
            # PATIENT APPROACH: ALWAYS use cache if available - background collects fresh data
            # Show cache age when data is older so user knows freshness
            if cache_age < _age_hint_threshold_seconds(self):
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
                # Loading status. Plain lines, no box: this used to draw a
                # ┌── │ └── frame inside a code block, which does not reflow and
                # broke apart on a phone (same finding as the "processing"
                # message in control_ui.py, 2026-09-19). The footer was a
                # hard-coded English "Background data collection in progress".
                embed = discord.Embed(
                    title=f"🔄 {_('Loading Status')}",
                    description=f"{_('Fetching container data...')}\n"
                                f"⏱️ {_('Background process running')}\n"
                                f"📊 {_('Please wait for fresh data')}",
                    color=0x3498db
                )
                embed.set_footer(text="https://ddc.bot")
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
                players_online = status_result.players_online
                max_players = status_result.max_players
                status_color = 0x00b300 if running else 0xe74c3c

                # Continue with box embed generation (same as tuple case)
                # PERFORMANCE OPTIMIZATION: Use cached translations
                embed_helper = get_embed_helper_service()
                cached_translations = embed_helper.get_translations(lang)
                online_text = cached_translations['online_text']
                offline_text = cached_translations['offline_text']
                status_text = online_text if running else offline_text
                current_emoji = "🟢" if running else "🔴"
                if status_result.not_found:
                    # Deleted/renamed container - own state instead of "offline"
                    status_text = _("Not found")
                    current_emoji = "❓"

                # Check if we should always collapse
                # CRITICAL FIX: Use docker_name (stable identifier) instead of display_name for expanded state lookup
                # This ensures consistency with how expanded states are set throughout the codebase
                is_expanded = self.expanded_states.get(docker_name, False) and not force_collapse

                # PERFORMANCE OPTIMIZATION: Use cached translations
                cpu_text = cached_translations['cpu_text']
                ram_text = cached_translations['ram_text']
                uptime_text = cached_translations['uptime_text']
                detail_denied_text = cached_translations['detail_denied_text']
                players_text = cached_translations['players_text']

                # Game-server player count line (only when we have query data). Shown in
                # both collapsed and expanded views since it's the key info for a game server.
                # Shared helper so the toggle path (control_ui.py) renders it identically.
                from services.discord.embed_helper_service import format_player_line
                player_line = format_player_line(players_online, max_players, players_text)

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

                # Older than 1.5 refresh intervals (a flag hid this before)
                if 'embed_cache_indicator' in locals() and embed_cache_indicator:
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
                        if player_line:
                            description_parts.append(player_line)
                    else:
                        if player_line:
                            description_parts.append(player_line)
                        description_parts.append(f"│ \u2022 ▼ Expand for details\n")
                elif running and not details_allowed:
                    if player_line:
                        description_parts.append(player_line)
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
                        channel_has_control_permission=_channel_has_permission(channel_id, server_conf),
                        channel_id=channel_id
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
            # CRITICAL FIX: Use docker_name (stable identifier) instead of display_name for expanded state lookup
            # This ensures consistency with how expanded states are set throughout the codebase
            is_expanded = self.expanded_states.get(docker_name, False) and not force_collapse

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

            # The age, as above
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
            # Get formatted time using the new time_only parameter
            current_time = format_datetime_with_timezone(now_footer, timezone_str, time_only=True)

            # Enhanced timestamp with cache age info
            if 'embed_cache_age' in locals() and embed_cache_age > _age_hint_threshold_seconds(self):
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
                view = ControlView(self, server_conf, running, channel_has_control_permission=channel_has_control, allow_toggle=allow_toggle, channel_id=channel_id)
        else:
            view = None # Ensure view is None if server_conf is missing or critical error

        return embed, view, running

    # Wrapper to set the update time (must accept allow_toggle)
    # =============================================================================
    # ULTRA-PERFORMANCE MESSAGE EDITING WITH BULK CACHE PRELOADING
    # =============================================================================

