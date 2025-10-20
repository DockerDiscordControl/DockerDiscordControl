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
    pass  # No parameters needed - uses current mech state


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
            # Get current mech state
            from services.mech.mech_service import get_mech_service
            mech_service = get_mech_service()
            state = mech_service.get_state()

            # Get speed description
            speed_description = self._get_speed_description(state.Power)

            # Format level text
            level_text = f"{state.level_name} (Level {state.level})"

            # Format speed text
            speed_text = f"Geschwindigkeit: {speed_description}"

            # Format power with decimals
            power_decimal = mech_service.get_power_with_decimals()
            power_text = f"⚡{power_decimal:.2f}"

            # Create power progress bar
            power_bar = self._create_progress_bar(
                state.bars.Power_current,
                state.bars.Power_max_for_level
            )

            # Format energy consumption (simplified)
            energy_consumption = "Energieverbrauch: 🔻 1.0/t"

            # Format next evolution
            next_evolution = None
            evolution_bar = None
            if state.next_level_threshold is not None:
                next_level_info = self._get_next_level_info(state.level + 1)
                if next_level_info:
                    next_evolution = f"⬆️ {next_level_info['name']}"
                    evolution_bar = self._create_progress_bar(
                        state.bars.mech_progress_current,
                        state.bars.mech_progress_max
                    )

            # Get animation
            animation_bytes, content_type = self._get_mech_animation(state.level, state.Power)

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

    def _get_mech_animation(self, level: int, power: float) -> tuple[Optional[bytes], Optional[str]]:
        """Get mech animation bytes."""
        try:
            from services.web.mech_web_service import get_mech_web_service, MechAnimationRequest

            web_service = get_mech_web_service()
            request = MechAnimationRequest(force_power=power)
            result = web_service.get_live_animation(request)

            if result.success:
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