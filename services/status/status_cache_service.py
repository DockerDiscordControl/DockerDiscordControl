# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

# SERVICE FIRST: Container Status Cache Service - PASS-THROUGH TO SINGLE CACHE

import logging
import os
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from copy import deepcopy

logger = logging.getLogger('ddc.status_cache_service')

class StatusCacheService:
    """Pass-through service to ContainerStatusService for single cache architecture.

    This service maintains backward compatibility while delegating all caching
    to ContainerStatusService, creating a single source of truth for all status data.

    Migration Notes:
    - All cache operations now route through ContainerStatusService
    - ContainerStatusService handles both raw Docker data AND formatted status tuples
    - No more dual-cache synchronization issues
    - Cache invalidation is simplified
    """

    def __init__(self):
        """Initialize the StatusCacheService as a pass-through to ContainerStatusService."""
        # Import here to avoid circular dependencies
        from services.infrastructure.container_status_service import get_container_status_service
        self._container_status_service = get_container_status_service()

        # Keep cache_ttl_seconds for compatibility, but it's now managed by ContainerStatusService
        cache_duration = int(os.environ.get('DDC_DOCKER_CACHE_DURATION', '30'))
        self.cache_ttl_seconds = int(cache_duration * 2.5)  # For backward compatibility only

        logger.info(f"StatusCacheService initialized as pass-through to ContainerStatusService")

    def get(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get cached entry for a container from the single cache.

        Args:
            container_name: Name of the container

        Returns:
            Dict with 'data' and 'timestamp' keys, or None if not cached
        """
        try:
            # Get formatted status from ContainerStatusService
            cached_data = self._container_status_service.get_formatted_status(container_name)
            if cached_data:
                return deepcopy(cached_data)
            return None
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error getting cached status for {container_name}: {e}", exc_info=True)
            return None

    def set(self, container_name: str, data: Any, timestamp: datetime = None) -> None:
        """Set cached entry for a container in the single cache.

        Args:
            container_name: Name of the container
            data: Status data to cache (typically a tuple)
            timestamp: Optional timestamp (defaults to now)
        """
        try:
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)

            # Store formatted status in ContainerStatusService
            self._container_status_service.set_formatted_status(container_name, data, timestamp)
            logger.debug(f"Cached status for {container_name} via pass-through")
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error setting cached status for {container_name}: {e}", exc_info=True)

    def set_error(self, container_name: str, error_msg: str = None) -> None:
        """Cache an error state for a container.

        Args:
            container_name: Name of the container
            error_msg: Optional error message
        """
        try:
            self._container_status_service.set_formatted_status(
                container_name,
                None,
                datetime.now(timezone.utc),
                error=error_msg or "Status check failed"
            )
            logger.debug(f"Cached error state for {container_name}: {error_msg}")
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error setting error state for {container_name}: {e}", exc_info=True)

    def copy(self) -> Dict[str, Dict[str, Any]]:
        """Get a copy of all formatted statuses.

        Returns:
            Dict of all cached formatted statuses
        """
        try:
            return self._container_status_service.get_all_formatted_statuses()
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error copying cache: {e}", exc_info=True)
            return {}

    def clear(self) -> None:
        """Clear all cache entries."""
        try:
            self._container_status_service.clear_cache()
            logger.info("Cache cleared via pass-through")
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error clearing cache: {e}", exc_info=True)

    def remove(self, container_name: str) -> bool:
        """Remove a specific container from cache.

        Args:
            container_name: Name of the container to remove

        Returns:
            True if removed, False if not found
        """
        try:
            result = self._container_status_service.invalidate_container(container_name)
            if result:
                logger.debug(f"Removed {container_name} from cache via pass-through")
            return result
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error removing {container_name} from cache: {e}", exc_info=True)
            return False

    def _is_cache_valid(self, cached_entry: Dict[str, Any]) -> bool:
        """Check if a cache entry is still valid.

        This method is kept for backward compatibility but the actual
        TTL check is now done in ContainerStatusService.

        Args:
            cached_entry: Cache entry to check

        Returns:
            True if still valid, False if expired
        """
        # This is now handled by ContainerStatusService
        return True

    def items(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Get all cache items.

        Returns:
            List of (container_name, cache_entry) tuples
        """
        cache_copy = self.copy()
        return list(cache_copy.items())

    def get_cache_age_for_display(self, timestamp: datetime) -> str:
        """Format cache age for human-readable display.

        Args:
            timestamp: Timestamp to format

        Returns:
            Human-readable age string
        """
        now = datetime.now(timezone.utc)

        # Ensure timestamp is timezone-aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        age = now - timestamp
        seconds = int(age.total_seconds())

        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}m ago"
        else:
            hours = seconds // 3600
            return f"{hours}h ago"

    def bulk_set(self, entries: Dict[str, Tuple[Any, datetime]]) -> None:
        """Set multiple cache entries at once.

        Args:
            entries: Dict mapping container_name to (data, timestamp) tuples
        """
        for container_name, (data, timestamp) in entries.items():
            self.set(container_name, data, timestamp)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        try:
            return self._container_status_service.get_cache_stats()
        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error getting cache stats: {e}", exc_info=True)
            return {
                'total_entries': 0,
                'error': str(e)
            }

# ============================================================================ #
# SERVICE INSTANCE                                                              #
# ============================================================================ #

# Global service instance
_status_cache_service: Optional[StatusCacheService] = None

def get_status_cache_service() -> StatusCacheService:
    """Get the global status cache service instance."""
    global _status_cache_service
    if _status_cache_service is None:
        _status_cache_service = StatusCacheService()
    return _status_cache_service
