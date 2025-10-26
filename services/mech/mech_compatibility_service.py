#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Compatibility Service                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Compatibility Service - Provides backward compatibility for old mech interfaces
Bridges between SERVICE FIRST patterns and legacy code expectations
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityStateRequest:
    """Request for backward-compatible mech state."""
    include_decimals: bool = False


@dataclass
class CompatibilityStateResult:
    """Backward-compatible mech state result."""
    success: bool

    # Direct legacy properties for compatibility
    level: int = 0
    Power: float = 0.0
    total_donated: float = 0.0
    level_name: str = ""

    # Additional properties that might be needed
    name: str = ""
    threshold: int = 0
    speed: float = 50.0

    # Speed/glvl properties for expanded view
    glvl: int = 0
    glvl_max: int = 100

    # Bars for progress display
    bars: Optional[Any] = None

    error_message: Optional[str] = None


class MechCompatibilityService:
    """
    SERVICE FIRST compatibility service for legacy mech interfaces.

    Provides backward-compatible state objects without breaking SERVICE FIRST principles.
    """

    def __init__(self):
        self.logger = logger.getChild(self.__class__.__name__)

    def get_compatible_state(self, request: CompatibilityStateRequest) -> CompatibilityStateResult:
        """
        Get mech state in legacy-compatible format using SERVICE FIRST.

        Args:
            request: CompatibilityStateRequest with configuration

        Returns:
            CompatibilityStateResult with legacy-compatible properties
        """
        try:
            from services.mech.mech_service import get_mech_service, GetMechStateRequest

            # Use SERVICE FIRST to get state
            mech_service = get_mech_service()
            mech_state_request = GetMechStateRequest(include_decimals=request.include_decimals)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)

            if not mech_state_result.success:
                return CompatibilityStateResult(
                    success=False,
                    error_message="Failed to get mech state from service"
                )

            # Map to legacy format
            return CompatibilityStateResult(
                success=True,
                level=mech_state_result.level,
                Power=mech_state_result.power,
                total_donated=mech_state_result.total_donated,
                level_name=mech_state_result.name,
                name=mech_state_result.name,
                threshold=mech_state_result.threshold,
                speed=mech_state_result.speed,
                glvl=mech_state_result.glvl,
                glvl_max=mech_state_result.glvl_max,
                bars=mech_state_result.bars
            )

        except Exception as e:
            self.logger.error(f"Error getting compatible state: {e}")
            return CompatibilityStateResult(
                success=False,
                error_message=str(e)
            )

    def get_store_data(self) -> Dict[str, Any]:
        """
        Get store data using SERVICE FIRST (for gradual migration).

        Returns:
            Dict with store data or empty dict on failure
        """
        try:
            from services.mech.mech_service import get_mech_service, GetStoreDataRequest
            mech_service = get_mech_service()

            # SERVICE FIRST: Use proper Request/Result pattern
            request = GetStoreDataRequest()
            result = mech_service.get_store_data_service(request)

            return result.data if result.success else {}
        except Exception as e:
            self.logger.error(f"Error loading store data: {e}")
            return {}

    def save_store_data(self, data: Dict[str, Any]) -> bool:
        """
        Save store data using SERVICE FIRST (for gradual migration).

        Args:
            data: Data to save

        Returns:
            True if successful, False otherwise
        """
        try:
            from services.mech.mech_service import get_mech_service, SaveStoreDataRequest
            mech_service = get_mech_service()

            # SERVICE FIRST: Use proper Request/Result pattern
            request = SaveStoreDataRequest(data=data)
            result = mech_service.save_store_data_service(request)

            return result.success
        except Exception as e:
            self.logger.error(f"Error saving store data: {e}")
            return False


# Singleton instance
_mech_compatibility_service = None


def get_mech_compatibility_service() -> MechCompatibilityService:
    """Get or create the mech compatibility service instance."""
    global _mech_compatibility_service
    if _mech_compatibility_service is None:
        _mech_compatibility_service = MechCompatibilityService()
    return _mech_compatibility_service