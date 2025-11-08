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
        Get mech state in legacy-compatible format using MechDataStore.

        Args:
            request: CompatibilityStateRequest with configuration

        Returns:
            CompatibilityStateResult with legacy-compatible properties
        """
        try:
            # MECHDATASTORE: Use centralized data service for compatibility layer
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest

            data_store = get_mech_data_store()
            data_request = MechDataRequest(include_decimals=request.include_decimals)
            data_result = data_store.get_comprehensive_data(data_request)

            if not data_result.success:
                return CompatibilityStateResult(
                    success=False,
                    error_message="Failed to get mech data from MechDataStore"
                )

            # Map to legacy format for backward compatibility
            return CompatibilityStateResult(
                success=True,
                level=data_result.current_level,
                Power=data_result.current_power,
                total_donated=data_result.total_donated,
                level_name=data_result.level_name,
                name=data_result.level_name,
                threshold=data_result.next_level_threshold or 0,
                speed=50.0,  # Default speed for compatibility
                glvl=data_result.current_level,  # Use level as glvl for compatibility
                glvl_max=100,  # Default max for compatibility
                bars=getattr(data_result, 'bars', None)
            )

        except Exception as e:
            self.logger.error(f"Error getting compatible state: {e}")
            return CompatibilityStateResult(
                success=False,
                error_message=str(e)
            )

    def get_store_data(self) -> Dict[str, Any]:
        """
        Get store data from progress service events for backward compatibility.

        Returns:
            Dict with 'donations' list converted from progress service events
        """
        try:
            import json
            from pathlib import Path

            # Read events from progress service event log
            event_log = Path("config/progress/events.jsonl")
            donations = []

            if event_log.exists():
                with open(event_log, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        if event.get('type') == 'DonationAdded':
                            payload = event.get('payload', {})
                            donations.append({
                                'username': payload.get('donor', 'Anonymous'),
                                'amount': payload.get('units', 0) / 100.0,  # Convert cents to dollars
                                'ts': event.get('ts', ''),
                                'level_upgrade': False,  # We don't track this in events
                                'level_reached': None,
                                'threshold_used': None,
                                'is_dynamic': True,
                                'donation_id': payload.get('donation_id', '')
                            })

            return {'donations': donations}
        except Exception as e:
            self.logger.error(f"Error loading store data from progress service: {e}", exc_info=True)
            return {'donations': []}

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