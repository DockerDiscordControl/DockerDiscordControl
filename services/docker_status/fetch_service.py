#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Status Fetch Service

Handles Docker container status fetching with intelligent retry logic,
adaptive timeouts, and query cooldown management.
"""

from __future__ import annotations

import os
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
        self._query_cooldown = int(os.environ.get('DDC_DOCKER_QUERY_COOLDOWN', '2'))
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

                # Fetch info and stats in parallel with adaptive timeout
                timeout_seconds = current_timeout / 1000.0  # Convert ms to seconds
                info_task = asyncio.create_task(get_docker_info_dict_service_first(docker_name, timeout_seconds))
                stats_task = asyncio.create_task(get_docker_stats_service_first(docker_name, timeout_seconds))

                try:
                    info, stats = await asyncio.wait_for(
                        asyncio.gather(info_task, stats_task, return_exceptions=True),
                        timeout=current_timeout / 1000.0  # Convert to seconds
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
                    # Cancel running tasks to prevent event loop leaks
                    info_task.cancel()
                    stats_task.cancel()
                    # Wait for cancellation to complete
                    await asyncio.gather(info_task, stats_task, return_exceptions=True)

                    last_exception = e
                    attempt_time = (time.time() - attempt_start) * 1000 if 'attempt_start' in locals() else current_timeout

                    logger.warning(f"Timeout for {docker_name} on attempt {attempt + 1}/{config.retry_attempts} "
                                 f"after {attempt_time:.1f}ms")

                    if attempt < config.retry_attempts - 1:
                        # Short delay before retry
                        await asyncio.sleep(0.5)

            except (RuntimeError, OSError, ValueError, TypeError) as e:
                # Cancel running tasks on error
                if 'info_task' in locals():
                    info_task.cancel()
                if 'stats_task' in locals():
                    stats_task.cancel()
                # Wait for cancellation to complete
                if 'info_task' in locals() and 'stats_task' in locals():
                    await asyncio.gather(info_task, stats_task, return_exceptions=True)

                last_exception = e
                logger.error(f"Error fetching {docker_name} on attempt {attempt + 1}: {e}", exc_info=True)

                if attempt < config.retry_attempts - 1:
                    await asyncio.sleep(0.5)

        # All retries failed - try emergency fetch without timeout
        logger.warning(f"All retries failed for {docker_name}, attempting emergency fetch")
        return await self._emergency_full_fetch(docker_name, last_exception)

    async def _emergency_full_fetch(self, docker_name: str, last_exception: Exception) -> Tuple[str, Any, Any]:
        """
        Emergency fetch with no timeout limits - last resort to get complete data.

        Args:
            docker_name: Name of the Docker container
            last_exception: Exception from previous attempts

        Returns:
            Tuple of (container_name, info, stats) or (container_name, exception, None)
        """
        try:
            logger.info(f"Emergency full fetch for {docker_name} - no timeout limit")

            # NO timeout - wait however long it takes (use very long timeout)
            info_task = asyncio.create_task(get_docker_info_dict_service_first(docker_name, timeout=300.0))
            stats_task = asyncio.create_task(get_docker_stats_service_first(docker_name, timeout=300.0))

            start_emergency = time.time()
            info, stats = await asyncio.gather(info_task, stats_task, return_exceptions=True)
            emergency_time = (time.time() - start_emergency) * 1000

            # Mark as slow container for future reference
            perf_service = get_performance_service()
            perf_service.update_performance(docker_name, emergency_time, True)

            logger.info(f"Emergency fetch successful for {docker_name} after {emergency_time:.1f}ms")
            return docker_name, info, stats

        except (RuntimeError, OSError, asyncio.CancelledError) as e:
            # Even emergency fetch failed - update performance and return error
            perf_service = get_performance_service()
            perf_service.update_performance(docker_name, 0, False)
            logger.error(f"Emergency fetch failed for {docker_name}: {e}", exc_info=True)
            return docker_name, last_exception, None

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
