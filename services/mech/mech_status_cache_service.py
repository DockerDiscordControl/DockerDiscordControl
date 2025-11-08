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

        # SERVICE FIRST: Event-based cache invalidation setup
        self._setup_event_listeners()

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
        """Fetch fresh mech status directly from progress service."""
        try:
            # Get mech data directly from MechDataStore
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest

            data_store = get_mech_data_store()
            data_request = MechDataRequest(include_decimals=include_decimals)
            data_result = data_store.get_comprehensive_data(data_request)

            if not data_result.success:
                return MechStatusCacheResult(
                    success=False,
                    error_message="Failed to get mech data from MechDataStore"
                )

            # Get speed status info
            from services.mech.speed_levels import get_speed_info
            speed_description, speed_color = get_speed_info(data_result.current_power)

            # Build cached result
            return MechStatusCacheResult(
                success=True,
                level=data_result.current_level,
                power=data_result.current_power,
                total_donated=data_result.total_donated,
                name=data_result.level_name,
                threshold=data_result.next_level_threshold or 0,
                speed=50.0,  # Default speed
                glvl=data_result.current_level,
                glvl_max=100,
                bars=getattr(data_result, 'bars', None),
                speed_description=speed_description,
                speed_color=speed_color,
                cached_at=datetime.now(timezone.utc)
            )

        except Exception as e:
            self.logger.error(f"Error fetching fresh mech status: {e}", exc_info=True)
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

    def _setup_event_listeners(self):
        """Set up Service First event listeners for cache invalidation."""
        try:
            from services.infrastructure.event_manager import get_event_manager
            event_manager = get_event_manager()

            # Register listener for donation completion events
            event_manager.register_listener('donation_completed', self._handle_donation_event)

            # Register listener for mech state changes
            event_manager.register_listener('mech_state_changed', self._handle_state_change_event)

            self.logger.info("Event listeners registered for mech status cache invalidation")

        except Exception as e:
            self.logger.error(f"Failed to setup event listeners: {e}")

    def _handle_donation_event(self, event_data):
        """Handle donation completion events for immediate cache invalidation."""
        try:
            # Extract relevant data from event
            event_info = event_data.data
            reason = f"Donation completed: ${event_info.get('amount', 'unknown')}"

            # CRITICAL: Clear cache immediately for donation events
            self.clear_cache()

            self.logger.info(f"Mech status cache invalidated due to donation event: {reason}")

            # ELEGANT SOLUTION: Emit Discord update event for automatic status message refresh
            # This keeps service boundaries clean while ensuring Discord updates
            try:
                from services.infrastructure.event_manager import get_event_manager
                event_manager = get_event_manager()

                event_manager.emit_event(
                    event_type='discord_update_needed',
                    source_service='mech_status_cache',
                    data={
                        'reason': 'donation_event',
                        'trigger_source': event_data.source_service,
                        'donation_data': event_info
                    }
                )
                self.logger.info("Discord update event emitted for automatic status message refresh")
            except Exception as discord_event_error:
                self.logger.error(f"Failed to emit Discord update event: {discord_event_error}")

        except Exception as e:
            self.logger.error(f"Error handling donation event: {e}")

    def _handle_state_change_event(self, event_data):
        """Handle mech state change events for cache invalidation."""
        try:
            # Extract state change information
            event_info = event_data.data
            old_power = event_info.get('old_power', 0)
            new_power = event_info.get('new_power', 0)

            # Clear cache for any significant state change
            self.clear_cache()
            reason = f"State change: {old_power:.2f} → {new_power:.2f}"
            self.logger.info(f"Mech status cache invalidated due to state change: {reason}")

        except Exception as e:
            self.logger.error(f"Error handling state change event: {e}")

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