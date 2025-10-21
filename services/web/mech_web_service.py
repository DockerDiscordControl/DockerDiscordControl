#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Web Service                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Web Service - Handles all web-related mech operations including animations,
speed configuration, difficulty management, and testing endpoints.
"""

import sys
import os
import logging
from io import BytesIO
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MechAnimationRequest:
    """Represents a mech animation request."""
    force_power: Optional[float] = None  # Override power level for testing
    resolution: str = "small"  # Animation resolution: "small" | "big"


@dataclass
class MechTestAnimationRequest:
    """Represents a test mech animation request."""
    donor_name: str = "Test User"
    amount: str = "10$"
    total_donations: float = 0


@dataclass
class MechSpeedConfigRequest:
    """Represents a mech speed configuration request."""
    total_donations: float


@dataclass
class MechDifficultyRequest:
    """Represents a mech difficulty request."""
    operation: str  # 'get', 'set', or 'reset'
    multiplier: Optional[float] = None


@dataclass
class MechAnimationResult:
    """Represents the result of mech animation generation."""
    success: bool
    animation_bytes: Optional[bytes] = None
    content_type: str = 'image/webp'
    cache_headers: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    status_code: int = 200


@dataclass
class MechConfigResult:
    """Represents the result of mech configuration operations."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200


