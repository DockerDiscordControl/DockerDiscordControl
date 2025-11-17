#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Render Mech 10 small walk animation."""

import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def render_mech10_small():
    """Render Mech 10 small walk animation."""
    try:
        from services.mech.animation_cache_service import AnimationCacheService

        print("\n" + "="*80)
        print("Rendering Mech 10 Small Walk Animation")
        print("="*80)
        print("\nUsing 128x128 small PNGs (unchanged)\n")

        # Create service instance
        service = AnimationCacheService()

        # Pre-generate Mech 10 small walk animation
        print("Starting render...")
        service.pre_generate_animation(
            evolution_level=10,
            animation_type="walk",
            resolution="small"
        )

        print("\n" + "="*80)
        print("✅ SUCCESS: Mech 10 small walk animation rendered!")
        print("="*80 + "\n")

        return True

    except Exception as e:
        print(f"\n❌ ERROR: Failed to render animation")
        print(f"   {str(e)}")
        logger.error(f"Rendering error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = render_mech10_small()
    sys.exit(0 if success else 1)
