#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Status Service Models

Dataclasses for request/response objects and shared data structures.
These models provide type safety and clear contracts between services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Any


# =========================================================================
# Performance Profile Models
# =========================================================================

@dataclass
class PerformanceProfile:
    """
    Performance profile for a container tracking response times and success rates.

    Used by PerformanceProfileService to implement adaptive timeout logic.
    """
    container_name: str
    response_times: List[float] = field(default_factory=list)
    avg_response_time: float = 30000.0  # milliseconds, default 30s
    max_response_time: float = 30000.0  # milliseconds
    min_response_time: float = 1000.0   # milliseconds
    success_rate: float = 1.0           # 0.0 to 1.0
    total_attempts: int = 0
    successful_attempts: int = 0
    is_slow: bool = False
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/caching"""
        return {
            'container_name': self.container_name,
            'response_times': self.response_times,
            'avg_response_time': self.avg_response_time,
            'max_response_time': self.max_response_time,
            'min_response_time': self.min_response_time,
            'success_rate': self.success_rate,
            'total_attempts': self.total_attempts,
            'successful_attempts': self.successful_attempts,
            'is_slow': self.is_slow,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PerformanceProfile:
        """Create from dictionary (from storage/cache)"""
        if 'last_updated' in data and data['last_updated']:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)


@dataclass
class PerformanceConfig:
    """Configuration for performance learning system"""
    min_timeout: int = 5000           # 5 seconds minimum timeout
    max_timeout: int = 45000          # 45 seconds maximum timeout
    default_timeout: int = 30000      # 30 seconds default for new containers
    slow_threshold: int = 8000        # 8+ seconds = slow container
    history_window: int = 20          # Keep last 20 measurements
    retry_attempts: int = 3           # Maximum retry attempts
    timeout_multiplier: float = 2.0   # Timeout = avg_time * multiplier


# =========================================================================
# Docker Fetch Models
# =========================================================================

@dataclass
class StatusFetchRequest:
    """
    Request for fetching Docker container status.

    Sent to DockerStatusFetchService.
    """
    container_name: str
    timeout_seconds: float = 5.0
    use_cache: bool = True
    max_retries: int = 3
    include_stats: bool = True  # Whether to fetch CPU/memory stats


@dataclass
class StatusFetchResult:
    """
    Result of Docker container status fetch.

    Returned by DockerStatusFetchService.
    """
    success: bool
    container_name: str
    info: Optional[Dict[str, Any]] = None      # Docker inspect info
    stats: Optional[Dict[str, Any]] = None     # Docker stats (CPU/memory)
    error: Optional[str] = None
    error_type: Optional[str] = None  # 'timeout', 'not_found', 'connection', etc.
    fetch_duration_ms: float = 0.0
    from_cache: bool = False
    cache_age_seconds: float = 0.0
    retry_count: int = 0  # How many retries were needed

    @property
    def is_running(self) -> bool:
        """Check if container is running based on info"""
        if not self.info:
            return False
        return self.info.get('State', {}).get('Running', False)

    @property
    def status(self) -> str:
        """Get container status string"""
        if not self.info:
            return 'unknown'
        return self.info.get('State', {}).get('Status', 'unknown')


# =========================================================================
# Cache Models
# =========================================================================

@dataclass
class CachedStatus:
    """
    Cached container status with TTL.

    Stored by StatusCacheService.
    """
    container_name: str
    fetch_result: StatusFetchResult
    cached_at: datetime
    ttl_seconds: int = 30

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired"""
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - self.cached_at).total_seconds()
        return age > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Get age of cache entry in seconds"""
        from datetime import datetime, timezone
        return (datetime.now(timezone.utc) - self.cached_at).total_seconds()


# =========================================================================
# Container Status Result Models
# =========================================================================

@dataclass
class ContainerStatusResult:
    """
    Result of a container status query with complete information.

    Replaces the inconsistent tuple returns from get_status() and bulk_fetch_container_status().
    Provides a clean, typed interface with both success and error states.

    Usage:
        # Success case
        result = ContainerStatusResult.success_result(
            docker_name="nginx", display_name="Web Server",
            is_running=True, cpu="5.2%", ram="128MB", uptime="2d 5h",
            details_allowed=True
        )

        # Error case
        result = ContainerStatusResult.error_result(
            docker_name="nginx", error=RuntimeError("Connection failed"),
            error_type="connectivity"
        )

        # Offline case
        result = ContainerStatusResult.offline_result(
            docker_name="nginx", display_name="Web Server"
        )
    """
    docker_name: str
    success: bool

    # Success fields (populated when success=True)
    display_name: Optional[str] = None
    is_running: bool = False
    cpu: str = "N/A"
    ram: str = "N/A"
    uptime: str = "N/A"
    details_allowed: bool = True

    # Error fields (populated when success=False)
    error: Optional[Exception] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None  # 'connectivity', 'not_found', 'timeout', etc.

    @property
    def is_online(self) -> bool:
        """Convenience property: container successfully queried AND running"""
        return self.success and self.is_running

    @property
    def is_offline(self) -> bool:
        """Convenience property: container successfully queried but NOT running"""
        return self.success and not self.is_running

    def as_tuple(self):
        """
        Legacy tuple format for backwards compatibility during migration.

        Returns: (display_name, is_running, cpu, ram, uptime, details_allowed)
        """
        from typing import Tuple
        return (
            self.display_name or self.docker_name,
            self.is_running,
            self.cpu,
            self.ram,
            self.uptime,
            self.details_allowed
        )

    @classmethod
    def success_result(cls, docker_name: str, display_name: str, is_running: bool,
                      cpu: str, ram: str, uptime: str, details_allowed: bool) -> 'ContainerStatusResult':
        """Factory method for successful status fetch"""
        return cls(
            docker_name=docker_name,
            success=True,
            display_name=display_name,
            is_running=is_running,
            cpu=cpu,
            ram=ram,
            uptime=uptime,
            details_allowed=details_allowed
        )

    @classmethod
    def error_result(cls, docker_name: str, error: Exception,
                     error_type: str = 'unknown') -> 'ContainerStatusResult':
        """Factory method for failed status fetch"""
        return cls(
            docker_name=docker_name,
            success=False,
            display_name=docker_name,  # Fallback to docker_name
            error=error,
            error_message=str(error),
            error_type=error_type
        )

    @classmethod
    def offline_result(cls, docker_name: str, display_name: str,
                       details_allowed: bool = True) -> 'ContainerStatusResult':
        """Factory method for offline container (successfully queried but not running)"""
        return cls(
            docker_name=docker_name,
            success=True,
            display_name=display_name,
            is_running=False,
            details_allowed=details_allowed
        )


# =========================================================================
# Embed Building Models
# =========================================================================

@dataclass
class StatusEmbedRequest:
    """
    Request for building a status embed.

    Sent to StatusEmbedService.
    """
    display_name: str
    is_running: bool
    cpu_text: str = 'N/A'
    ram_text: str = 'N/A'
    uptime_text: str = 'N/A'
    language: str = 'de'
    allow_toggle: bool = True
    collapsed: bool = False
    error_message: Optional[str] = None


@dataclass
class StatusEmbedResult:
    """
    Result containing Discord embed data.

    Returned by StatusEmbedService.
    """
    success: bool
    embed_dict: Optional[Dict[str, Any]] = None  # Discord embed as dict
    view_components: Optional[List[Any]] = None  # Discord view/buttons
    error: Optional[str] = None


# =========================================================================
# Bulk Fetch Models
# =========================================================================

@dataclass
class BulkFetchRequest:
    """Request for bulk fetching multiple containers"""
    container_names: List[str]
    timeout_seconds: float = 5.0
    use_cache: bool = True
    parallel_limit: int = 5  # Max containers to fetch in parallel


@dataclass
class BulkFetchResult:
    """Result of bulk fetch operation"""
    results: Dict[str, StatusFetchResult]  # container_name -> result
    total_duration_ms: float
    success_count: int
    error_count: int


# =========================================================================
# Container Classification
# =========================================================================

@dataclass
class ContainerClassification:
    """Classification of containers by performance characteristics"""
    fast_containers: List[str] = field(default_factory=list)
    slow_containers: List[str] = field(default_factory=list)
    unknown_containers: List[str] = field(default_factory=list)  # No history yet

    @property
    def total_containers(self) -> int:
        return len(self.fast_containers) + len(self.slow_containers) + len(self.unknown_containers)
