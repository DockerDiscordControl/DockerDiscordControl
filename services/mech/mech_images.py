#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Neues Mech-Images System mit dynamischer Geschwindigkeitsanpassung.
Unterstützt alle Level 1-10 mit verschlüsselten WebP-Animationen.
"""

import io
from PIL import Image
from typing import List, Optional, Tuple
import logging
from services.mech.mech_evolution_loader import get_mech_loader

# Logger
try:
    from utils.logging_utils import get_module_logger
    logger = get_module_logger('mech_images')
except:
    logger = logging.getLogger(__name__)

def get_mech_image(level: int, frame: int = 0) -> Optional[Image.Image]:
    """
    Holt ein einzelnes Mech-Bild.

    Args:
        level: Mech-Level (1-10)
        frame: Frame-Nummer (0-7)

    Returns:
        PIL Image oder None
    """
    return get_mech_loader().get_mech_image(level, frame)

def get_mech_frames(level: int) -> List[Image.Image]:
    """
    Holt alle Frames für ein Mech-Level.

    Args:
        level: Mech-Level (1-10)

    Returns:
        Liste von PIL Images
    """
    frames = []
    info = get_level_info(level)

    if not info:
        logger.warning(f"No info for level {level}")
        return frames

    frame_count = info.get('frames', 8)

    for frame_num in range(frame_count):
        img = get_mech_image(level, frame_num)
        if img:
            frames.append(img)
        else:
            logger.warning(f"Could not load frame {frame_num} for level {level}")
            break

    return frames

def get_mech_frames_for_speed(level: int, speed: int) -> Tuple[List[Image.Image], int]:
    """
    Holt Frames und berechnet die optimale Frame-Duration für die Geschwindigkeit.

    Args:
        level: Mech-Level (1-10)
        speed: Geschwindigkeitslevel (0-100)

    Returns:
        Tuple von (Liste von Images, Frame-Duration in ms)
    """
    frames = get_mech_frames(level)

    # Berechne Frame-Duration basierend auf Geschwindigkeit
    # Speed 0 = 100ms/frame (langsam), Speed 100 = 10ms/frame (schnell)
    duration = calculate_frame_duration(speed)

    return frames, duration

def calculate_frame_duration(speed: float) -> int:
    """
    Berechnet die Frame-Duration basierend auf der Geschwindigkeit.
    Verwendet eine Easing-Kurve für natürlichere Beschleunigung.

    Args:
        speed: Geschwindigkeitslevel (0-100)

    Returns:
        Frame-Duration in Millisekunden
    """
    # Clamp speed zwischen 0 und 100
    speed = max(0.0, min(100.0, speed))

    # Ease-out cubic für natürlichere Beschleunigung
    t = speed / 100.0
    eased = 1 - pow(1 - t, 3)

    # Map auf Duration: 100ms (langsam) bis 10ms (schnell)
    min_duration = 10
    max_duration = 100
    duration = max_duration - (max_duration - min_duration) * eased

    return int(round(duration))

def get_available_levels() -> List[int]:
    """Gibt Liste aller verfügbaren Level zurück."""
    return get_mech_loader().get_available_levels()

def get_level_info(level: int) -> Optional[dict]:
    """
    Holt Informationen über ein Level.

    Returns:
        Dict mit 'resolution', 'frames', etc.
    """
    return get_mech_loader().get_level_info(level)

def create_animated_gif(level: int, speed: int, with_overlay: bool = False) -> bytes:
    """
    Erstellt ein animiertes GIF mit angepasster Geschwindigkeit.

    Args:
        level: Mech-Level (1-10)
        speed: Geschwindigkeitslevel (0-100)
        with_overlay: Ob Power-Overlay hinzugefügt werden soll

    Returns:
        GIF als bytes
    """
    frames, duration = get_mech_frames_for_speed(level, speed)

    if not frames:
        logger.error(f"No frames for level {level}")
        return b''

    # Erstelle GIF
    buffer = io.BytesIO()

    # Speichere als animiertes GIF mit der berechneten Duration
    frames[0].save(
        buffer,
        'GIF',
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2  # Restore to background
    )

    buffer.seek(0)
    return buffer.getvalue()

# Test-Funktionen
if __name__ == "__main__":
    print("Testing new mech images system...")

    levels = get_available_levels()
    print(f"Available levels: {levels}")

    # Teste verschiedene Geschwindigkeiten
    test_speeds = [0, 25, 50, 75, 100]

    for level in [1, 5, 10]:
        if level in levels:
            print(f"\nLevel {level}:")
            info = get_level_info(level)
            print(f"  Info: {info}")

            for speed in test_speeds:
                frames, duration = get_mech_frames_for_speed(level, speed)
                print(f"  Speed {speed}: {len(frames)} frames @ {duration}ms/frame")

            # Teste GIF-Erstellung
            gif_data = create_animated_gif(level, 50)
            if gif_data:
                print(f"  ✓ GIF created: {len(gif_data)} bytes")