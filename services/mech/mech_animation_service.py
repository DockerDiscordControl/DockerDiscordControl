# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Unified Mech Animation Service - Redirects to PNG to WebP System
===============================================================

This service provides the same API but now uses the optimized PNG-to-WebP system.
"""

def get_mech_animation_service():
    """
    Get mech animation service - uses PNG to WebP system

    The new system:
    - Pre-generates WebP animations from PNG sequences (Mech1-11)
    - Uses cache for instant performance
    - Supports speed adjustment via frame duration
    - Works with Discord (WebP embedding) and WebUI
    - Single unified API for both platforms
    """
    from .png_to_webp_service import get_png_to_webp_service
    return get_png_to_webp_service()

# Compatibility alias for legacy imports
def MechAnimationService():
    """Legacy class alias - redirects to PNG-to-WebP service"""
    return get_mech_animation_service()