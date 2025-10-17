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
        """Create Discord-compatible animation file (async) - Thin wrapper over animation cache service"""
        try:
            from services.mech.mech_evolutions import get_evolution_level

            evolution_level = max(1, min(11, get_evolution_level(total_donations)))

            # Delegate all business logic to animation cache service
            webp_bytes = self.cache_service.get_current_mech_animation(evolution_level)

            # Interface adaptation: bytes -> Discord.File
            buffer = BytesIO(webp_bytes)
            return discord.File(buffer, filename=f"mech_animation_{int(time.time())}.webp", spoiler=False)

        except Exception as e:
            logger.error(f"Error creating donation animation: {e}")
            return self._create_fallback_animation()

    def create_donation_animation_sync(self, donor_name: str, amount: str, total_donations: float) -> bytes:
        """Create animation bytes for Web UI (sync) - Thin wrapper over animation cache service"""
        try:
            from services.mech.mech_evolutions import get_evolution_level

            evolution_level = max(1, min(11, get_evolution_level(total_donations)))

            # Delegate all business logic to animation cache service
            return self.cache_service.get_current_mech_animation(evolution_level)

        except Exception as e:
            logger.error(f"Error creating sync animation: {e}")
            # Simple fallback - use smart canvas size if possible
            try:
                from services.mech.mech_evolutions import get_evolution_level
                evolution_level = max(1, min(11, get_evolution_level(total_donations)))
                canvas_size = self.cache_service.get_expected_canvas_size(evolution_level)
            except:
                canvas_size = (270, 135)  # Ultimate fallback
            img = Image.new('RGBA', canvas_size, (47, 49, 54, 255))
            buffer = BytesIO()
            img.save(
                buffer,
                format='WebP',
                lossless=True,        # LOSSLESS = absolute zero color loss!
                quality=100,          # Maximum quality setting
                method=6,             # SLOWEST compression = BEST quality (method 6 = maximum effort)
                exact=True,           # Preserve exact pixel colors
                minimize_size=False,  # Never sacrifice quality for size
                allow_mixed=False     # Force pure lossless, no mixed mode
            )
            buffer.seek(0)
            return buffer.getvalue()


    def _create_fallback_animation(self) -> discord.File:
        """Create simple fallback animation"""
        img = Image.new('RGBA', (270, 100), (47, 49, 54, 255))  # Smaller fallback
        buffer = BytesIO()
        img.save(
            buffer,
            format='WebP',
            lossless=True,        # LOSSLESS = absolute zero color loss!
            quality=100,          # Maximum quality setting
            method=6,             # SLOWEST compression = BEST quality (method 6 = maximum effort)
            exact=True,           # Preserve exact pixel colors
            minimize_size=False,  # Never sacrifice quality for size
            allow_mixed=False     # Force pure lossless, no mixed mode
        )
        buffer.seek(0)
        return discord.File(buffer, filename="error_animation.webp")

    # Status view compatibility methods - Thin wrappers over unified animation system
    async def create_expanded_status_animation_async(self, power_level: float, total_donations: float):
        """Create compact animation for expanded /ss status view - Uses 2/3 smaller canvas"""
        from services.mech.mech_evolutions import get_evolution_level
        evolution_level = max(1, min(11, get_evolution_level(total_donations)))

        # Use compact status overview animation (1/3 height)
        compact_bytes = self.cache_service.get_status_overview_animation(evolution_level, power_level)

        # Convert to Discord File for async usage
        buffer = BytesIO(compact_bytes)
        return discord.File(buffer, filename=f"mech_status_expanded_{int(time.time())}.webp", spoiler=False)

    async def create_collapsed_status_animation_async(self, power_level: float, total_donations: float):
        """Create compact animation for collapsed /ss status view - Uses 2/3 smaller canvas"""
        from services.mech.mech_evolutions import get_evolution_level
        evolution_level = max(1, min(11, get_evolution_level(total_donations)))

        # Use compact status overview animation (1/3 height)
        compact_bytes = self.cache_service.get_status_overview_animation(evolution_level, power_level)

        # Convert to Discord File for async usage
        buffer = BytesIO(compact_bytes)
        return discord.File(buffer, filename=f"mech_status_collapsed_{int(time.time())}.webp", spoiler=False)

    def create_expanded_status_animation_sync(self, power_level: float, total_donations: float) -> bytes:
        """Create compact animation for expanded /ss status view (sync) - Uses 2/3 smaller canvas"""
        from services.mech.mech_evolutions import get_evolution_level
        evolution_level = max(1, min(11, get_evolution_level(total_donations)))

        # Use compact status overview animation (1/3 height)
        return self.cache_service.get_status_overview_animation(evolution_level, power_level)

    def create_collapsed_status_animation_sync(self, power_level: float, total_donations: float) -> bytes:
        """Create compact animation for collapsed /ss status view (sync) - Uses 2/3 smaller canvas"""
        from services.mech.mech_evolutions import get_evolution_level
        evolution_level = max(1, min(11, get_evolution_level(total_donations)))

        # Use compact status overview animation (1/3 height)
        return self.cache_service.get_status_overview_animation(evolution_level, power_level)

# Singleton instance
_png_to_webp_service = None

def get_png_to_webp_service() -> PngToWebpService:
    """Get or create the singleton PNG to WebP service instance"""
    global _png_to_webp_service
    if _png_to_webp_service is None:
        _png_to_webp_service = PngToWebpService()
    return _png_to_webp_service