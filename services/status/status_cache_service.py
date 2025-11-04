# =============================================================================
# SERVICE FIRST: Container Status Cache Service
# =============================================================================

import logging
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone

logger = logging.getLogger('ddc.status_cache_service')

class StatusCacheService:
    """Service First implementation for container status cache access.

    This service provides a clean interface to the status cache,
    hiding implementation details and providing type safety.
    """

    def __init__(self, cog_instance=None):
        """Initialize the StatusCacheService.

        Args:
            cog_instance: Reference to the DockerControlCog for cache access
        """
        self._cog = cog_instance
        logger.info("StatusCacheService initialized")

    def set_cog_instance(self, cog_instance):
        """Set the cog instance for cache access.

        Args:
            cog_instance: Reference to the DockerControlCog
        """
        self._cog = cog_instance
        logger.debug("Cog instance set for StatusCacheService")

    def get_container_status(self, container_name: str) -> Optional[Tuple]:
        """Get cached status for a container.

        Args:
            container_name: Name of the container

        Returns:
            Tuple of (display_name, is_running, cpu_str, ram_str, uptime, details_allowed)
            or None if not cached
        """
        if not self._cog or not hasattr(self._cog, 'status_cache'):
            logger.warning("Status cache not available")
            return None

        cached_entry = self._cog.status_cache.get(container_name)
        if not cached_entry or not cached_entry.get('data'):
            logger.debug(f"No cache entry for {container_name}")
            return None

        # Check cache age if timestamp is available
        if 'timestamp' in cached_entry:
            import os
            max_cache_age = int(os.environ.get('DDC_DOCKER_MAX_CACHE_AGE', '300'))
            cache_age = (datetime.now(timezone.utc) - cached_entry['timestamp']).total_seconds()
            if cache_age > max_cache_age:
                logger.debug(f"Cache for {container_name} expired ({cache_age:.1f}s > {max_cache_age}s)")
                return None

        return cached_entry.get('data')

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

# Singleton instance management
_status_cache_service_instance = None

def get_status_cache_service(cog_instance=None) -> StatusCacheService:
    """Get singleton instance of StatusCacheService.

    Args:
        cog_instance: Optional cog instance to use

    Returns:
        StatusCacheService instance
    """
    global _status_cache_service_instance

    if _status_cache_service_instance is None:
        _status_cache_service_instance = StatusCacheService(cog_instance)
    elif cog_instance is not None:
        # Update cog instance if provided
        _status_cache_service_instance.set_cog_instance(cog_instance)

    return _status_cache_service_instance