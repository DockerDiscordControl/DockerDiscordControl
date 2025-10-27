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
            # SINGLE POINT OF TRUTH: Use MechDataStore for all mech data
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest

            data_store = get_mech_data_store()
            data_request = MechDataRequest(include_decimals=True)
            data_result = data_store.get_comprehensive_data(data_request)

            if not data_result.success:
                return MechStatusDetailsResult(success=False, error="Failed to get mech data from MechDataStore")

            # Extract data from MechDataStore result
            power_decimal = data_result.current_power

            # Get speed description from MechDataStore
            # SPECIAL CASE: Level 11 is maximum level - always show "Göttlich" (no more speed changes)
            if data_result.current_level >= 11:
                speed_description = "Göttlich"  # Level 11 is final level with static divine speed
            else:
                speed_description = self._get_speed_description(int(data_result.current_power))

            # Format level text
            level_text = f"{data_result.level_name} (Level {data_result.current_level})"

            # Create power progress bar using MechDataStore bars data
            # SPECIAL CASE: Level 11 is maximum level - show infinity instead of speed bar
            if data_result.current_level >= 11:
                # For maximum level, show "reached infinity" message with appreciation (divine perfection achieved)
                power_bar = self._get_infinity_message()
            else:
                # Normal level progression - use Power bar data (not Evolution data)
                power_bar = self._create_progress_bar(
                    data_result.bars.Power_current,
                    data_result.bars.Power_max_for_level
                )

            # Format speed text
            speed_text = f"Geschwindigkeit: {speed_description}"

            # Format power with decimals
            power_text = f"⚡{power_decimal:.2f}"

            # Format energy consumption (dynamic) - Level 11 has no energy consumption
            current_level = data_result.current_level
            if current_level >= 11:
                energy_consumption = None  # Maximum level has no energy consumption
            else:
                # Get dynamic decay rate from evolution config (SERVICE FIRST: unified evolution system)
                from services.mech.mech_evolutions import get_evolution_level_info
                evolution_info = get_evolution_level_info(current_level)
                decay_per_day = evolution_info.decay_per_day if evolution_info else 1.0
                energy_consumption = f"Energieverbrauch: 🔻 {decay_per_day}/t"

            # Format next evolution
            next_evolution = None
            evolution_bar = None

            # Get level for next evolution calculation using MechDataStore
            current_level = data_result.current_level

            # Try to get next level info
            next_level_info = self._get_next_level_info(current_level + 1)
            if next_level_info:
                next_evolution = f"⬆️ {next_level_info['name']}"

                # Create evolution progress bar using MechDataStore evolution data
                # Calculate current progress toward next level
                total_donated = data_result.total_donated
                next_threshold = data_result.next_threshold

                # Find current level threshold (previous level's threshold)
                if current_level > 1:
                    current_threshold_info = self._get_next_level_info(current_level)
                    current_threshold = current_threshold_info.get('threshold', 0) if current_threshold_info else 0
                else:
                    current_threshold = 0

                # Calculate progress: how much of the gap between current and next threshold is filled
                progress_range = next_threshold - current_threshold
                progress_current = total_donated - current_threshold

                if progress_range > 0:
                    evolution_bar = self._create_progress_bar(progress_current, progress_range)
                else:
                    evolution_bar = self._create_progress_bar(100, 100)  # Full bar if at max level

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
        """Get next level information using MechDataStore."""
        try:
            from services.mech.mech_data_store import get_mech_data_store, EvolutionDataRequest

            data_store = get_mech_data_store()
            evolution_request = EvolutionDataRequest()
            evolution_result = data_store.get_evolution_info(evolution_request)

            if not evolution_result.success:
                logger.debug(f"Error getting evolution info from MechDataStore: {evolution_result.error}")
                return None

            # Get level information from MechDataStore
            if hasattr(evolution_result, 'level_data') and evolution_result.level_data:
                level_data = evolution_result.level_data

                # Find the requested level
                for level_info in level_data:
                    if hasattr(level_info, 'level') and level_info.level == level:
                        return {
                            'name': level_info.name,
                            'threshold': level_info.threshold,
                            'mode': evolution_result.evolution_mode,
                            'difficulty': evolution_result.difficulty_multiplier,
                            'base_threshold': getattr(level_info, 'base_threshold', level_info.threshold)
                        }

            # Fallback: construct from evolution result data
            if level <= 11:  # Valid mech levels
                # Use evolution result data for threshold calculation
                if evolution_result.evolution_mode == 'dynamic':
                    # For dynamic mode, we may not have exact level data, use base calculation
                    base_thresholds = [0, 20, 50, 100, 200, 350, 550, 800, 1100, 1450, 1850]
                    if level <= len(base_thresholds):
                        threshold = base_thresholds[level - 1] if level > 0 else 0
                    else:
                        return None
                else:
                    # For static mode, apply difficulty multiplier
                    base_thresholds = [0, 20, 50, 100, 200, 350, 550, 800, 1100, 1450, 1850]
                    if level <= len(base_thresholds):
                        base_threshold = base_thresholds[level - 1] if level > 0 else 0
                        threshold = int(base_threshold * evolution_result.difficulty_multiplier) if level > 1 else 0
                    else:
                        return None

                # Get level names (matching evolution_config.json) - Index aligned with level numbers
                level_names = ["INVALID", "The Rustborn Husk", "The Battle-Scarred Survivor", "The Corewalker Standard",
                              "The Titanframe", "The Pulseforged Guardian", "The Abyss Engine",
                              "The Rift Strider", "The Radiant Bastion", "The Overlord Ascendant",
                              "The Celestial Exarch", "OMEGA MECH"]

                if level < len(level_names) and level > 0:
                    return {
                        'name': level_names[level],  # Direct index: level_names[3] = "The Corewalker Standard"
                        'threshold': threshold,
                        'mode': evolution_result.evolution_mode,
                        'difficulty': evolution_result.difficulty_multiplier,
                        'base_threshold': base_thresholds[level - 1] if level > 0 and level <= len(base_thresholds) else 0
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