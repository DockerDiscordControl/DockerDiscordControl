#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Profile Service

Adaptive timeout and performance learning system for Docker containers.
Tracks response times, success rates, and provides intelligent timeout calculations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .models import (
    PerformanceProfile,
    PerformanceConfig,
    ContainerClassification
)
from utils.logging_utils import get_module_logger

logger = get_module_logger('performance_service')


class PerformanceProfileService:
    """
    Service for managing container performance profiles and adaptive timeouts.

    Responsibilities:
    - Track response times and success rates per container
    - Calculate adaptive timeouts based on historical performance
    - Classify containers as fast/slow for scheduling optimization
    - Provide performance statistics and insights
    """

    def __init__(self):
        """Initialize performance profile service."""
        self._profiles: Dict[str, PerformanceProfile] = {}
        self._config: PerformanceConfig = self._create_default_config()
        logger.info("PerformanceProfileService initialized")

    def _create_default_config(self) -> PerformanceConfig:
        """Create default performance configuration aligned with Docker timeouts."""
        try:
            # SERVICE FIRST: Use direct timeout values instead of old docker_utils
            # These values come from DDC_FAST_STATS_TIMEOUT and DDC_FAST_INFO_TIMEOUT (both default to 45.0s)
            stats_timeout_ms = 45.0 * 1000  # 45 seconds in milliseconds
            info_timeout_ms = 45.0 * 1000   # 45 seconds in milliseconds

            # Get Docker timeouts for alignment
            max_docker_timeout = max(stats_timeout_ms, info_timeout_ms)

            config = PerformanceConfig(
                min_timeout=5000,      # 5 seconds minimum
                max_timeout=int(max_docker_timeout),  # Match Docker config timeouts
                default_timeout=int(min(30000, max_docker_timeout * 0.8)), # 30s or 80% of max Docker timeout
                slow_threshold=8000,   # 8+ seconds = slow container
                history_window=20,     # Keep last 20 measurements
                retry_attempts=3,      # Maximum retry attempts
                timeout_multiplier=2.0 # Timeout = avg_time * multiplier
            )

            logger.info(f"Performance config aligned with Docker timeouts: max={max_docker_timeout}ms")
            return config

        except (ImportError, AttributeError, KeyError, TypeError) as e:
            # Fallback to conservative values if import fails
            logger.warning(f"Failed to align with Docker timeouts, using conservative defaults: {e}", exc_info=True)
            return PerformanceConfig()  # Use default values from dataclass

    def get_profile(self, container_name: str) -> PerformanceProfile:
        """
        Get or create performance profile for a container.

        Args:
            container_name: Name of the container

        Returns:
            PerformanceProfile for the container
        """
        if container_name not in self._profiles:
            self._profiles[container_name] = PerformanceProfile(
                container_name=container_name,
                response_times=[],
                avg_response_time=float(self._config.default_timeout),
                max_response_time=float(self._config.default_timeout),
                min_response_time=1000.0,
                success_rate=1.0,
                total_attempts=0,
                successful_attempts=0,
                is_slow=False,
                last_updated=datetime.now(timezone.utc)
            )
            logger.debug(f"Created new performance profile for container: {container_name}")

        return self._profiles[container_name]

    def update_performance(self, container_name: str, response_time: float, success: bool) -> None:
        """
        Update container performance history with new measurement.

        Args:
            container_name: Name of the container
            response_time: Response time in milliseconds
            success: Whether the request was successful
        """
        profile = self.get_profile(container_name)

        # Update attempt counters
        profile.total_attempts += 1
        if success:
            profile.successful_attempts += 1
            profile.response_times.append(response_time)

        # Maintain sliding window
        if len(profile.response_times) > self._config.history_window:
            profile.response_times = profile.response_times[-self._config.history_window:]

        # Calculate new statistics
        if profile.response_times:
            profile.avg_response_time = sum(profile.response_times) / len(profile.response_times)
            profile.max_response_time = max(profile.response_times)
            profile.min_response_time = min(profile.response_times)

        profile.success_rate = profile.successful_attempts / profile.total_attempts
        profile.is_slow = profile.avg_response_time > self._config.slow_threshold
        profile.last_updated = datetime.now(timezone.utc)

        if success:
            logger.debug(f"Performance update for {container_name}: avg={profile.avg_response_time:.0f}ms, "
                        f"success_rate={profile.success_rate:.2f}, is_slow={profile.is_slow}")

    def get_adaptive_timeout(self, container_name: str) -> float:
        """
        Calculate adaptive timeout based on container performance history.

        Args:
            container_name: Name of the container

        Returns:
            Adaptive timeout in milliseconds
        """
        profile = self.get_profile(container_name)

        # Base timeout on average response time with safety margin
        adaptive_timeout = max(
            profile.avg_response_time * self._config.timeout_multiplier,
            profile.max_response_time * 1.5,  # 1.5x worst recorded time
            float(self._config.min_timeout)  # Never go below minimum
        )

        # Cap at maximum timeout
        adaptive_timeout = min(adaptive_timeout, float(self._config.max_timeout))

        # Add extra time for containers with poor success rate
        if profile.success_rate < 0.8:
            adaptive_timeout *= 1.5
            logger.debug(f"Increased timeout for {container_name} due to low success rate: {profile.success_rate:.2f}")

        return adaptive_timeout

    def classify_containers(self, container_names: List[str]) -> ContainerClassification:
        """
        Classify containers into fast/slow/unknown based on performance history.

        Args:
            container_names: List of container names to classify

        Returns:
            ContainerClassification with containers grouped by performance
        """
        fast_containers = []
        slow_containers = []
        unknown_containers = []

        for container_name in container_names:
            profile = self.get_profile(container_name)

            # Unknown if no successful attempts yet
            if profile.total_attempts == 0:
                unknown_containers.append(container_name)
                continue

            # Slow if marked as slow or poor success rate
            if profile.is_slow or profile.success_rate < 0.8:
                slow_containers.append(container_name)
                logger.debug(f"Classified {container_name} as slow: avg={profile.avg_response_time:.0f}ms, "
                           f"success_rate={profile.success_rate:.2f}")
            else:
                fast_containers.append(container_name)

        return ContainerClassification(
            fast_containers=fast_containers,
            slow_containers=slow_containers,
            unknown_containers=unknown_containers
        )

    def get_config(self) -> PerformanceConfig:
        """Get current performance configuration."""
        return self._config

    def get_all_profiles(self) -> Dict[str, PerformanceProfile]:
        """Get all tracked performance profiles."""
        return self._profiles.copy()


# Singleton instance
_performance_service_instance: PerformanceProfileService | None = None


def get_performance_service() -> PerformanceProfileService:
    """
    Get the singleton PerformanceProfileService instance.

    Returns:
        PerformanceProfileService instance
    """
    global _performance_service_instance
    if _performance_service_instance is None:
        _performance_service_instance = PerformanceProfileService()
    return _performance_service_instance
