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
        logger.info(f"Base animation speed: 8 FPS (125ms per frame)")

    def get_expected_canvas_size(self, evolution_level: int) -> Tuple[int, int]:
        """Get expected canvas size for an evolution level using smart cropping"""
        try:
            # Quick analysis to determine canvas size
            mech_folder = self._get_actual_mech_folder(evolution_level)

            import re
            pattern = re.compile(rf"{evolution_level}_walk_(\d{{4}})\.png")
            png_files = [f for f in sorted(mech_folder.glob("*.png")) if pattern.match(f.name)]

            if not png_files:
                return (270, 100)  # Fallback

            # Analyze first few frames to estimate size
            min_x, min_y = float('inf'), float('inf')
            max_x, max_y = 0, 0

            for png_path in png_files[:3]:  # Sample first 3 frames
                with Image.open(png_path) as img:
                    frame = img.convert('RGBA')
                    bbox = frame.getbbox()
                    if bbox:
                        x1, y1, x2, y2 = bbox
                        min_x = min(min_x, x1)
                        min_y = min(min_y, y1)
                        max_x = max(max_x, x2)
                        max_y = max(max_y, y2)

            if min_x == float('inf'):
                return (270, 100)  # Fallback

            crop_width = max_x - min_x
            crop_height = max_y - min_y

            # Use same content-based scaling logic as main processing
            content_area = crop_width * crop_height
            mech1_baseline_area = 1638
            area_ratio = content_area / mech1_baseline_area
            size_ratio = area_ratio ** 0.5
            max_mech_size = int(100 * size_ratio)
            max_mech_size = max(80, min(250, max_mech_size))
            scale_factor = min(max_mech_size / crop_width, max_mech_size / crop_height)
            mech_height = int(crop_height * scale_factor)

            # Canvas: 270px wide, height = mech height
            return (270, mech_height)

        except Exception as e:
            logger.warning(f"Could not determine canvas size for evolution {evolution_level}: {e}")
            return (270, 100)  # Fallback

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

    def _load_and_process_frames(self, evolution_level: int, target_size: Tuple[int, int] = (270, 135)) -> List[Image.Image]:
        """Load PNG frames and process them with proper aspect ratio"""
        # Use the same folder detection logic as cache path
        mech_folder = self._get_actual_mech_folder(evolution_level)
        if mech_folder.name != f"Mech{evolution_level}":
            logger.warning(f"Mech{evolution_level} not found, using {mech_folder.name}")

        # Find PNG files with new walk animation pattern
        import re
        png_files = []

        # New pattern: 1_walk_0000.png, 2_walk_0000.png, 3_walk_0000.png, etc.
        pattern = re.compile(rf"{evolution_level}_walk_(\d{{4}})\.png")

        for file in sorted(mech_folder.glob("*.png")):
            if pattern.match(file.name):
                png_files.append(file)

        if not png_files:
            raise FileNotFoundError(f"No PNG sequences found in {mech_folder}")

        # Sort by frame number (extract from filename)
        png_files.sort(key=lambda x: int(pattern.match(x.name).group(1)))

        # SMART CROPPING: First pass - analyze all frames to find minimal bounding box
        all_frames = []
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = 0, 0

        logger.debug(f"Smart cropping: Analyzing {len(png_files)} frames for evolution {evolution_level}")

        # Load all frames and find the minimal bounding box across entire animation
        for png_path in png_files:
            with Image.open(png_path) as img:
                # Ensure we preserve original color depth and avoid any conversion loss
                if img.mode != 'RGBA':
                    frame = img.convert('RGBA')
                else:
                    frame = img.copy()  # Direct copy if already RGBA to avoid conversion
                all_frames.append(frame)

                # Find bounding box of non-transparent pixels
                bbox = frame.getbbox()
                if bbox:
                    x1, y1, x2, y2 = bbox
                    min_x = min(min_x, x1)
                    min_y = min(min_y, y1)
                    max_x = max(max_x, x2)
                    max_y = max(max_y, y2)

        # Calculate unified crop dimensions for entire animation
        if min_x == float('inf'):
            # Fallback if no content found
            crop_width, crop_height = 64, 64
            logger.warning(f"No content found in frames, using fallback size")
        else:
            crop_width = max_x - min_x
            crop_height = max_y - min_y
            logger.debug(f"Smart crop found: {crop_width}x{crop_height} (from {min_x},{min_y} to {max_x},{max_y})")

        # Content-based proportional scaling using actual mech content area
        base_mech_size = 100  # Mech1 baseline = 100px

        # Calculate content area ratio (area scales quadratically, so we use square root for linear scaling)
        content_area = crop_width * crop_height
        mech1_baseline_area = 1638  # Mech1 actual content area from analysis

        # Use square root for proportional scaling (area → linear dimension)
        area_ratio = content_area / mech1_baseline_area
        size_ratio = area_ratio ** 0.5  # Square root for linear scaling

        # Apply scaling with reasonable limits
        max_mech_size = int(base_mech_size * size_ratio)

        # Set reasonable bounds: min 80px, max 250px
        max_mech_size = max(80, min(250, max_mech_size))

        logger.debug(f"Content-based scaling: area {content_area} vs baseline {mech1_baseline_area}, ratio {area_ratio:.2f}, size ratio {size_ratio:.2f}, final {max_mech_size}px")

        # Calculate scale factor to fit mech within proportional size while preserving aspect ratio
        scale_factor = min(max_mech_size / crop_width, max_mech_size / crop_height)
        mech_width = int(crop_width * scale_factor)
        mech_height = int(crop_height * scale_factor)

        # Canvas: 270px wide for Discord centering, height = mech height (no wasted space)
        canvas_width = 270
        canvas_height = mech_height

        logger.debug(f"Mech size: {mech_width}x{mech_height}, Canvas: {canvas_width}x{canvas_height}")

        # Process all frames with unified cropping and reasonable scaling
        frames = []
        for frame in all_frames:
            # Apply unified crop to this frame
            if min_x != float('inf'):
                cropped = frame.crop((min_x, min_y, max_x, max_y))
            else:
                cropped = frame

            # Scale mech to reasonable size - NEAREST for crystal sharp pixel art
            scaled_mech = cropped.resize((mech_width, mech_height), Image.NEAREST)

            # Create canvas and center mech horizontally
            canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
            x_offset = (canvas_width - mech_width) // 2
            y_offset = 0  # No vertical offset needed since canvas height = mech height

            canvas.paste(scaled_mech, (x_offset, y_offset), scaled_mech)
            frames.append(canvas)

        logger.debug(f"Processed {len(frames)} frames for evolution {evolution_level}")
        return frames

    def _create_unified_webp(self, frames: List[Image.Image], base_duration: int = 125) -> bytes:
        """Create CRYSTAL SHARP WebP animation with ZERO color loss at 8 FPS (125ms per frame)"""
        buffer = BytesIO()
        frames[0].save(
            buffer,
            format='WebP',
            save_all=True,
            append_images=frames[1:],
            duration=base_duration,
            loop=0,
            lossless=True,        # LOSSLESS = crystal sharp, zero color loss!
            quality=100,          # Maximum quality (for lossless this controls compression effort)
            method=0,             # FASTEST compression - with only 8 frames, speed matters more than size
            exact=True,           # Preserve exact colors
            minimize_size=False   # Don't sacrifice quality for size
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

    def clear_cache(self):
        """Clear all cached animations to force regeneration with new PNG files"""
        logger.info("Clearing animation cache to use new high-resolution PNG files...")
        self.cleanup_old_animations(keep_hours=0)  # Remove all cached files
        logger.info("✅ Animation cache cleared - new walk animations will be generated")

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

        # Calculate speed adjustment - 8 FPS base (125ms) with 80%-120% range
        base_duration = 125  # Match cached animation: 8 FPS = 125ms per frame
        speed_factor = 0.8 + (speed_level / 100.0) * 0.4  # 80% to 120% range
        speed_factor = max(0.8, min(1.2, speed_factor))  # Clamp to safe range
        new_duration = max(50, int(base_duration / speed_factor))  # Min 50ms for readability

        # If speed is exactly 100% (speed_level = 50), return cached version as-is
        if abs(speed_level - 50.0) < 5.0:
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

        # Re-encode with new duration and CRYSTAL SHARP quality
        buffer = BytesIO()
        try:
            frames[0].save(
                buffer,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=new_duration,
                loop=0,
                lossless=True,        # LOSSLESS = crystal sharp, zero color loss!
                quality=100,          # Maximum quality (compression effort for lossless)
                method=0,             # FASTEST compression - with only 8 frames, speed matters more than size
                exact=True,           # Preserve exact colors
                minimize_size=False   # Don't sacrifice quality for size
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