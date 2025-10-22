#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Status Details Service                    #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Status Details Service - Provides formatted mech status details for Discord UI.
Follows service-first architecture pattern, combining existing mech services.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MechStatusDetailsRequest:
    """Request for formatted mech status details."""
    use_high_resolution: bool = False  # True for big mechs, False for small mechs


@dataclass
class MechStatusDetailsResult:
    """Result containing formatted mech status details for Discord."""
    success: bool
    error: Optional[str] = None

    # Formatted strings ready for Discord
    level_text: Optional[str] = None      # "The Rustborn Husk (Level 1)"
    speed_text: Optional[str] = None      # "Geschwindigkeit: Motionless"
    power_text: Optional[str] = None      # "⚡0.24"
    power_bar: Optional[str] = None       # "░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 1.2%"
    energy_consumption: Optional[str] = None  # "Energieverbrauch: 🔻 1.0/t"
    next_evolution: Optional[str] = None  # "⬆️ The Battle-Scarred Survivor"
    evolution_bar: Optional[str] = None   # "█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 5.0%"

    # Animation data
    animation_bytes: Optional[bytes] = None
    content_type: Optional[str] = None


class MechStatusDetailsService:
    """Service for providing formatted mech status details."""

    def __init__(self):
        self.cache = {}

    def get_mech_status_details(self, request: MechStatusDetailsRequest) -> MechStatusDetailsResult:
        """
        Get formatted mech status details combining all mech services.

        Args:
            request: The mech status details request

        Returns:
            MechStatusDetailsResult with formatted status information
        """
        try:
            # PERFORMANCE OPTIMIZATION: Use cached mech state instead of live calculations
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest

            cache_service = get_mech_status_cache_service()
            cache_request = MechStatusCacheRequest(include_decimals=True)
            cached_result = cache_service.get_cached_status(cache_request)

            if not cached_result.success:
                # Fallback to live calculation if cache fails
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                state = mech_service.get_state()
                power_decimal = mech_service.get_power_with_decimals()

                # Get speed description
                # SPECIAL CASE: Level 11 is maximum level - always show "Göttlich" (no more speed changes)
                if state.level >= 11:
                    speed_description = "Göttlich"  # Level 11 is final level with static divine speed
                else:
                    speed_description = self._get_speed_description(state.Power)

                # Format level text
                level_text = f"{state.level_name} (Level {state.level})"

                # Create power progress bar
                # SPECIAL CASE: Level 11 is maximum level - show infinity instead of speed bar
                if state.level >= 11:
                    # For maximum level, show "reached infinity" message with appreciation (divine perfection achieved)
                    power_bar = self._get_infinity_message()
                else:
                    # Normal level progression
                    power_bar = self._create_progress_bar(
                        state.bars.Power_current,
                        state.bars.Power_max_for_level
                    )
            else:
                # Use cached data - much faster!
                power_decimal = cached_result.power

                # Get speed description from cache (already calculated)
                # SPECIAL CASE: Level 11 is maximum level - always show "Göttlich" (no more speed changes)
                if cached_result.level >= 11:
                    speed_description = "Göttlich"  # Level 11 is final level with static divine speed
                else:
                    speed_description = cached_result.speed_description if cached_result.speed_description else self._get_speed_description(int(power_decimal))

                # Format level text (cache has 'name' not 'level_name')
                level_text = f"{cached_result.name} (Level {cached_result.level})"

                # Create power progress bar from cache
                if cached_result.bars and hasattr(cached_result.bars, 'Power_current'):
                    # SPECIAL CASE: Level 11 is maximum level - show infinity instead of speed bar
                    if cached_result.level >= 11:
                        # For maximum level, show "reached infinity" message with appreciation (divine perfection achieved)
                        power_bar = self._get_infinity_message()
                    else:
                        # Normal level progression
                        power_bar = self._create_progress_bar(
                            cached_result.bars.Power_current,
                            cached_result.bars.Power_max_for_level
                        )
                else:
                    # Fallback progress bar calculation
                    current_progress = int((power_decimal % 1.0) * 100)
                    power_bar = self._create_progress_bar(current_progress, 100)

            # Format speed text
            speed_text = f"Geschwindigkeit: {speed_description}"

            # Format power with decimals
            power_text = f"⚡{power_decimal:.2f}"

            # Format energy consumption (simplified) - Level 11 has no energy consumption
            current_level = cached_result.level if cached_result.success else state.level
            if current_level >= 11:
                energy_consumption = None  # Maximum level has no energy consumption
            else:
                energy_consumption = "Energieverbrauch: 🔻 1.0/t"

            # Format next evolution
            next_evolution = None
            evolution_bar = None

            # Get level for next evolution calculation
            current_level = cached_result.level if cached_result.success else state.level

            # Try to get next level info
            next_level_info = self._get_next_level_info(current_level + 1)
            if next_level_info:
                next_evolution = f"⬆️ {next_level_info['name']}"

                # Create evolution progress bar
                if cached_result.success and cached_result.bars and hasattr(cached_result.bars, 'mech_progress_current'):
                    evolution_bar = self._create_progress_bar(
                        cached_result.bars.mech_progress_current,
                        cached_result.bars.mech_progress_max
                    )
                elif not cached_result.success and hasattr(state, 'bars'):
                    evolution_bar = self._create_progress_bar(
                        state.bars.mech_progress_current,
                        state.bars.mech_progress_max
                    )

            # Get animation (use high resolution if requested) - use decimal power for proper animation selection
            animation_bytes, content_type = self._get_mech_animation(current_level, power_decimal, request.use_high_resolution)

            return MechStatusDetailsResult(
                success=True,
                level_text=level_text,
                speed_text=speed_text,
                power_text=power_text,
                power_bar=power_bar,
                energy_consumption=energy_consumption,
                next_evolution=next_evolution,
                evolution_bar=evolution_bar,
                animation_bytes=animation_bytes,
                content_type=content_type
            )

        except Exception as e:
            logger.error(f"Error getting mech status details: {e}", exc_info=True)
            return MechStatusDetailsResult(
                success=False,
                error=str(e)
            )

    def _get_speed_description(self, power: int) -> str:
        """Get speed description based on power level."""
        try:
            from services.mech.speed_levels import SPEED_DESCRIPTIONS

            # Calculate speed level (simplified)
            # Power 0 = OFFLINE, Power 1+ gets speed descriptions
            if power <= 0:
                return SPEED_DESCRIPTIONS.get(0, ("OFFLINE", "#888888"))[0]

            # Get speed level from power (simplified mapping)
            speed_level = min(power // 10 + 1, len(SPEED_DESCRIPTIONS) - 1)
            speed_level = max(1, speed_level)  # Minimum level 1

            return SPEED_DESCRIPTIONS.get(speed_level, ("Motionless", "#4a4a4a"))[0]

        except Exception as e:
            logger.debug(f"Error getting speed description: {e}")
            return "Motionless"

    def _create_progress_bar(self, current: int, maximum: int, length: int = 30) -> str:
        """Create a Unicode progress bar."""
        try:
            if maximum <= 0:
                percentage = 0.0
                filled = 0
            else:
                percentage = (current / maximum) * 100
                filled = int((current / maximum) * length)

            # Filled blocks
            bar = "█" * filled
            # Empty blocks
            bar += "░" * (length - filled)

            return f"{bar} {percentage:.1f}%"

        except Exception as e:
            logger.debug(f"Error creating progress bar: {e}")
            return "░" * length + " 0.0%"

    def _get_infinity_message(self) -> str:
        """Get Level 11 infinity message using the existing translation system."""
        try:
            # Use existing translation system from speed_levels.py
            from services.mech.speed_levels import SPEED_TRANSLATIONS

            # Get current language (same logic as existing system)
            try:
                from services.config.config_service import load_config

                config = load_config()
                if config:
                    language = config.get('language', 'en').lower()
                    if language not in ['en', 'de', 'fr']:
                        language = 'en'
                else:
                    language = 'en'
            except:
                language = 'en'

            # Get infinity message using existing translation structure
            if SPEED_TRANSLATIONS and 'infinity_messages' in SPEED_TRANSLATIONS:
                infinity_messages = SPEED_TRANSLATIONS['infinity_messages']
                level_11_messages = infinity_messages.get('level_11', {})
                message = level_11_messages.get(language, level_11_messages.get('en', "∞ reached infinity, Thank you! 🖤"))

                logger.debug(f"Level 11 infinity message ({language}): {message}")
                return message

            # Fallback if translation system unavailable
            fallback_messages = {
                'en': "∞ reached infinity, Thank you! 🖤",
                'de': "∞ Unendlichkeit erreicht, Danke! 🖤",
                'fr': "∞ infini atteint, Merci ! 🖤"
            }
            return fallback_messages.get(language, fallback_messages['en'])

        except Exception as e:
            logger.debug(f"Error getting infinity message: {e}")
            # Fallback to German (current default)
            return "∞ Unendlichkeit erreicht, Danke! 🖤"

    def _get_next_level_info(self, level: int) -> Optional[Dict[str, Any]]:
        """Get next level information."""
        try:
            from services.mech.mech_service import MECH_LEVELS

            for mech_level in MECH_LEVELS:
                if mech_level.level == level:
                    return {
                        'name': mech_level.name,
                        'threshold': mech_level.threshold
                    }
            return None

        except Exception as e:
            logger.debug(f"Error getting next level info: {e}")
            return None

    def _get_mech_animation(self, level: int, power: float, use_high_resolution: bool = False) -> tuple[Optional[bytes], Optional[str]]:
        """Get mech animation bytes with optional high resolution support via unified MechWebService."""
        try:
            # SERVICE FIRST: Use unified MechWebService for both resolutions
            from services.web.mech_web_service import get_mech_web_service, MechAnimationRequest

            web_service = get_mech_web_service()

            # Select resolution based on use_high_resolution flag
            resolution = "big" if use_high_resolution else "small"

            request = MechAnimationRequest(
                force_power=power,
                resolution=resolution
            )

            result = web_service.get_live_animation(request)

            if result.success:
                logger.debug(f"Loaded {resolution} animation for level {level} (power={power}): {len(result.animation_bytes)} bytes")
                return result.animation_bytes, result.content_type
            else:
                logger.debug(f"Animation service error: {result.error}")
                return None, None

        except Exception as e:
            logger.debug(f"Error getting mech animation: {e}")
            return None, None



# Global service instance
_mech_status_details_service: Optional[MechStatusDetailsService] = None


def get_mech_status_details_service() -> MechStatusDetailsService:
    """Get the global mech status details service instance."""
    global _mech_status_details_service
    if _mech_status_details_service is None:
        _mech_status_details_service = MechStatusDetailsService()
    return _mech_status_details_service