#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Donation Status Service                        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Donation Status Service - Handles comprehensive donation status queries with mech integration
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DonationStatusRequest:
    """Represents a donation status request."""
    pass


@dataclass
class DonationStatusResult:
    """Represents the result of donation status operation."""
    success: bool
    status_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DonationStatusService:
    """Service for handling comprehensive donation status queries."""

    def __init__(self):
        self.logger = logger

    def get_donation_status(self, request: DonationStatusRequest) -> DonationStatusResult:
        """
        Get current donation status with speed information using MechService.

        Args:
            request: DonationStatusRequest (currently no specific data needed)

        Returns:
            DonationStatusResult with comprehensive status data
        """
        try:
            # PERFORMANCE OPTIMIZATION: Use MechStatusCacheService instead of direct MechService
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest

            cache_service = get_mech_status_cache_service()
            cache_request = MechStatusCacheRequest(include_decimals=True)
            mech_cache_result = cache_service.get_cached_status(cache_request)

            if not mech_cache_result.success:
                return DonationStatusResult(
                    success=False,
                    error="Failed to get mech state from cache"
                )

            self.logger.info(f"WEB UI: Using cached mech status (age: {mech_cache_result.cache_age_seconds:.1f}s)")

            # Step 3: Get speed information using cached data
            speed_info = self._calculate_speed_information(
                power=mech_cache_result.power,
                total_donated=mech_cache_result.total_donated,
                evolution_level=mech_cache_result.level,
                power_max=getattr(getattr(mech_cache_result, 'bars', None), 'Power_max_for_level', None)
            )

            # Step 4: Get evolution information using cached data
            evolution_info = self._get_evolution_information(mech_cache_result.level)

            # Step 5: Build comprehensive status object using cached data
            status_data = self._build_status_data_from_cache(mech_cache_result, speed_info, evolution_info)

            return DonationStatusResult(
                success=True,
                status_data=status_data
            )

        except (RuntimeError) as e:
            self.logger.error(f"Error getting donation status: {e}", exc_info=True)
            return DonationStatusResult(
                success=False,
                error=f"Error getting donation status: {str(e)}"
            )


    def _calculate_speed_information(self, power: float, total_donated: float,
                                     evolution_level: Optional[int] = None,
                                     power_max: Optional[float] = None) -> Dict[str, Any]:
        """Calculate speed level and related information.

        Args:
            power: Current power amount (for speed calculation within level)
            total_donated: Total donations received (legacy level guess if evolution_level is missing)
            evolution_level: Actual mech level (preferred over a level guessed from total_donated)
            power_max: Power bar maximum of that level (speed scale)
        """
        try:
            from services.mech.speed_levels import SPEED_DESCRIPTIONS, get_speed_emoji, _get_evolution_context, _calculate_speed_level_from_power_ratio, get_speed_level_for_state

            # Calculate speed level using evolution-based calculation
            try:
                if evolution_level is not None:
                    # Real level + power bar: a level guessed from total_donated is wrong with dynamic costs
                    level = get_speed_level_for_state(evolution_level, power, power_max)
                else:
                    # Legacy: total_donated for evolution level, power for speed calculation
                    guessed_level, max_power_for_level = _get_evolution_context(total_donated)
                    level = _calculate_speed_level_from_power_ratio(guessed_level, power, max_power_for_level)
            except (ImportError, ValueError, ZeroDivisionError):
                # Fallback if evolution system unavailable
                level = min(int(power), 100) if power > 0 else 0

            # Get description directly from SPEED_DESCRIPTIONS using calculated level
            # This ensures consistency between level and description
            if level in SPEED_DESCRIPTIONS:
                description, color = SPEED_DESCRIPTIONS[level]
            else:
                description, color = SPEED_DESCRIPTIONS.get(0, ("OFFLINE", "#888888"))

            emoji = get_speed_emoji(level)

            return {
                'level': level,
                'description': description,
                'emoji': emoji,
                'color': color,
                'formatted_status': f"{emoji} {description}"
            }

        except (RuntimeError) as e:
            self.logger.error(f"Error calculating speed information: {e}", exc_info=True)
            # Return fallback speed info
            return {
                'level': 0,
                'description': 'Offline',
                'emoji': '⚫',
                'color': '#666666',
                'formatted_status': '⚫ Offline'
            }

    def _get_evolution_information(self, mech_level: int) -> Dict[str, Any]:
        """Get evolution-specific information like decay rate directly from mech_evolutions."""
        try:
            # SERVICE FIRST: Use unified evolution system directly
            from services.mech.mech_evolutions import get_evolution_level_info
            evolution_info = get_evolution_level_info(mech_level)

            return {
                'decay_per_day': evolution_info.decay_per_day if evolution_info else 1.0
            }

        except (RuntimeError, ImportError, AttributeError) as e:
            self.logger.error(f"Error getting evolution information: {e}", exc_info=True)
            # Return fallback evolution info
            return {
                'decay_per_day': 1.0
            }


    @staticmethod
    def _next_level_name(level: int) -> str:
        """Name of the evolution after `level`, or '' when there is none (level 11 is the last).

        Read from the same configured source Discord uses, so both surfaces agree.
        """
        try:
            if level >= 11:
                return ''
            from services.mech.mech_service_adapter import get_level_name
            return get_level_name(level + 1) or ''
        except (ImportError, AttributeError, RuntimeError, ValueError):
            return ''

    def _build_status_data_from_cache(self, cache_result, speed_info: Dict[str, Any], evolution_info: Dict[str, Any]) -> Dict[str, Any]:
        """Build the comprehensive status data object from cached data - PERFORMANCE OPTIMIZED."""
        try:
            # Build status object using cached data - NO additional service calls needed!
            status_data = {
                'total_amount': cache_result.total_donated,
                'current_Power': cache_result.power,
                'current_Power_raw': cache_result.power,  # Cache already includes decimals
                'mech_level': cache_result.level,
                'mech_level_name': cache_result.name,
                # The name of the NEXT evolution, so the Web UI does not have to keep its own
                # copy of the level names. It used to hold a hardcoded list ("STANDARD MECH",
                # ...) that had drifted away from the configured ones ("The Corewalker
                # Standard", ...), so the panel and Discord showed different names for the same
                # level. Empty on level 11, which has no successor.
                'next_level_name': self._next_level_name(cache_result.level),
                'next_level_threshold': cache_result.threshold,
                'glvl': cache_result.glvl,
                'glvl_max': cache_result.glvl_max,
                'decay_per_day': evolution_info['decay_per_day'],  # Level-specific decay rate
                'bars': {
                    'mech_progress_current': cache_result.bars.mech_progress_current,
                    'mech_progress_max': cache_result.bars.mech_progress_max,
                    'Power_current': cache_result.bars.Power_current,
                    'Power_max_for_level': cache_result.bars.Power_max_for_level,
                },
                'speed': speed_info
            }

            return status_data

        except (RuntimeError) as e:
            self.logger.error(f"Error building status data from cache: {e}", exc_info=True)
            # Return minimal fallback status
            return {
                'total_amount': 0,
                'current_Power': 0,
                'current_Power_raw': 0,
                'mech_level': 1,
                'mech_level_name': 'Unknown',
                'next_level_threshold': 0,
                'glvl': 0,
                'glvl_max': 0,
                'decay_per_day': 1.0,
                'bars': {
                    'mech_progress_current': 0,
                    'mech_progress_max': 0,
                    'Power_current': 0,
                    'Power_max_for_level': 0,
                },
                'speed': speed_info
            }


# Singleton instance
_donation_status_service = None


def get_donation_status_service() -> DonationStatusService:
    """Get the singleton DonationStatusService instance."""
    global _donation_status_service
    if _donation_status_service is None:
        _donation_status_service = DonationStatusService()
    return _donation_status_service
