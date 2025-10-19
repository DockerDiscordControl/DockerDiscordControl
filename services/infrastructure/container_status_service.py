# -*- coding: utf-8 -*-
"""
Container Status Service - Clean SERVICE FIRST architecture for Docker container status queries

Replaces the old docker_utils.get_docker_info/get_docker_stats with remote Docker support
and proper caching for high-performance Discord status updates.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from utils.logging_utils import get_module_logger

logger = get_module_logger('container_status_service')

@dataclass(frozen=True)
class ContainerStatusRequest:
    """Request for container status information."""
    container_name: str
    include_stats: bool = True  # Include CPU/RAM stats
    include_details: bool = True  # Include detailed container info
    timeout_seconds: float = 10.0

@dataclass(frozen=True)
class ContainerBulkStatusRequest:
    """Request for bulk container status information."""
    container_names: List[str]
    include_stats: bool = True
    include_details: bool = True
    timeout_seconds: float = 15.0
    max_concurrent: int = 3

@dataclass(frozen=True)
class ContainerStatusResult:
    """Result of container status query."""
    success: bool
    container_name: str

    # Basic status
    is_running: bool = False
    status: str = "unknown"

    # Stats (if requested)
    cpu_percent: float = 0.0
    memory_usage_mb: float = 0.0
    memory_limit_mb: float = 0.0

    # Detailed info (if requested)
    uptime_seconds: int = 0
    image: str = ""
    ports: Dict[str, Any] = None

    # Performance metadata
    query_duration_ms: float = 0.0
    cached: bool = False
    cache_age_seconds: float = 0.0

    # Error info
    error_message: Optional[str] = None
    error_type: Optional[str] = None  # 'timeout', 'not_found', 'docker_error', etc.

@dataclass(frozen=True)
class ContainerBulkStatusResult:
    """Result of bulk container status query."""
    success: bool
    results: Dict[str, ContainerStatusResult]
    total_duration_ms: float = 0.0
    successful_containers: int = 0
    failed_containers: int = 0
    error_message: Optional[str] = None

class ContainerStatusService:
    """
    High-performance container status service with remote Docker support.

    Features:
    - Remote Docker connectivity (works from Mac to Unraid)
    - Intelligent caching with TTL
    - Bulk operations with concurrency control
    - Performance monitoring and adaptive timeouts
    - Compatible interface with old docker_utils functions
    """

    def __init__(self):
        self.logger = logger.getChild(self.__class__.__name__)

        # Cache storage
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 30.0  # 30 seconds TTL

        # Performance tracking
        self._performance_history: Dict[str, List[float]] = {}

        self.logger.info("Container Status Service initialized (SERVICE FIRST)")

    async def get_container_status(self, request: ContainerStatusRequest) -> ContainerStatusResult:
        """
        Get status for a single container.

        Args:
            request: ContainerStatusRequest with container name and options

        Returns:
            ContainerStatusResult with status information
        """
        start_time = time.time()

        try:
            # Check cache first
            cached_result = self._get_from_cache(request.container_name)
            if cached_result and not self._is_cache_expired(cached_result):
                cache_age = time.time() - cached_result['timestamp']
                self.logger.debug(f"Cache hit for {request.container_name} (age: {cache_age:.1f}s)")

                result = cached_result['result']
                # Update metadata for cache hit
                result = ContainerStatusResult(
                    **{**result.__dict__, 'cached': True, 'cache_age_seconds': cache_age}
                )
                return result

            # Cache miss - fetch fresh data
            self.logger.debug(f"Cache miss for {request.container_name} - fetching fresh data")
            result = await self._fetch_container_status(request)

            # Store in cache if successful
            if result.success:
                self._store_in_cache(request.container_name, result)

            # Record performance
            duration_ms = (time.time() - start_time) * 1000
            self._record_performance(request.container_name, duration_ms)

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(f"Error getting container status for {request.container_name}: {e}")

            return ContainerStatusResult(
                success=False,
                container_name=request.container_name,
                error_message=str(e),
                error_type="service_error",
                query_duration_ms=duration_ms
            )

    async def get_bulk_container_status(self, request: ContainerBulkStatusRequest) -> ContainerBulkStatusResult:
        """
        Get status for multiple containers efficiently.

        Args:
            request: ContainerBulkStatusRequest with container names and options

        Returns:
            ContainerBulkStatusResult with all container statuses
        """
        start_time = time.time()

        try:
            # Create individual requests
            individual_requests = [
                ContainerStatusRequest(
                    container_name=name,
                    include_stats=request.include_stats,
                    include_details=request.include_details,
                    timeout_seconds=request.timeout_seconds
                )
                for name in request.container_names
            ]

            # Process with concurrency control
            semaphore = asyncio.Semaphore(request.max_concurrent)

            async def fetch_with_semaphore(req):
                async with semaphore:
                    return await self.get_container_status(req)

            # Execute all requests concurrently
            tasks = [fetch_with_semaphore(req) for req in individual_requests]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            result_dict = {}
            successful = 0
            failed = 0

            for i, result in enumerate(results):
                container_name = request.container_names[i]

                if isinstance(result, Exception):
                    # Handle exception
                    result_dict[container_name] = ContainerStatusResult(
                        success=False,
                        container_name=container_name,
                        error_message=str(result),
                        error_type="exception"
                    )
                    failed += 1
                else:
                    result_dict[container_name] = result
                    if result.success:
                        successful += 1
                    else:
                        failed += 1

            total_duration_ms = (time.time() - start_time) * 1000

            return ContainerBulkStatusResult(
                success=True,
                results=result_dict,
                total_duration_ms=total_duration_ms,
                successful_containers=successful,
                failed_containers=failed
            )

        except Exception as e:
            total_duration_ms = (time.time() - start_time) * 1000
            self.logger.error(f"Error in bulk container status query: {e}")

            return ContainerBulkStatusResult(
                success=False,
                results={},
                total_duration_ms=total_duration_ms,
                error_message=str(e)
            )

    async def _fetch_container_status(self, request: ContainerStatusRequest) -> ContainerStatusResult:
        """Fetch fresh container status from Docker daemon."""
        start_time = time.time()

        try:
            # Use the Docker client pool for remote Docker support
            from services.docker_service.docker_utils import get_docker_client_async

            async with get_docker_client_async() as client:
                # Get basic container info
                try:
                    container = client.containers.get(request.container_name)
                    is_running = container.status == 'running'
                    status = container.status

                    # Basic container details
                    image = container.image.tags[0] if container.image.tags else str(container.image.id)[:12]

                    # Calculate uptime
                    if is_running and container.attrs.get('State', {}).get('StartedAt'):
                        started_at_str = container.attrs['State']['StartedAt']
                        # Parse Docker's timestamp format
                        started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                        uptime_seconds = int((datetime.now(timezone.utc) - started_at).total_seconds())
                    else:
                        uptime_seconds = 0

                    # Get ports info
                    ports = container.attrs.get('NetworkSettings', {}).get('Ports', {}) if request.include_details else {}

                except Exception as e:
                    # Container not found or other error
                    duration_ms = (time.time() - start_time) * 1000
                    return ContainerStatusResult(
                        success=False,
                        container_name=request.container_name,
                        error_message=f"Container not found or inaccessible: {e}",
                        error_type="container_not_found",
                        query_duration_ms=duration_ms
                    )

                # Get stats if requested and container is running
                cpu_percent = 0.0
                memory_usage_mb = 0.0
                memory_limit_mb = 0.0

                if request.include_stats and is_running:
                    try:
                        # Get container stats
                        stats = container.stats(stream=False, decode=True)

                        # Calculate CPU percentage
                        cpu_stats = stats.get('cpu_stats', {})
                        precpu_stats = stats.get('precpu_stats', {})

                        if cpu_stats and precpu_stats:
                            cpu_delta = cpu_stats.get('cpu_usage', {}).get('total_usage', 0) - \
                                       precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                            system_delta = cpu_stats.get('system_cpu_usage', 0) - \
                                          precpu_stats.get('system_cpu_usage', 0)

                            if system_delta > 0:
                                cpu_count = cpu_stats.get('online_cpus', len(cpu_stats.get('cpu_usage', {}).get('percpu_usage', [])))
                                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

                        # Get memory stats
                        memory_stats = stats.get('memory_stats', {})
                        memory_usage = memory_stats.get('usage', 0)
                        memory_limit = memory_stats.get('limit', 0)

                        memory_usage_mb = memory_usage / (1024 * 1024)
                        memory_limit_mb = memory_limit / (1024 * 1024)

                    except Exception as e:
                        self.logger.debug(f"Could not get stats for {request.container_name}: {e}")
                        # Continue without stats - not critical

                duration_ms = (time.time() - start_time) * 1000

                return ContainerStatusResult(
                    success=True,
                    container_name=request.container_name,
                    is_running=is_running,
                    status=status,
                    cpu_percent=cpu_percent,
                    memory_usage_mb=memory_usage_mb,
                    memory_limit_mb=memory_limit_mb,
                    uptime_seconds=uptime_seconds,
                    image=image,
                    ports=ports,
                    query_duration_ms=duration_ms,
                    cached=False,
                    cache_age_seconds=0.0
                )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(f"Docker error for {request.container_name}: {e}")

            return ContainerStatusResult(
                success=False,
                container_name=request.container_name,
                error_message=str(e),
                error_type="docker_error",
                query_duration_ms=duration_ms
            )

    def _get_from_cache(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get container status from cache."""
        return self._cache.get(container_name)

    def _is_cache_expired(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if cache entry is expired."""
        age = time.time() - cache_entry['timestamp']
        return age > self._cache_ttl

    def _store_in_cache(self, container_name: str, result: ContainerStatusResult):
        """Store result in cache."""
        self._cache[container_name] = {
            'result': result,
            'timestamp': time.time()
        }
        self.logger.debug(f"Cached status for {container_name}")

    def _record_performance(self, container_name: str, duration_ms: float):
        """Record performance metrics for adaptive optimization."""
        if container_name not in self._performance_history:
            self._performance_history[container_name] = []

        history = self._performance_history[container_name]
        history.append(duration_ms)

        # Keep only last 10 measurements
        if len(history) > 10:
            history.pop(0)

    def clear_cache(self):
        """Clear the entire cache."""
        cache_count = len(self._cache)
        self._cache.clear()
        self.logger.info(f"Cache cleared: {cache_count} entries removed")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        expired_count = sum(1 for entry in self._cache.values()
                          if now - entry['timestamp'] > self._cache_ttl)

        return {
            'total_entries': len(self._cache),
            'expired_entries': expired_count,
            'active_entries': len(self._cache) - expired_count,
            'cache_ttl_seconds': self._cache_ttl,
            'performance_tracked_containers': len(self._performance_history)
        }


# Singleton instance
_container_status_service = None

def get_container_status_service() -> ContainerStatusService:
    """Get or create the container status service instance."""
    global _container_status_service
    if _container_status_service is None:
        _container_status_service = ContainerStatusService()
    return _container_status_service


# COMPATIBILITY LAYER: Functions that match old docker_utils interface

async def get_docker_info_dict_service_first(docker_container_name: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """
    SERVICE FIRST replacement for old get_docker_info function (Dictionary format).

    Returns: Dictionary with container info or None on error
    """
    service = get_container_status_service()
    request = ContainerStatusRequest(
        container_name=docker_container_name,
        include_stats=True,
        include_details=True,
        timeout_seconds=timeout
    )

    result = await service.get_container_status(request)

    if not result.success:
        return None

    # Return Dictionary format expected by status_handlers.py
    return {
        'State': {
            'Running': result.is_running,
            'StartedAt': None  # Will calculate uptime differently
        },
        'Config': {
            'Image': result.image
        },
        'NetworkSettings': {
            'Ports': result.ports or {}
        },
        # Add our computed values
        '_computed': {
            'cpu_percent': result.cpu_percent,
            'memory_usage_mb': result.memory_usage_mb,
            'uptime_seconds': result.uptime_seconds
        }
    }

async def get_docker_info_service_first(docker_container_name: str, timeout: float = 10.0) -> Optional[Tuple]:
    """
    SERVICE FIRST replacement for old get_docker_info function.

    Returns: (display_name, is_running, cpu, ram, uptime, details_allowed) or None on error
    """
    service = get_container_status_service()
    request = ContainerStatusRequest(
        container_name=docker_container_name,
        include_stats=True,
        include_details=True,
        timeout_seconds=timeout
    )

    result = await service.get_container_status(request)

    if not result.success:
        return None

    # Match old interface format
    return (
        docker_container_name,  # display_name
        result.is_running,      # is_running
        result.cpu_percent,     # cpu
        result.memory_usage_mb, # ram (MB)
        result.uptime_seconds,  # uptime
        True                    # details_allowed (always True for now)
    )

async def get_docker_stats_service_first(docker_container_name: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """
    SERVICE FIRST replacement for old get_docker_stats function.

    Returns: Dict with stats or None on error
    """
    service = get_container_status_service()
    request = ContainerStatusRequest(
        container_name=docker_container_name,
        include_stats=True,
        include_details=False,
        timeout_seconds=timeout
    )

    result = await service.get_container_status(request)

    if not result.success:
        return None

    # Match old interface format
    return {
        'cpu_percent': result.cpu_percent,
        'memory_usage_mb': result.memory_usage_mb,
        'memory_limit_mb': result.memory_limit_mb,
        'is_running': result.is_running,
        'status': result.status
    }