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
