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

            # Get animation (use high resolution if requested)
            animation_bytes, content_type = self._get_mech_animation(state.level, state.Power, request.use_high_resolution)

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


    def _generate_big_animation_prototype(self, level: int, power: float) -> Optional[bytes]:
        """Prototype implementation for big animation generation."""
        try:
            from services.mech.mech_high_res_service import get_mech_high_res_service, MechResolutionRequest
            from pathlib import Path
            from PIL import Image
            import io
            import re

            # Get high-res service info
            high_res_service = get_mech_high_res_service()
            request = MechResolutionRequest(evolution_level=level, preferred_resolution="big")
            result = high_res_service.get_mech_resolution_info(request)

            if not result.success or not result.has_big_version:
                return None

            # Load big PNG files directly for prototype
            big_folder = result.assets_folder
            animation_type = "rest" if power <= 0 and level <= 10 else "walk"

            # Find PNG files
            pattern = re.compile(rf'{level}_{animation_type}_(\d{{4}})\.png')
            png_files = [f for f in sorted(big_folder.glob('*.png')) if pattern.match(f.name)]

            if not png_files:
                logger.debug(f"No {animation_type} files found for level {level} in big folder")
                return None

            # Simple prototype: create WebP animation from big PNGs
            frames = []
            for png_file in png_files:
                with Image.open(png_file) as img:
                    # Apply smart cropping adjustments
                    if result.cropping_adjustments:
                        top = result.cropping_adjustments.get("top", 0)
                        bottom = result.cropping_adjustments.get("bottom", 0)

                        if top > 0 or bottom > 0:
                            width, height = img.size
                            crop_box = (0, top, width, height - bottom)
                            img = img.crop(crop_box)

                    # Smart crop to content
                    bbox = img.getbbox()
                    if bbox:
                        img = img.crop(bbox)

                    # Convert to RGBA for WebP
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')

                    frames.append(img.copy())

            if not frames:
                return None

            # Create WebP animation (high quality)
            output = io.BytesIO()
            frames[0].save(
                output,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=125,  # 8 FPS
                loop=0,
                lossless=True,
                quality=100,
                method=6
            )

            animation_bytes = output.getvalue()
            logger.debug(f"Generated big animation for level {level}: {len(animation_bytes)} bytes")
            return animation_bytes

        except Exception as e:
            logger.debug(f"Error generating big animation prototype: {e}")
            return None


# Global service instance
_mech_status_details_service: Optional[MechStatusDetailsService] = None


def get_mech_status_details_service() -> MechStatusDetailsService:
    """Get the global mech status details service instance."""
    global _mech_status_details_service
    if _mech_status_details_service is None:
        _mech_status_details_service = MechStatusDetailsService()
    return _mech_status_details_service