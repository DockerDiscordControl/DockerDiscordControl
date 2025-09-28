# -*- coding: utf-8 -*-
"""
Animation Cache Service - Pre-generates and caches mech animations
"""

import os
import time
import logging
from pathlib import Path
from typing import Tuple, List, Optional
from PIL import Image
from io import BytesIO
import discord

from utils.logging_utils import get_module_logger

logger = get_module_logger('animation_cache_service')

class AnimationCacheService:
    """
    Service that pre-generates mech animations at 100% speed and stores them permanently.
    Then dynamically adjusts speed by modifying frame durations on-the-fly.

    Benefits:
    - Much faster response times (no frame processing)
    - Consistent quality across all speed levels
    - Reduced CPU usage during runtime
    - Permanent storage for reliability
    """

    def __init__(self):
        # Use correct path for Docker vs Local
        import os
        if os.path.exists("/app/assets/mech_evolutions"):
            self.assets_dir = Path("/app/assets/mech_evolutions")
            self.cache_dir = Path("/app/cached_animations")
        else:
            self.assets_dir = Path("/Volumes/appdata/dockerdiscordcontrol/assets/mech_evolutions")
            self.cache_dir = Path("/Volumes/appdata/dockerdiscordcontrol/cached_animations")

        # Create cache directory
        self.cache_dir.mkdir(exist_ok=True)

        logger.info(f"Animation Cache Service initialized")
        logger.info(f"Assets dir: {self.assets_dir}")
        logger.info(f"Cache dir: {self.cache_dir}")

    def get_cached_animation_path(self, evolution_level: int) -> Path:
        """Get path for cached animation file (unified for Discord and Web UI)"""
        # Check if the specific mech folder exists
        actual_mech_folder = self._get_actual_mech_folder(evolution_level)
        actual_level = int(actual_mech_folder.name[4:])  # Extract number from "Mech1", "Mech2", etc.

        filename = f"mech_{actual_level}_100speed.webp"
        return self.cache_dir / filename

    def _get_actual_mech_folder(self, evolution_level: int) -> Path:
        """Get the actual mech folder that will be used (with fallback logic)"""
        mech_folder = self.assets_dir / f"Mech{evolution_level}"
        if not mech_folder.exists():
            # Fallback to Mech1
            mech_folder = self.assets_dir / "Mech1"
            if not mech_folder.exists():
                raise FileNotFoundError(f"No Mech folders found in {self.assets_dir}")
        return mech_folder

    def _load_and_process_frames(self, evolution_level: int, target_size: Tuple[int, int] = (270, 171)) -> List[Image.Image]:
        """Load PNG frames and process them with proper aspect ratio"""
        # Use the same folder detection logic as cache path
        mech_folder = self._get_actual_mech_folder(evolution_level)
        if mech_folder.name != f"Mech{evolution_level}":
            logger.warning(f"Mech{evolution_level} not found, using {mech_folder.name}")

        # Find PNG files with unified pattern (all mechs now use LEVEL_XXXX.png)
        import re
        png_files = []

        # Unified pattern: 1_0000.png, 2_0000.png, 3_0000.png, etc.
        pattern = re.compile(rf"{evolution_level}_(\d{{4}})\.png")

        for file in sorted(mech_folder.glob("*.png")):
            if pattern.match(file.name):
                png_files.append(file)

        if not png_files:
            raise FileNotFoundError(f"No PNG sequences found in {mech_folder}")

        # Sort by frame number (extract from filename)
        png_files.sort(key=lambda x: int(pattern.match(x.name).group(1)))

        # Process frames
        frames = []
        target_width, target_height = target_size

        for png_path in png_files:
            with Image.open(png_path) as img:
                frame = img.convert('RGBA')
                original_width, original_height = frame.size

                # Calculate scaling to preserve aspect ratio
                original_ratio = original_width / original_height
                target_ratio = target_width / target_height

                if original_ratio > target_ratio:
                    # Original is wider - scale by height
                    scaled_height = target_height
                    scaled_width = int(original_width * (target_height / original_height))
                else:
                    # Original is taller or same - scale by width
                    scaled_width = target_width
                    scaled_height = int(original_height * (target_width / original_width))

                # Scale mech preserving aspect ratio
                scaled_frame = frame.resize((scaled_width, scaled_height), Image.NEAREST)

                # Create transparent canvas
                canvas = Image.new('RGBA', target_size, (0, 0, 0, 0))

                # Calculate centering position
                x_offset = (target_width - scaled_width) // 2
                y_offset = (target_height - scaled_height) // 2

                # Paste scaled mech onto center of canvas
                canvas.paste(scaled_frame, (x_offset, y_offset), scaled_frame)
                frames.append(canvas)

        logger.debug(f"Processed {len(frames)} frames for evolution {evolution_level}")
        return frames

    def _create_unified_webp(self, frames: List[Image.Image], base_duration: int = 40) -> bytes:
        """Create unified WebP animation - RAW MINIMAL VERSION (works in Discord manually)"""
        # ABSOLUTE MINIMUM parameters - just what's required for WebP animation
        # No quality, no method, no lossless - let PIL use defaults
        buffer = BytesIO()
        frames[0].save(
            buffer,
            format='WebP',
            save_all=True,
            append_images=frames[1:],
            duration=base_duration,
            loop=0
        )

        buffer.seek(0)
        return buffer.getvalue()

    def pre_generate_animation(self, evolution_level: int):
        """Pre-generate and cache unified animation for given evolution level"""
        cache_path = self.get_cached_animation_path(evolution_level)

        # Check if already cached
        if cache_path.exists():
            logger.debug(f"Animation already cached for evolution {evolution_level}")
            return

        logger.info(f"Pre-generating unified animation for evolution level {evolution_level}")

        try:
            # Load and process frames
            frames = self._load_and_process_frames(evolution_level)

            # Create unified WebP animation (for both Discord and Web UI)
            unified_webp = self._create_unified_webp(frames)
            with open(cache_path, 'wb') as f:
                f.write(unified_webp)
            logger.info(f"Generated unified animation: {cache_path} ({len(unified_webp)} bytes)")

        except Exception as e:
            logger.error(f"Failed to pre-generate animation for evolution {evolution_level}: {e}")

    def pre_generate_all_animations(self):
        """Pre-generate animations for all available evolution levels"""
        logger.info("Pre-generating all mech animations...")

        # Check what evolution levels we have
        evolution_levels = []
        for folder in self.assets_dir.iterdir():
            if folder.is_dir() and folder.name.startswith("Mech"):
                try:
                    level = int(folder.name[4:])  # Extract number from "Mech1", "Mech2", etc.
                    evolution_levels.append(level)
                except ValueError:
                    continue

        evolution_levels.sort()
        logger.info(f"Found evolution levels: {evolution_levels}")

        # Generate for each level
        for level in evolution_levels:
            self.pre_generate_animation(level)

        logger.info(f"Pre-generation complete for {len(evolution_levels)} evolution levels")

    def cleanup_old_animations(self, keep_hours: int = 24):
        """Remove cached animations older than specified hours"""
        if keep_hours == 0:
            # Remove all cached files
            for cache_file in self.cache_dir.glob("*.webp"):
                try:
                    cache_file.unlink()
                    logger.debug(f"Removed cache file: {cache_file.name}")
                except Exception as e:
                    logger.warning(f"Could not remove cache file {cache_file}: {e}")
            logger.info("Cleared all cached animations")
        else:
            # Remove files older than keep_hours
            cutoff_time = time.time() - (keep_hours * 3600)
            for cache_file in self.cache_dir.glob("*.webp"):
                try:
                    if cache_file.stat().st_mtime < cutoff_time:
                        cache_file.unlink()
                        logger.debug(f"Removed old cache file: {cache_file.name}")
                except Exception as e:
                    logger.warning(f"Could not remove cache file {cache_file}: {e}")

    def get_animation_with_speed(self, evolution_level: int, speed_level: float) -> bytes:
        """
        Get unified animation with adjusted speed from cache

        Args:
            evolution_level: Mech evolution level
            speed_level: Desired speed (0-101)

        Returns:
            Animation bytes with adjusted speed
        """
        # Get cached animation path (unified for Discord and Web UI)
        cache_path = self.get_cached_animation_path(evolution_level)

        # Ensure animation is cached
        if not cache_path.exists():
            logger.info(f"Cache miss - generating animation for evolution {evolution_level}")
            self.pre_generate_animation(evolution_level)

        # Read cached animation
        with open(cache_path, 'rb') as f:
            animation_data = f.read()

        # Calculate speed adjustment
        base_duration = 40  # 100% speed baseline
        speed_factor = speed_level / 50.0 if speed_level > 0 else 0.1
        new_duration = max(10, int(base_duration / speed_factor))

        # If speed is exactly 100% (speed_level = 50), return cached version as-is
        if abs(speed_level - 50.0) < 0.1:
            logger.debug(f"Using cached animation at 100% speed for evolution {evolution_level}")
            return animation_data

        # Otherwise, adjust speed by re-encoding with new duration
        logger.debug(f"Adjusting speed for evolution {evolution_level}: {speed_level} → {new_duration}ms/frame")

        # Load the cached animation and re-save with new duration
        frames = []
        try:
            with Image.open(BytesIO(animation_data)) as img:
                frame_count = 0
                try:
                    while True:
                        frames.append(img.copy())
                        frame_count += 1
                        img.seek(frame_count)
                except EOFError:
                    pass
        except Exception as e:
            logger.error(f"Failed to parse cached animation: {e}")
            return animation_data  # Return original if parsing fails

        # Re-encode with new duration (RAW MINIMAL parameters)
        buffer = BytesIO()
        try:
            frames[0].save(
                buffer,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=new_duration,
                loop=0
            )

            buffer.seek(0)
            adjusted_data = buffer.getvalue()
            logger.debug(f"Speed-adjusted animation: {len(adjusted_data)} bytes")
            return adjusted_data

        except Exception as e:
            logger.error(f"Failed to adjust animation speed: {e}")
            return animation_data  # Return original if adjustment fails

# Singleton instance
_animation_cache_service = None

def get_animation_cache_service() -> AnimationCacheService:
    """Get or create the singleton animation cache service instance"""
    global _animation_cache_service
    if _animation_cache_service is None:
        _animation_cache_service = AnimationCacheService()
    return _animation_cache_service