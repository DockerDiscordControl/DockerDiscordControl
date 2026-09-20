#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Status Fetch Service

Handles Docker container status fetching with intelligent retry logic,
adaptive timeouts, and query cooldown management.
"""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Tuple, Any, Dict

from services.infrastructure.container_status_service import get_docker_info_dict_service_first, get_docker_stats_service_first
from services.docker_status import get_performance_service
from utils.logging_utils import get_module_logger

logger = get_module_logger('docker_fetch_service')


class DockerStatusFetchService:
    """
    Service for fetching Docker container status with retry logic.

    Responsibilities:
    - Fetch container info and stats with adaptive timeouts
    - Intelligent retry strategy with exponential backoff
    - Query cooldown management to prevent API overload
    - Emergency fetch as last resort
    - Performance tracking integration
    """

    def __init__(self):
        """Initialize Docker status fetch service."""
        self._last_docker_query: Dict[str, float] = {}
        from utils.settings import get_setting
        self._query_cooldown = get_setting('DDC_DOCKER_QUERY_COOLDOWN', 2)
        logger.info(f"DockerStatusFetchService initialized (cooldown: {self._query_cooldown}s)")

    async def fetch_with_retries(self, docker_name: str) -> Tuple[str, Any, Any]:
        """
        Fetch container data with intelligent retry strategy.

        Args:
            docker_name: Name of the Docker container

        Returns:
            Tuple of (container_name, info, stats)
        """
        # Apply query cooldown
        await self._apply_query_cooldown(docker_name)

        # Record this query time
        self._last_docker_query[docker_name] = time.time()

        start_time = time.time()
        perf_service = get_performance_service()
        config = perf_service.get_config()

        last_exception = None

        for attempt in range(config.retry_attempts):
            try:
                # Calculate timeout for this attempt (increases with each retry)
                base_timeout = perf_service.get_adaptive_timeout(docker_name)
                current_timeout = base_timeout * (1.5 ** attempt)  # Exponential backoff

                logger.debug(f"Fetching {docker_name} - attempt {attempt + 1}/{config.retry_attempts}, "
                           f"timeout: {current_timeout:.0f}ms")

                attempt_start = time.time()
                timeout_seconds = current_timeout / 1000.0  # Convert ms to seconds

                try:
                    # One Docker query per attempt (wait_for cancels it on timeout)
                    info, stats = await asyncio.wait_for(
                        self._fetch_info_and_stats(docker_name, timeout_seconds),
                        timeout=timeout_seconds
                    )

                    attempt_time = (time.time() - attempt_start) * 1000

                    # Update performance history
                    perf_service.update_performance(docker_name, attempt_time, True)

                    total_time = (time.time() - start_time) * 1000
                    if attempt > 0:
                        logger.info(f"Successfully fetched {docker_name} on attempt {attempt + 1} "
                                  f"(attempt: {attempt_time:.1f}ms, total: {total_time:.1f}ms)")

                    return docker_name, info, stats

                except asyncio.TimeoutError as e:
                    last_exception = e
                    attempt_time = (time.time() - attempt_start) * 1000

                    # A timeout is a failed attempt - it must lower the success rate
                    perf_service.update_performance(docker_name, attempt_time, False)

                    logger.warning(f"Timeout for {docker_name} on attempt {attempt + 1}/{config.retry_attempts} "
                                 f"after {attempt_time:.1f}ms")

                    if attempt < config.retry_attempts - 1:
                        # Short delay before retry
                        await asyncio.sleep(0.5)

            except (RuntimeError, OSError, ValueError, TypeError) as e:
                last_exception = e
                logger.error(f"Error fetching {docker_name} on attempt {attempt + 1}: {e}", exc_info=True)

                if attempt < config.retry_attempts - 1:
                    await asyncio.sleep(0.5)

        # All retries failed - try one last, bounded emergency fetch
        logger.warning(f"All retries failed for {docker_name}, attempting emergency fetch")
        return await self._emergency_full_fetch(docker_name, last_exception)

    async def _emergency_full_fetch(self, docker_name: str, last_exception: Exception) -> Tuple[str, Any, Any]:
        """
        Emergency fetch with the maximum configured timeout - last resort to get complete data.

        Only counts as a success for the performance profile if it actually returned
        container info.

        Args:
            docker_name: Name of the Docker container
            last_exception: Exception from previous attempts

        Returns:
            Tuple of (container_name, info, stats) or (container_name, exception, None)
        """
        perf_service = get_performance_service()
        # Bounded by the longest configured Docker timeout instead of waiting (up to 300s)
        emergency_timeout = perf_service.get_config().max_timeout / 1000.0
        start_emergency = time.time()

        try:
            logger.info(f"Emergency full fetch for {docker_name} (timeout: {emergency_timeout:.0f}s)")

            info, stats = await asyncio.wait_for(
                self._fetch_info_and_stats(docker_name, emergency_timeout),
                timeout=emergency_timeout
            )
            emergency_time = (time.time() - start_emergency) * 1000

            if not isinstance(info, dict):
                # Container not found / Docker error - no data, so not a success
                perf_service.update_performance(docker_name, emergency_time, False)
                logger.warning(f"Emergency fetch for {docker_name} returned no data after {emergency_time:.1f}ms: {info}")
                return docker_name, info, stats

            # Mark as slow container for future reference
            perf_service.update_performance(docker_name, emergency_time, True)

            logger.info(f"Emergency fetch successful for {docker_name} after {emergency_time:.1f}ms")
            return docker_name, info, stats

        except asyncio.TimeoutError:
            perf_service.update_performance(docker_name, (time.time() - start_emergency) * 1000, False)
            logger.error(f"Emergency fetch for {docker_name} timed out after {emergency_timeout:.0f}s")
            return docker_name, last_exception, None

        except (RuntimeError, OSError) as e:
            # Even emergency fetch failed - update performance and return error
            perf_service.update_performance(docker_name, 0, False)
            logger.error(f"Emergency fetch failed for {docker_name}: {e}", exc_info=True)
            return docker_name, last_exception, None

    async def _fetch_info_and_stats(self, docker_name: str, timeout_seconds: float) -> Tuple[Any, Any]:
        """
        Fetch container info and stats with a single Docker query.

        The info call does the full fetch (incl. CPU/RAM) and fills the
        ContainerStatusService cache, so the stats call is served from that cache
        instead of running a second full fetch (new client + ping) in parallel.
        Errors are returned as values, like gather(return_exceptions=True) before.

        Returns:
            Tuple of (info, stats)
        """
        try:
            info = await get_docker_info_dict_service_first(docker_name, timeout_seconds)
        except Exception as e:  # noqa: BLE001 - returned as value, handled by the caller
            return e, None

        if not isinstance(info, dict):
            # Not found / error - there are no stats to fetch
            return info, None

        try:
            stats = await get_docker_stats_service_first(docker_name, timeout_seconds)
        except Exception as e:  # noqa: BLE001 - returned as value, handled by the caller
            stats = e
        return info, stats

    async def _apply_query_cooldown(self, docker_name: str) -> None:
        """
        Apply query cooldown to prevent Docker API overload.

        Args:
            docker_name: Name of the Docker container
        """
        if self._query_cooldown <= 0:
            return

        last_query_time = self._last_docker_query.get(docker_name, 0)
        time_since_last = time.time() - last_query_time

        if time_since_last < self._query_cooldown:
            wait_time = self._query_cooldown - time_since_last
            logger.debug(f"[QUERY_COOLDOWN] Waiting {wait_time:.1f}s before querying {docker_name}")
            await asyncio.sleep(wait_time)

    def get_query_cooldown(self) -> int:
        """Get current query cooldown in seconds."""
        return self._query_cooldown

    def set_query_cooldown(self, seconds: int) -> None:
        """
        Set query cooldown in seconds.

        Args:
            seconds: Cooldown time in seconds (0 to disable)
        """
        self._query_cooldown = max(0, seconds)
        logger.info(f"Query cooldown set to {self._query_cooldown}s")

    def clear_query_history(self) -> None:
        """Clear query history (for testing/debugging)."""
        self._last_docker_query.clear()
        logger.debug("Cleared query history")


# Singleton instance
_fetch_service_instance: DockerStatusFetchService | None = None


def get_fetch_service() -> DockerStatusFetchService:
    """
    Get the singleton DockerStatusFetchService instance.

    Returns:
        DockerStatusFetchService instance
    """
    global _fetch_service_instance
    if _fetch_service_instance is None:
        _fetch_service_instance = DockerStatusFetchService()
    return _fetch_service_instance
