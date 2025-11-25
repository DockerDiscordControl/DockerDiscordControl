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
    force_evolution_level: Optional[int] = None  # Override evolution level (for Mech History)
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
            if request.force_evolution_level is not None:
                # Override evolution level (for Mech History)
                evolution_level = max(1, min(11, request.force_evolution_level))
                current_power = request.force_power if request.force_power is not None else 100.0  # Default high power
                self.logger.debug(f"Live mech animation request with force_evolution_level: {evolution_level}, power: {current_power}")
            elif request.force_power is not None:
                # Use force_power for testing, but get actual level from mech state
                current_power = request.force_power

                # BUGFIX: Use actual mech level instead of calculating from power
                # get_evolution_level() calculates based on thresholds, but actual level
                # can be different (e.g., Level 3 with Power 2.97 after decay)
                from services.mech.mech_data_store import get_mech_data_store, LevelDataRequest
                data_store = get_mech_data_store()
                level_request = LevelDataRequest()
                level_result = data_store.get_level_info(level_request)

                if level_result.success:
                    evolution_level = level_result.current_level
                else:
                    # Fallback to calculation from power if MechDataStore fails
                    evolution_level = max(1, min(11, get_evolution_level(current_power)))

                self.logger.debug(f"Live mech animation request with force_power: {current_power}, actual_level: {evolution_level}")
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
            # SPECIAL CASE: Level 11 is maximum level - always use Speed Level 100 (maximum animation speed)
            if evolution_level >= 11:
                speed_level = 100  # Level 11 always has maximum speed (divine speed)
                self.logger.debug(f"Level 11 using maximum speed level: {speed_level}")
            else:
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

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error in get_live_animation: {e}", exc_info=True)
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

            # SERVICE FIRST: Use unified animation system for test animations too
            test_request = MechAnimationRequest(
                force_power=request.total_donations,  # Use donation amount as power for test
                resolution="small"  # Test animations use small resolution
            )

            # Use the same unified system as live animations
            result = self.get_live_animation(test_request)

            if result.success:
                return result
            else:
                return self._create_fallback_animation(request.total_donations)

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error in get_test_animation: {e}", exc_info=True)
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
            from services.mech.speed_levels import SPEED_DESCRIPTIONS, get_speed_emoji, _get_evolution_context, _calculate_speed_level_from_power_ratio

            # Calculate speed level using evolution-based system
            try:
                evolution_level, max_power_for_level = _get_evolution_context(request.total_donations)
                level = _calculate_speed_level_from_power_ratio(evolution_level, request.total_donations, max_power_for_level)
            except (ImportError, ValueError, ZeroDivisionError):
                level = min(int(request.total_donations), 100) if request.total_donations > 0 else 0

            # Get description directly from SPEED_DESCRIPTIONS
            if level in SPEED_DESCRIPTIONS:
                description, color = SPEED_DESCRIPTIONS[level]
            else:
                description, color = SPEED_DESCRIPTIONS.get(0, ("OFFLINE", "#888888"))

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

        except (ImportError, AttributeError, TypeError, ValueError, ZeroDivisionError) as e:
            # Service/calculation errors (missing services, invalid types, missing attributes, division errors)
            self.logger.error(f"Service error in get_speed_config: {e}", exc_info=True)
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

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error in manage_difficulty: {e}", exc_info=True)
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
        except (AttributeError, TypeError, IndexError, OSError) as e:
            # Path manipulation errors (missing attributes, invalid types, path errors)
            self.logger.warning(f"Could not set Python path: {e}")

    def _get_total_donations(self, force_power: Optional[float] = None) -> float:
        """Get total donations using MechDataStore (centralized data service)."""
        if force_power is not None:
            return force_power

        try:
            from services.mech.mech_data_store import get_mech_data_store, PowerDataRequest

            data_store = get_mech_data_store()
            power_request = PowerDataRequest(include_decimals=False)
            power_result = data_store.get_power_info(power_request)

            if not power_result.success:
                self.logger.error("Failed to get power info from MechDataStore")
                return 20.0  # Fallback

            total_donations = power_result.total_donated
            self.logger.debug(f"Got total donations from MechDataStore: {total_donations}")
            return total_donations

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error getting donation status from MechDataStore: {e}", exc_info=True)
            return 20.0  # Fallback default

    def _create_donation_animation(self, total_donations: float, donor_name: str, amount: str) -> Optional[bytes]:
        """Create donation animation using internal methods (no circular deps)."""
        try:
            from services.mech.mech_data_store import get_mech_data_store, PowerDataRequest

            data_store = get_mech_data_store()

            # MECHDATASTORE: Get power info with decimals for proper animation
            power_request = PowerDataRequest(include_decimals=True)
            power_result = data_store.get_power_info(power_request)

            if not power_result.success:
                self.logger.error("Failed to get power info from MechDataStore for animation")
                return None

            # Get current Power and total donated for proper animation
            current_power = power_result.current_power
            total_donated = power_result.total_donated or total_donations

            # DIRECT CALL: Use self.get_live_animation instead of circular PngToWebpService
            request = MechAnimationRequest(
                force_power=total_donated,  # Use donation amount as power context
                resolution="small"
            )
            
            result = self.get_live_animation(request)

            if result.success:
                return result.animation_bytes
            return None

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error creating donation animation: {e}", exc_info=True)
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

        except (ImportError, OSError, AttributeError, TypeError, ValueError) as e:
            # Image generation errors (PIL import, I/O errors, attribute/type/value errors)
            self.logger.error(f"Image generation error in fallback animation: {e}", exc_info=True)
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

        except (ImportError, OSError, AttributeError, TypeError, ValueError) as e:
            # Image generation errors (PIL import, I/O errors, attribute/type/value errors)
            self.logger.error(f"Image generation error in error animation: {e}", exc_info=True)
            return MechAnimationResult(
                success=False,
                error=f"Animation system offline: {error_msg}",
                status_code=500
            )

    def _get_difficulty(self) -> MechConfigResult:
        """Get current mech evolution difficulty multiplier using MechDataStore and evolution config."""
        try:
            from services.mech.mech_data_store import get_mech_data_store, EvolutionDataRequest
            # FIX: Use mech_evolutions directly instead of missing simple_evolution_service
            from services.mech.mech_evolutions import get_evolution_config_service, get_evolution_level, get_evolution_level_info

            data_store = get_mech_data_store()
            
            # MECHDATASTORE: Get evolution information
            evolution_request = EvolutionDataRequest()
            evolution_result = data_store.get_evolution_info(evolution_request)

            if not evolution_result.success:
                self.logger.error("Failed to get evolution info from MechDataStore")
                return MechConfigResult(success=False, error=evolution_result.error, status_code=500)

            multiplier = evolution_result.difficulty_multiplier
            is_auto = evolution_result.evolution_mode == 'dynamic'

            # Get total donations (handling compatibility)
            # evolution_result.amount_needed is actually "amount needed for next level", not total donated
            # We should use our internal helper or trust data store
            total_donated = self._get_total_donations()

            # --- Reconstruct Simple Evolution State ---
            current_level = get_evolution_level(total_donated)
            
            # Calculate next level cost
            next_level_info = get_evolution_level_info(current_level + 1)
            if next_level_info:
                # Simple estimation: Base Cost * Multiplier
                # Note: This ignores community size scaling for this specific view, 
                # but provides a consistent baseline for difficulty settings.
                next_level_cost = int(next_level_info.base_cost * multiplier)
            else:
                next_level_cost = 0 # Max level reached

            # Build achieved levels map
            achieved_levels = {}
            for lvl in range(1, 12): # Levels 1-11
                info = get_evolution_level_info(lvl)
                if info:
                    achieved_levels[str(lvl)] = {
                        'level': lvl,
                        'name': info.name,
                        'cost': int(info.base_cost * multiplier),
                        'achieved': lvl <= current_level
                    }

            # Difficulty Presets (Hardcoded standard values)
            presets = {
                "EASY": 0.5,
                "NORMAL": 1.0,
                "HARD": 1.5,
                "EXTREME": 2.0
            }

            return MechConfigResult(
                success=True,
                data={
                    'multiplier': multiplier,
                    'is_auto': is_auto,
                    'status': 'auto' if is_auto else 'manual',
                    'manual_override': not is_auto,
                    'simple_evolution': {
                        'current_level': current_level,
                        'next_level_cost': next_level_cost,
                        'total_donated': total_donated,
                        'achieved_levels': achieved_levels
                    },
                    'presets': presets
                }
            )

        except (ImportError, AttributeError, ValueError, TypeError) as e:
            self.logger.error(f"Error getting difficulty settings: {e}", exc_info=True)
            return MechConfigResult(success=False, error=f"Configuration error: {e}", status_code=500)

    def _set_difficulty(self, multiplier: Optional[float]) -> MechConfigResult:
        """Set mech evolution difficulty multiplier using MechService evolution mode."""
        try:
            if multiplier is None:
                return MechConfigResult(
                    success=False,
                    error="Multiplier is required",
                    status_code=400
                )

            if not (0.5 <= multiplier <= 2.4):  # Match Web UI slider range
                return MechConfigResult(
                    success=False,
                    error="Multiplier must be between 0.5 and 2.4",
                    status_code=400
                )

            from services.mech.mech_service import get_mech_service
            # FIX: Use mech_evolutions directly instead of missing simple_evolution_service
            from services.mech.mech_evolutions import get_evolution_level, get_evolution_level_info

            mech_service = get_mech_service()

            # Set evolution mode to static with custom difficulty
            mech_service.set_evolution_mode(use_dynamic=False, difficulty_multiplier=multiplier)

            # Get updated simple evolution state (Reconstructed manually)
            total_donated = self._get_total_donations()
            current_level = get_evolution_level(total_donated)
            
            next_level_info = get_evolution_level_info(current_level + 1)
            if next_level_info:
                next_level_cost = int(next_level_info.base_cost * multiplier)
            else:
                next_level_cost = 0

            # Log the action
            self._log_user_action(
                action="SET_MECH_DIFFICULTY",
                target=f"Static mode: {multiplier}x",
                source="Web UI"
            )

            return MechConfigResult(
                success=True,
                data={
                    'multiplier': multiplier,
                    'is_auto': False,
                    'status': 'manual',
                    'message': f'Evolution set to static mode with {multiplier}x difficulty',
                    'simple_evolution': {
                        'current_level': current_level,
                        'next_level_cost': next_level_cost,
                        'total_donated': total_donated,
                        'cost_change': f'Next level now costs ${next_level_cost}'
                    }
                }
            )

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error setting difficulty: {e}", exc_info=True)
            return MechConfigResult(
                success=False,
                error=str(e),
                status_code=500
            )

    def _reset_difficulty(self) -> MechConfigResult:
        """Reset mech evolution difficulty to dynamic mode."""
        try:
            from services.mech.mech_service import get_mech_service

            mech_service = get_mech_service()

            # Set evolution mode to dynamic (community-based)
            mech_service.set_evolution_mode(use_dynamic=True, difficulty_multiplier=1.0)

            # Log the action
            self._log_user_action(
                action="RESET_MECH_DIFFICULTY",
                target="Dynamic mode (community-based)",
                source="Web UI"
            )

            return MechConfigResult(
                success=True,
                data={
                    'multiplier': 1.0,  # Reset to normal in UI
                    'is_auto': True,
                    'status': 'auto',
                    'message': 'Difficulty reset to automatic mode'
                }
            )

        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:
            # Service/data errors (missing services, invalid types, missing attributes/keys)
            self.logger.error(f"Service error resetting difficulty: {e}", exc_info=True)
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
        except (ImportError, AttributeError, OSError, TypeError) as e:
            # Logging errors (missing module, missing attributes, I/O errors, type errors)
            self.logger.warning(f"Could not log user action: {e}")


# Singleton instance
_mech_web_service = None


def get_mech_web_service() -> MechWebService:
    """Get the singleton MechWebService instance."""
    global _mech_web_service
    if _mech_web_service is None:
        _mech_web_service = MechWebService()
    return _mech_web_service
