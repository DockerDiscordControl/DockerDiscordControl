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
            speed_info = self._calculate_speed_information(mech_cache_result.power)

            # Step 4: Get evolution information using cached data
            evolution_info = self._get_evolution_information(mech_cache_result.level)

            # Step 5: Build comprehensive status object using cached data
            status_data = self._build_status_data_from_cache(mech_cache_result, speed_info, evolution_info)

            return DonationStatusResult(
                success=True,
                status_data=status_data
            )

        except Exception as e:
            self.logger.error(f"Error getting donation status: {e}", exc_info=True)
            return DonationStatusResult(
                success=False,
                error=f"Error getting donation status: {str(e)}"
            )


    def _calculate_speed_information(self, total_amount: float) -> Dict[str, Any]:
        """Calculate speed level and related information."""
        try:
            from services.mech.speed_levels import get_speed_info, get_speed_emoji

            # Calculate speed information
            description, color = get_speed_info(total_amount)
            level = min(int(total_amount / 10), 101) if total_amount > 0 else 0
            emoji = get_speed_emoji(level)

            return {
                'level': level,
                'description': description,
                'emoji': emoji,
                'color': color,
                'formatted_status': f"{emoji} {description}"
            }

        except Exception as e:
            self.logger.error(f"Error calculating speed information: {e}")
            # Return fallback speed info
            return {
                'level': 0,
                'description': 'Offline',
                'emoji': '⚫',
                'color': '#666666',
                'formatted_status': '⚫ Offline'
            }

    def _get_evolution_information(self, mech_level: int) -> Dict[str, Any]:
        """Get evolution-specific information like decay rate using MechDecayService."""
        try:
            from services.mech.mech_decay_service import get_mech_decay_service, DecayInfoRequest

            decay_service = get_mech_decay_service()
            request = DecayInfoRequest(mech_level=mech_level)
            result = decay_service.get_decay_info_for_level(request)

            if result.success and result.decay_info:
                return {
                    'decay_per_day': result.decay_info['decay_per_day']
                }
            else:
                self.logger.warning(f"MechDecayService failed for level {mech_level}: {result.error}")
                # Fallback to direct config access (SERVICE FIRST: unified evolution system)
                from services.mech.mech_evolutions import get_evolution_level_info
                evolution_info = get_evolution_level_info(mech_level)
                return {
                    'decay_per_day': evolution_info.decay_per_day if evolution_info else 1.0
                }

        except Exception as e:
            self.logger.error(f"Error getting evolution information: {e}")
            # Return fallback evolution info
            return {
                'decay_per_day': 1.0
            }


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

        except Exception as e:
            self.logger.error(f"Error building status data from cache: {e}")
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