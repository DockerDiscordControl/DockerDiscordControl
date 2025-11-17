#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Render Mech 10 big walk animation with corrected frames."""

import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def render_mech10_big():
    """Render Mech 10 big walk animation."""
    try:
        from services.mech.animation_cache_service import AnimationCacheService

        print("\n" + "="*80)
        print("Rendering Mech 10 Big Walk Animation")
        print("="*80)
        print("\nUsing corrected 412x412 high-quality PNGs")
        print("Frames 1 and 3 have been automatically aligned")
        print("Expected alignment quality: 18px variation (3.2% relative)\n")

        # Create service instance
        service = AnimationCacheService()

        # Pre-generate Mech 10 big walk animation
        print("Starting render...")
        service.pre_generate_animation(
            evolution_level=10,
            animation_type="walk",
            resolution="big"
        )

        print("\n" + "="*80)
        print("✅ SUCCESS: Mech 10 big walk animation rendered!")
        print("="*80)
        print("\nNext steps:")
        print("  1. Test in Discord (big mech button)")
        print("  2. Compare quality vs old upscaled version")
        print("  3. Verify smooth animation (no 'bounce')")
        print("="*80 + "\n")

        return True

    except Exception as e:
        print(f"\n❌ ERROR: Failed to render animation")
        print(f"   {str(e)}")
        logger.error(f"Rendering error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = render_mech10_big()
    sys.exit(0 if success else 1)
