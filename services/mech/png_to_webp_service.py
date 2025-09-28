# -*- coding: utf-8 -*-
"""
PNG to WebP Animation Service - Creates WebP animations from PNG sequences
"""

import time
import logging
from io import BytesIO
from PIL import Image
import discord

from utils.logging_utils import get_module_logger

logger = get_module_logger('png_to_webp_service')

class PngToWebpService:
    """
    Service that creates WebP animations from PNG frame sequences.

    Features:
    - Uses pre-generated WebP cache for performance
    - Adjusts speed based on power level
    - Provides unified API for Discord and WebUI
    """

    def __init__(self):
        from .animation_cache_service import get_animation_cache_service
        self.cache_service = get_animation_cache_service()
        logger.info("PNG to WebP Service initialized with cached animation system")

    async def create_donation_animation(self, donor_name: str, amount: str, total_donations: float, show_overlay: bool = True) -> discord.File:
        """Create Discord-compatible animation file (async)"""
        try:
            from services.mech.mech_evolutions import get_evolution_level
            from services.mech.mech_service import get_mech_service

            evolution_level = max(1, min(11, get_evolution_level(total_donations)))

            mech_service = get_mech_service()
            current_power = float(mech_service.get_state().Power)
            speed_level = self._calculate_speed_level_from_power(current_power, evolution_level)

            cache_path = self.cache_service.get_cached_animation_path(evolution_level)

            if not cache_path.exists():
                logger.info(f"Cache miss - generating animation for evolution {evolution_level}")
                self.cache_service.pre_generate_animation(evolution_level)

            # Speed adjustment logic
            base_duration = 40
            speed_factor = speed_level / 50.0 if speed_level > 0 else 0.1
            target_duration = max(10, int(base_duration / speed_factor))

            # Use direct file for normal speed, adjust for others
            if abs(speed_level - 50.0) < 5.0:
                logger.debug(f"Using direct cached WebP (speed ~50): {cache_path}")
                return discord.File(str(cache_path), filename=f"mech_animation_{int(time.time())}.webp", spoiler=False)

            # Speed adjustment via re-encoding
            logger.debug(f"Adjusting WebP speed: {speed_level} → {target_duration}ms/frame")

            webp_frames = []
            with Image.open(cache_path) as webp_img:
                frame_count = 0
                try:
                    while True:
                        frame = webp_img.copy()
                        webp_frames.append(frame)
                        frame_count += 1
                        webp_img.seek(frame_count)
                except EOFError:
                    pass

            buffer = BytesIO()
            if webp_frames:
                webp_frames[0].save(
                    buffer,
                    format='WebP',
                    save_all=True,
                    append_images=webp_frames[1:],
                    duration=target_duration,
                    loop=0
                )
                buffer.seek(0)
                return discord.File(buffer, filename=f"mech_animation_{int(time.time())}.webp", spoiler=False)

            # Fallback
            return discord.File(str(cache_path), filename=f"mech_animation_{int(time.time())}.webp", spoiler=False)

        except Exception as e:
            logger.error(f"Error creating donation animation: {e}")
            return self._create_fallback_animation()

    def create_donation_animation_sync(self, donor_name: str, amount: str, total_donations: float) -> bytes:
        """Create animation bytes for Web UI (sync)"""
        try:
            from services.mech.mech_evolutions import get_evolution_level
            from services.mech.mech_service import get_mech_service

            evolution_level = max(1, min(11, get_evolution_level(total_donations)))

            mech_service = get_mech_service()
            current_power = float(mech_service.get_state().Power)
            speed_level = self._calculate_speed_level_from_power(current_power, evolution_level)

            # Use cached animation system for WebUI too
            webp_bytes = self.cache_service.get_animation_with_speed(
                evolution_level=evolution_level,
                speed_level=speed_level
            )
            return webp_bytes

        except Exception as e:
            logger.error(f"Error creating sync animation: {e}")
            # Simple fallback
            img = Image.new('RGBA', (270, 171), (47, 49, 54, 255))
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            return buffer.getvalue()

    def _calculate_speed_level_from_power(self, current_power: float, evolution_level: int) -> float:
        """Calculate speed level from current power and evolution level"""
        if current_power <= 0:
            return 0

        stretch_factors = {
            1: 1.0, 2: 1.0, 3: 1.0,    # Levels 1-3: 1x
            4: 1.5, 5: 1.5, 6: 1.5,    # Levels 4-6: 1.5x
            7: 2.0, 8: 2.0, 9: 2.0,    # Levels 7-9: 2x
            10: 3.0, 11: 3.0           # Levels 10-11: 3x
        }

        stretch = stretch_factors.get(evolution_level, 1.0)
        speed = current_power / stretch

        # OMEGA speed at level 11 with high power
        if evolution_level == 11 and speed >= 100:
            return 101

        return min(100, max(0, speed))

    def _create_fallback_animation(self) -> discord.File:
        """Create simple fallback animation"""
        img = Image.new('RGBA', (270, 171), (47, 49, 54, 255))
        buffer = BytesIO()
        img.save(buffer, format='WebP', quality=90)
        buffer.seek(0)
        return discord.File(buffer, filename="error_animation.webp")

    # Status view compatibility methods
    async def create_expanded_status_animation_async(self, power_level: float, total_donations: float):
        """Create animation for expanded /ss status view"""
        return await self.create_donation_animation("Status", "0.00", total_donations, show_overlay=True)

    async def create_collapsed_status_animation_async(self, power_level: float, total_donations: float):
        """Create animation for collapsed /ss status view"""
        return await self.create_donation_animation("Status", "0.00", total_donations, show_overlay=False)

    def create_expanded_status_animation_sync(self, power_level: float, total_donations: float) -> bytes:
        """Create animation for expanded /ss status view (sync)"""
        return self.create_donation_animation_sync("Status", "0.00", total_donations)

    def create_collapsed_status_animation_sync(self, power_level: float, total_donations: float) -> bytes:
        """Create animation for collapsed /ss status view (sync)"""
        return self.create_donation_animation_sync("Status", "0.00", total_donations)

# Singleton instance
_png_to_webp_service = None

def get_png_to_webp_service() -> PngToWebpService:
    """Get or create the singleton PNG to WebP service instance"""
    global _png_to_webp_service
    if _png_to_webp_service is None:
        _png_to_webp_service = PngToWebpService()
    return _png_to_webp_service