#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Status Cache Service                      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Status Cache Service - Provides high-performance cached access to mech status
with background refresh loop for instant Discord and Web UI responses.
"""

import logging
import asyncio
import threading
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class MechStatusCacheRequest:
    """Request for cached mech status."""
    include_decimals: bool = False
    force_refresh: bool = False


@dataclass
class MechStatusCacheResult:
    """Cached mech status result."""
    success: bool

    # Core mech data
    level: int = 0
    power: float = 0.0
    total_donated: float = 0.0
    name: str = ""
    threshold: int = 0
    speed: float = 50.0

    # Extended data for expanded views
    glvl: int = 0
    glvl_max: int = 100
    bars: Optional[Any] = None

    # Speed status info
    speed_description: str = ""
    speed_color: str = "#cccccc"

    # Cache metadata
    cached_at: Optional[datetime] = None
    cache_age_seconds: float = 0.0

    error_message: Optional[str] = None


class MechStatusCacheService:
    """
    High-performance mech status cache with background refresh loop.

    Features:
    - 30-second background refresh loop
    - 45-second TTL for cache entries
    - Instant response for Discord/Web UI
    - Thread-safe cache access
    - Fallback to direct service calls
    """

    def __init__(self):
        self.logger = logger.getChild(self.__class__.__name__)

        # Cache storage
        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.RLock()
        self._cache_ttl = 45.0  # 45 seconds TTL

        # Background loop control
        self._loop_task: Optional[asyncio.Task] = None
        self._loop_running = False
        self._refresh_interval = 30.0  # 30 seconds refresh

        self.logger.info("Mech Status Cache Service initialized")

    def get_cached_status(self, request: MechStatusCacheRequest) -> MechStatusCacheResult:
        """
        Get mech status from cache with fallback to direct service call.

        Args:
            request: MechStatusCacheRequest with configuration

        Returns:
            MechStatusCacheResult with cached or fresh data
        """
        try:
            # Check cache first (unless force refresh)
            if not request.force_refresh:
                cached_result = self._get_from_cache(request.include_decimals)
                if cached_result:
                    self.logger.debug(f"Cache hit: age {cached_result.cache_age_seconds:.1f}s")
                    return cached_result

            # Cache miss or force refresh - get fresh data
            self.logger.debug("Cache miss or force refresh - fetching fresh data")
            fresh_result = self._fetch_fresh_status(request.include_decimals)

            # Store in cache
            self._store_in_cache(fresh_result, request.include_decimals)

            return fresh_result

        except Exception as e:
            self.logger.error(f"Error getting cached mech status: {e}")
            return MechStatusCacheResult(
                success=False,
                error_message=str(e)
            )

    def _get_from_cache(self, include_decimals: bool) -> Optional[MechStatusCacheResult]:
        """Get status from cache if valid."""
        cache_key = f"mech_status_{include_decimals}"

        with self._cache_lock:
            cache_entry = self._cache.get(cache_key)
            if not cache_entry:
                return None

            # Check TTL
            cache_age = time.time() - cache_entry['timestamp']
            if cache_age > self._cache_ttl:
                self.logger.debug(f"Cache expired: {cache_age:.1f}s > {self._cache_ttl}s")
                del self._cache[cache_key]
                return None

            # Return cached result with age metadata
            result = cache_entry['result']
            result.cache_age_seconds = cache_age
            return result

    def _store_in_cache(self, result: MechStatusCacheResult, include_decimals: bool):
        """Store result in cache with timestamp."""
        cache_key = f"mech_status_{include_decimals}"

        with self._cache_lock:
            result.cached_at = datetime.now(timezone.utc)
            result.cache_age_seconds = 0.0

            self._cache[cache_key] = {
                'result': result,
                'timestamp': time.time()
            }

            self.logger.debug(f"Stored in cache: {cache_key}")

    def _fetch_fresh_status(self, include_decimals: bool) -> MechStatusCacheResult:
        """Fetch fresh mech status from services."""
        try:
            # Get mech state using SERVICE FIRST
            from services.mech.mech_compatibility_service import get_mech_compatibility_service, CompatibilityStateRequest

            compat_service = get_mech_compatibility_service()
            compat_request = CompatibilityStateRequest(include_decimals=include_decimals)
            compat_result = compat_service.get_compatible_state(compat_request)

            if not compat_result.success:
                return MechStatusCacheResult(
                    success=False,
                    error_message=compat_result.error_message or "Failed to get mech state"
                )

            # Get speed status info
            from services.mech.speed_levels import get_speed_info
            speed_description, speed_color = get_speed_info(compat_result.Power)

            # Build cached result
            return MechStatusCacheResult(
                success=True,
                level=compat_result.level,
                power=compat_result.Power,
                total_donated=compat_result.total_donated,
                name=compat_result.level_name,
                threshold=compat_result.threshold,
                speed=compat_result.speed,
                glvl=compat_result.glvl,
                glvl_max=compat_result.glvl_max,
                bars=compat_result.bars,
                speed_description=speed_description,
                speed_color=speed_color
            )

        except Exception as e:
            self.logger.error(f"Error fetching fresh mech status: {e}")
            return MechStatusCacheResult(
                success=False,
                error_message=str(e)
            )

    async def start_background_loop(self):
        """Start the background cache refresh loop."""
        if self._loop_running:
            self.logger.warning("Background loop already running")
            return

        self._loop_running = True
        self.logger.info(f"Starting mech status cache loop (interval: {self._refresh_interval}s, TTL: {self._cache_ttl}s)")

        try:
            while self._loop_running:
                await self._background_refresh()
                await asyncio.sleep(self._refresh_interval)

        except asyncio.CancelledError:
            self.logger.info("Background loop cancelled")
        except Exception as e:
            self.logger.error(f"Background loop error: {e}")
        finally:
            self._loop_running = False
            self.logger.info("Background loop stopped")

    async def _background_refresh(self):
        """Perform background cache refresh."""
        try:
            self.logger.debug("Background cache refresh starting...")

            # Refresh both decimal variants
            for include_decimals in [False, True]:
                request = MechStatusCacheRequest(
                    include_decimals=include_decimals,
                    force_refresh=True
                )

                # Run in thread pool to avoid blocking
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.get_cached_status, request)

            self.logger.debug("Background cache refresh completed")

        except Exception as e:
            self.logger.error(f"Background refresh error: {e}")

    def stop_background_loop(self):
        """Stop the background cache refresh loop."""
        self._loop_running = False
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        self.logger.info("Background loop stop requested")

    def clear_cache(self):
        """Clear all cached data."""
        with self._cache_lock:
            cache_count = len(self._cache)
            self._cache.clear()
            self.logger.info(f"Cache cleared: {cache_count} entries removed")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            stats = {
                'entries': len(self._cache),
                'ttl_seconds': self._cache_ttl,
                'refresh_interval_seconds': self._refresh_interval,
                'loop_running': self._loop_running,
                'entries_detail': {}
            }

            # Add entry details
            for key, entry in self._cache.items():
                age = time.time() - entry['timestamp']
                stats['entries_detail'][key] = {
                    'age_seconds': round(age, 1),
                    'expires_in_seconds': round(self._cache_ttl - age, 1),
                    'is_expired': age > self._cache_ttl
                }

            return stats


# Singleton instance
_mech_status_cache_service = None


def get_mech_status_cache_service() -> MechStatusCacheService:
    """Get or create the mech status cache service instance."""
    global _mech_status_cache_service
    if _mech_status_cache_service is None:
        _mech_status_cache_service = MechStatusCacheService()
    return _mech_status_cache_service