# =============================================================================
# SERVICE FIRST: Container Status Cache Service - SINGLE POINT OF TRUTH
# =============================================================================

import logging
import os
import threading
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone, timedelta
from copy import deepcopy

logger = logging.getLogger('ddc.status_cache_service')

class StatusCacheService:
    """Service First implementation for container status cache - SINGLE POINT OF TRUTH.

    This service is the single source of truth for container status caching.
    It manages the cache internally and provides thread-safe access.
    """

    def __init__(self):
        """Initialize the StatusCacheService with internal cache management."""
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # Cache configuration
        cache_duration = int(os.environ.get('DDC_DOCKER_CACHE_DURATION', '30'))
        self.cache_ttl_seconds = int(cache_duration * 2.5)  # Default 75s (as int)

        logger.info(f"StatusCacheService initialized with {self.cache_ttl_seconds}s TTL")

    def get(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get cached entry for a container.

        Args:
            container_name: Name of the container (display_name or docker_name)

        Returns:
            Dict with 'data' and 'timestamp' keys, or None if not cached
        """
        with self._lock:
            cached_entry = self._cache.get(container_name)

            if cached_entry:
                # Check if cache is still valid
                if self._is_cache_valid(cached_entry):
                    # Return a deep copy to prevent external modifications
                    return deepcopy(cached_entry)
                else:
                    # Remove expired entry
                    logger.debug(f"Removing expired cache for {container_name}")
                    del self._cache[container_name]

            return None

    def set(self, container_name: str, data: Any, timestamp: datetime = None) -> None:
        """Set cached entry for a container.

        Args:
            container_name: Name of the container
            data: Status data to cache (typically a tuple)
            timestamp: Optional timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        with self._lock:
            self._cache[container_name] = {
                'data': data,
                'timestamp': timestamp
            }
            logger.debug(f"Cached status for {container_name}")

    def set_error(self, container_name: str, error_msg: str = None) -> None:
        """Cache an error state for a container.

        Args:
            container_name: Name of the container
            error_msg: Optional error message
        """
        with self._lock:
            self._cache[container_name] = {
                'data': None,
                'timestamp': datetime.now(timezone.utc),
                'error': error_msg or "Status check failed"
            }
            logger.debug(f"Cached error state for {container_name}: {error_msg}")

    def copy(self) -> Dict[str, Dict[str, Any]]:
        """Get a copy of the entire cache.

        Returns:
            Deep copy of the cache dictionary
        """
        with self._lock:
            # Return deep copy to prevent external modifications
            return deepcopy(self._cache)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            logger.info("Cache cleared")

    def remove(self, container_name: str) -> bool:
        """Remove a specific entry from cache.

        Args:
            container_name: Name of the container

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            if container_name in self._cache:
                del self._cache[container_name]
                logger.debug(f"Removed cache for {container_name}")
                return True
            return False

    def _is_cache_valid(self, cached_entry: Dict[str, Any]) -> bool:
        """Check if a cache entry is still valid.

        Args:
            cached_entry: Cache entry to validate

        Returns:
            True if cache is valid, False if expired
        """
        if 'timestamp' not in cached_entry:
            return False

        cache_age = (datetime.now(timezone.utc) - cached_entry['timestamp']).total_seconds()
        max_age = int(os.environ.get('DDC_DOCKER_MAX_CACHE_AGE', str(self.cache_ttl_seconds)))

        return cache_age <= max_age

    def get_container_status(self, container_name: str) -> Optional[Tuple]:
        """Get cached status for a container.

        Args:
            container_name: Name of the container

        Returns:
            Tuple of (display_name, is_running, cpu_str, ram_str, uptime, details_allowed)
            or None if not cached
        """
        cached_entry = self.get(container_name)
        if cached_entry and cached_entry.get('data'):
            return cached_entry['data']
        return None

    def is_container_running(self, container_name: str) -> Optional[bool]:
        """Check if a container is running based on cache.

        Args:
            container_name: Name of the container

        Returns:
            True if running, False if not running, None if unknown
        """
        status = self.get_container_status(container_name)
        if status and isinstance(status, tuple) and len(status) >= 2:
            return status[1]  # is_running is at index 1
        return None

    def get_container_resources(self, container_name: str) -> Optional[Dict[str, str]]:
        """Get CPU and RAM usage for a container.

        Args:
            container_name: Name of the container

        Returns:
            Dict with 'cpu' and 'ram' keys, or None if not available
        """
        status = self.get_container_status(container_name)
        if status and isinstance(status, tuple) and len(status) >= 4:
            return {
                'cpu': status[2],  # cpu_str at index 2
                'ram': status[3]   # ram_str at index 3
            }
        return None

    def get_all_running_containers(self, server_configs: List[Dict[str, Any]]) -> List[str]:
        """Get list of all running containers.

        Args:
            server_configs: List of server configurations

        Returns:
            List of docker_names for running containers
        """
        running_containers = []

        for server in server_configs:
            if not isinstance(server, dict):
                continue

            docker_name = server.get('docker_name')
            display_name = server.get('name', docker_name)

            if not docker_name:
                continue

            # Check both by display_name and docker_name for compatibility
            is_running = self.is_container_running(display_name)
            if is_running is None and display_name != docker_name:
                # Try with docker_name if display_name didn't work
                is_running = self.is_container_running(docker_name)

            if is_running:
                running_containers.append(docker_name)

        return running_containers

    def count_running_containers(self, server_configs: List[Dict[str, Any]]) -> int:
        """Count how many containers are currently running.

        Args:
            server_configs: List of server configurations

        Returns:
            Number of running containers
        """
        return len(self.get_all_running_containers(server_configs))

    def has_any_running_containers(self, server_configs: List[Dict[str, Any]]) -> bool:
        """Check if any containers are running.

        Args:
            server_configs: List of server configurations

        Returns:
            True if at least one container is running
        """
        return self.count_running_containers(server_configs) > 0

    def validate_cache_data(self, data: Any) -> bool:
        """Validate that cache data has the expected format.

        Args:
            data: Data from cache to validate

        Returns:
            True if data is valid, False otherwise
        """
        if not isinstance(data, tuple):
            return False

        if len(data) < 6:
            return False

        # Basic type checking for expected fields
        # (display_name, is_running, cpu_str, ram_str, uptime, details_allowed)
        if not isinstance(data[0], str):  # display_name
            return False
        if not isinstance(data[1], bool):  # is_running
            return False
        # cpu_str and ram_str can be None or str
        # uptime can be None or str
        # details_allowed is bool

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        with self._lock:
            total_entries = len(self._cache)
            valid_entries = sum(1 for entry in self._cache.values()
                              if self._is_cache_valid(entry))
            error_entries = sum(1 for entry in self._cache.values()
                              if 'error' in entry)

            return {
                'total_entries': total_entries,
                'valid_entries': valid_entries,
                'expired_entries': total_entries - valid_entries,
                'error_entries': error_entries,
                'cache_ttl_seconds': self.cache_ttl_seconds
            }

# Singleton instance management
_status_cache_service_instance = None

def get_status_cache_service() -> StatusCacheService:
    """Get singleton instance of StatusCacheService.

    Returns:
        StatusCacheService instance
    """
    global _status_cache_service_instance

    if _status_cache_service_instance is None:
        _status_cache_service_instance = StatusCacheService()
        logger.info("Created new StatusCacheService singleton instance")

    return _status_cache_service_instance

def reset_status_cache_service():
    """Reset the singleton instance (mainly for testing)."""
    global _status_cache_service_instance
    if _status_cache_service_instance:
        _status_cache_service_instance.clear()
    _status_cache_service_instance = None
    logger.info("StatusCacheService singleton reset")