class MechWebService:
    """Service for comprehensive web-related mech operations."""

    def __init__(self):
        self.logger = logger
        self._ensure_python_path()

    def get_live_animation(self, request: MechAnimationRequest) -> MechAnimationResult:
        """
        Generate live mech animation based on current power level using cached system.

        Args:
            request: MechAnimationRequest with optional power override and resolution

        Returns:
            MechAnimationResult with animation bytes or error information
        """
        try:
            # PERFORMANCE OPTIMIZATION: Use cached data instead of live generation
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
            from services.mech.animation_cache_service import get_animation_cache_service
            from services.mech.mech_evolutions import get_evolution_level
            from services.mech.speed_levels import get_combined_mech_status

            # Step 1: Get current mech status from cache (ultra-fast)
            if request.force_power is not None:
                # Use force_power for testing
                current_power = request.force_power
                evolution_level = max(1, min(11, get_evolution_level(current_power)))
                self.logger.debug(f"Live mech animation request with force_power: {current_power}")
            else:
                # Use cached mech status (30-second background refresh)
                cache_service = get_mech_status_cache_service()
                cache_request = MechStatusCacheRequest(include_decimals=True)
                mech_cache_result = cache_service.get_cached_status(cache_request)

                if not mech_cache_result.success:
                    self.logger.error("Failed to get mech status from cache")
                    return self._create_error_response("Failed to get mech status from cache")

                current_power = mech_cache_result.power
                evolution_level = mech_cache_result.level
                self.logger.debug(f"Live mech animation request from cache: level={evolution_level}, power={current_power}")

            # Step 2: Get power-based animation with proper speed calculation (same logic as big mechs)
            animation_service = get_animation_cache_service()

            # Calculate speed level from current power (same logic as MechStatusDetailsService)
            speed_status = get_combined_mech_status(current_power)
            speed_level = speed_status['speed']['level']

            # Get animation with power-based selection (walk vs rest) - unified service interface
            if request.resolution == "big":
                animation_bytes = animation_service.get_animation_with_speed_and_power_big(evolution_level, speed_level, current_power)
                self.logger.debug(f"Using big animation for resolution: {request.resolution}")
            else:
                animation_bytes = animation_service.get_animation_with_speed_and_power(evolution_level, speed_level, current_power)
                self.logger.debug(f"Using small animation for resolution: {request.resolution}")

            if animation_bytes:
                # TEMPORARY: Disable caching to force browser to load fresh animations after cache regeneration
                cache_headers = {'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache', 'Expires': '0'}

                return MechAnimationResult(
                    success=True,
                    animation_bytes=animation_bytes,
                    content_type='image/webp',
                    cache_headers=cache_headers
                )
            else:
                # Animation generation failed - this should rarely happen with cache system
                self.logger.warning(f"Cache animation failed for level {evolution_level}, using fallback")
                return self._create_fallback_animation(current_power)

        except Exception as e:
            self.logger.error(f"Error in get_live_animation: {e}", exc_info=True)
            return self._create_error_animation(current_power if 'current_power' in locals() else 0.0, str(e))

    def get_test_animation(self, request: MechTestAnimationRequest) -> MechAnimationResult:
        """
        Generate test mech animation with specified parameters using cached system.

        Args:
            request: MechTestAnimationRequest with test parameters

        Returns:
            MechAnimationResult with animation bytes or error information
        """
        try:
            self.logger.info(f"Generating test mech animation for {request.donor_name}, donations: {request.total_donations}")

            # PERFORMANCE OPTIMIZATION: Use cached animations for test too
            from services.mech.animation_cache_service import get_animation_cache_service
            from services.mech.mech_evolutions import get_evolution_level

            # Calculate evolution level from test parameters
            evolution_level = max(1, min(11, get_evolution_level(request.total_donations)))

            # Get pre-cached animation (instant response)
            animation_service = get_animation_cache_service()
            animation_bytes = animation_service.get_current_mech_animation(evolution_level)

            if animation_bytes:
                return MechAnimationResult(
                    success=True,
                    animation_bytes=animation_bytes,
                    content_type='image/webp'
                )
            else:
                return self._create_fallback_animation(request.total_donations)

        except Exception as e:
            self.logger.error(f"Error in get_test_animation: {e}", exc_info=True)
            return self._create_error_animation(request.total_donations, str(e))

    def get_speed_config(self, request: MechSpeedConfigRequest) -> MechConfigResult:
        """
        Get speed configuration using 101-level system.

        Args:
            request: MechSpeedConfigRequest with total donations

        Returns:
            MechConfigResult with speed configuration data
        """
        try:
            from services.mech.speed_levels import get_speed_info, get_speed_emoji

            # Use new speed system
            description, color = get_speed_info(request.total_donations)
            level = min(int(request.total_donations / 10), 101) if request.total_donations > 0 else 0
            emoji = get_speed_emoji(level)

            config = {
                'speed_level': level,
                'description': description,
                'emoji': emoji,
                'color': color,
                'total_donations': request.total_donations
            }

            # Log the action
            self._log_user_action(
                action="GET_MECH_SPEED_CONFIG",
                target=f"Level {level} - {description}",
                source="Web UI"
            )

            return MechConfigResult(
                success=True,
                data=config
            )

        except Exception as e:
            self.logger.error(f"Error in get_speed_config: {e}", exc_info=True)
            return MechConfigResult(
                success=False,
                error=str(e),
                status_code=500
            )

    def manage_difficulty(self, request: MechDifficultyRequest) -> MechConfigResult:
        """
        Manage mech evolution difficulty settings.

        Args:
            request: MechDifficultyRequest with operation and optional multiplier

        Returns:
            MechConfigResult with difficulty operation result
        """
        try:
            if request.operation == 'get':
                return self._get_difficulty()
            elif request.operation == 'set':
                return self._set_difficulty(request.multiplier)
            elif request.operation == 'reset':
                return self._reset_difficulty()
            else:
                return MechConfigResult(
                    success=False,
                    error=f"Invalid operation: {request.operation}",
                    status_code=400
                )

        except Exception as e:
            self.logger.error(f"Error in manage_difficulty: {e}", exc_info=True)
            return MechConfigResult(
                success=False,
                error=str(e),
                status_code=500
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _ensure_python_path(self):
        """Ensure project root is in Python path for service imports."""
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
        except Exception as e:
            self.logger.warning(f"Could not set Python path: {e}")

    def _get_total_donations(self, force_power: Optional[float] = None) -> float:
        """Get total donations with multiple fallbacks."""
        if force_power is not None:
            return force_power

        try:
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            mech_service = get_mech_service()
            mech_state_request = GetMechStateRequest(include_decimals=False)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)
            if not mech_state_result.success:
                self.logger.error("Failed to get mech state")
                return 20.0  # Fallback
            total_donations = mech_state_result.total_donated
            self.logger.debug(f"Got total donations from mech service: {total_donations}")
            return total_donations
        except Exception as e:
            self.logger.error(f"Error getting donation status: {e}")
            return 20.0  # Fallback default

    def _create_donation_animation(self, total_donations: float, donor_name: str, amount: str) -> Optional[bytes]:
        """Create donation animation using unified service."""
        try:
            from services.mech.png_to_webp_service import get_png_to_webp_service
            from services.mech.mech_service import get_mech_service, GetMechStateRequest

            animation_service = get_png_to_webp_service()
            mech_service = get_mech_service()

            # SERVICE FIRST: Get mech state with decimals for proper animation
            mech_state_request = GetMechStateRequest(include_decimals=True)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)
            if not mech_state_result.success:
                self.logger.error("Failed to get mech state for animation")
                return None

            # Get current Power and total donated for proper animation
            current_power = mech_state_result.power
            total_donated = mech_state_result.total_donated

            # Create animation bytes synchronously using unified service
            animation_bytes = animation_service.create_donation_animation_sync(
                donor_name=donor_name,
                amount=amount,
                total_donations=total_donated or total_donations
            )

            return animation_bytes

        except Exception as e:
            self.logger.error(f"Error creating donation animation: {e}")
            return None

    def _create_fallback_animation(self, total_donations: float) -> MechAnimationResult:
        """Create fallback static image when animation fails."""
        try:
            from PIL import Image, ImageDraw

            img = Image.new('RGBA', (341, 512), (47, 49, 54, 255))
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), f"Power: ${total_donations:.2f}", fill=(255, 255, 255, 255))
            draw.text((10, 30), "Animation Loading...", fill=(255, 255, 0, 255))

            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            return MechAnimationResult(
                success=True,
                animation_bytes=buffer.getvalue(),
                content_type='image/png'
            )

        except Exception as e:
            self.logger.error(f"Error creating fallback animation: {e}")
            return MechAnimationResult(
                success=False,
                error="Could not create fallback animation",
                status_code=500
            )

    def _create_error_animation(self, total_donations: float, error_msg: str) -> MechAnimationResult:
        """Create error image when all animation attempts fail."""
        try:
            from PIL import Image, ImageDraw

            img = Image.new('RGBA', (341, 512), (47, 49, 54, 255))
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), f"Power: ${total_donations:.2f}", fill=(255, 255, 255, 255))
            draw.text((10, 30), "Mech Offline", fill=(255, 0, 0, 255))

            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            return MechAnimationResult(
                success=False,
                animation_bytes=buffer.getvalue(),
                content_type='image/png',
                error=error_msg,
                status_code=500
            )

        except Exception as e:
            self.logger.error(f"Error creating error animation: {e}")
            return MechAnimationResult(
                success=False,
                error=f"Animation system offline: {error_msg}",
                status_code=500
            )

    def _get_difficulty(self) -> MechConfigResult:
        """Get current mech evolution difficulty multiplier."""
        try:
            from services.mech.evolution_config_manager import get_evolution_config_manager

            config_manager = get_evolution_config_manager()
            multiplier = config_manager.get_difficulty_multiplier()
            is_auto = config_manager.is_auto_difficulty()

            return MechConfigResult(
                success=True,
                data={
                    'multiplier': multiplier,
                    'is_auto': is_auto,
                    'status': 'auto' if is_auto else 'manual'
                }
            )

        except Exception as e:
            self.logger.error(f"Error getting difficulty: {e}")
            return MechConfigResult(
                success=False,
                error=str(e),
                status_code=500
            )

    def _set_difficulty(self, multiplier: Optional[float]) -> MechConfigResult:
        """Set mech evolution difficulty multiplier."""
        try:
            if multiplier is None:
                return MechConfigResult(
                    success=False,
                    error="Multiplier is required",
                    status_code=400
                )

            if not (0.1 <= multiplier <= 10.0):
                return MechConfigResult(
                    success=False,
                    error="Multiplier must be between 0.1 and 10.0",
                    status_code=400
                )

            from services.mech.evolution_config_manager import get_evolution_config_manager

            config_manager = get_evolution_config_manager()
            config_manager.set_difficulty_multiplier(multiplier)

            # Log the action
            self._log_user_action(
                action="SET_MECH_DIFFICULTY",
                target=f"Multiplier: {multiplier}",
                source="Web UI"
            )

            return MechConfigResult(
                success=True,
                data={
                    'multiplier': multiplier,
                    'is_auto': False,
                    'status': 'manual',
                    'message': f'Difficulty multiplier set to {multiplier}x'
                }
            )

        except Exception as e:
            self.logger.error(f"Error setting difficulty: {e}")
            return MechConfigResult(
                success=False,
                error=str(e),
                status_code=500
            )

    def _reset_difficulty(self) -> MechConfigResult:
        """Reset mech evolution difficulty to automatic mode."""
        try:
            from services.mech.evolution_config_manager import get_evolution_config_manager

            config_manager = get_evolution_config_manager()
            config_manager.reset_to_auto_difficulty()
            current_multiplier = config_manager.get_difficulty_multiplier()

            # Log the action
            self._log_user_action(
                action="RESET_MECH_DIFFICULTY",
                target="Auto mode",
                source="Web UI"
            )

            return MechConfigResult(
                success=True,
                data={
                    'multiplier': current_multiplier,
                    'is_auto': True,
                    'status': 'auto',
                    'message': 'Difficulty reset to automatic mode'
                }
            )

        except Exception as e:
            self.logger.error(f"Error resetting difficulty: {e}")
            return MechConfigResult(
                success=False,
                error=str(e),
                status_code=500
            )

    def _log_user_action(self, action: str, target: str, source: str):
        """Log user action for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(action=action, target=target, source=source)
        except Exception as e:
            self.logger.warning(f"Could not log user action: {e}")


# Singleton instance
_mech_web_service = None


def get_mech_web_service() -> MechWebService:
    """Get the singleton MechWebService instance."""
    global _mech_web_service
    if _mech_web_service is None:
        _mech_web_service = MechWebService()
    return _mech_web_service