#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker Status Services

Service-First architecture for Docker container status management.
Extracted from StatusHandlersMixin for better modularity and testability.

Services:
- PerformanceProfileService: Adaptive timeout & performance learning
- StatusCacheService: Status caching with TTL management
- DockerStatusFetchService: Docker data fetching with retry logic
- StatusEmbedService: Discord embed generation for status display
"""

__all__ = [
    'PerformanceProfile',
    'StatusFetchRequest',
    'StatusFetchResult',
    'CachedStatus',
    'get_performance_service',
    'get_fetch_service',
]

from .models import (
    PerformanceProfile,
    StatusFetchRequest,
    StatusFetchResult,
    CachedStatus,
)
from .performance_service import get_performance_service
from .fetch_service import get_fetch_service
