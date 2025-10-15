# -*- coding: utf-8 -*-
"""
Animation Cache Service - Pre-generates and caches mech animations
"""

import os
import re
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

        # Cache for walk scale factors to ensure rest mechs use identical scaling
        self._walk_scale_factors = {}

        logger.info(f"Animation Cache Service initialized")
        logger.info(f"Assets dir: {self.assets_dir}")
        logger.info(f"Cache dir: {self.cache_dir}")
        logger.info(f"Base animation speed: 8 FPS (125ms per frame)")

    def _obfuscate_data(self, data: bytes) -> bytes:
        """Simple XOR obfuscation to make WebP files unrecognizable when browsing filesystem"""
        # Super simple XOR key - fast and effective for hiding content
        xor_key = b'MechAnimCache2024'
        key_len = len(xor_key)

        # XOR each byte with repeating key pattern
        return bytes(data[i] ^ xor_key[i % key_len] for i in range(len(data)))

    def _deobfuscate_data(self, data: bytes) -> bytes:
        """Reverse the XOR obfuscation (XOR is symmetric)"""
        return self._obfuscate_data(data)  # XOR is its own inverse

    def get_expected_canvas_size(self, evolution_level: int, animation_type: str = "walk") -> Tuple[int, int]:
        """Get expected canvas size for an evolution level using predefined heights"""
        # Fixed heights per evolution level for walk animations
        walk_heights = {
            1: 100, 2: 100, 3: 100,  # Mech1-3: ~100px height
            4: 150, 5: 150,           # Mech4-5: ~150px height
            6: 170,                   # Mech 6: ~170px height
            7: 100, 8: 100,           # Mech 7-8: ~100px height (resized)
            9: 230,                   # Mech 9: ~230px height
            10: 250,                  # Mech 10: ~250px height
            11: 270                   # Mech 11: ~270px height
        }

        if animation_type == "rest":
            # Rest animations (offline mechs) with custom heights for levels 1-10
            # Level 11 never goes offline, so no rest animation
            if evolution_level <= 10:
                # Special height configuration for rest animations
                # Rule: REST height = WALK height + 60px for all levels
                rest_heights = {
                    1: 160,   # Walk 100px + 60px = 160px
                    2: 160,   # Walk 100px + 60px = 160px
                    3: 160,   # Walk 100px + 60px = 160px
                    4: 210,   # Walk 150px + 60px = 210px
                    5: 210,   # Walk 150px + 60px = 210px
                    6: 230,   # Walk 170px + 60px = 230px
                    7: 160,   # Walk 100px + 60px = 160px (resized)
                    8: 160,   # Walk 100px + 60px = 160px (needs space for charging cable)
                    9: 290,   # Walk 230px + 60px = 290px
                    10: 310   # Walk 250px + 60px = 310px
                }
                canvas_height = rest_heights.get(evolution_level, 200)  # Fallback to 200
            else:
                # Level 11 has no rest animation, fallback to walk height
                canvas_height = walk_heights.get(evolution_level, 270)
        else:
            # Walk animations use normal heights
            canvas_height = walk_heights.get(evolution_level, 100)

        # Canvas: Always 270px wide, with calculated height
        return (270, canvas_height)

    def get_cached_animation_path(self, evolution_level: int, animation_type: str = "walk") -> Path:
        """Get path for cached animation file (unified for Discord and Web UI)"""
        # For cache-only operations, use the requested evolution level directly
        # This prevents recursion when PNG folders are deleted
        if animation_type == "rest":
            filename = f"mech_{evolution_level}_rest_100speed.cache"
        else:
            filename = f"mech_{evolution_level}_100speed.cache"

        cache_path = self.cache_dir / filename

        # If cache exists, return the direct path
        if cache_path.exists():
            return cache_path

        # Only check for folder mapping if cache doesn't exist (for generation)
        try:
            actual_mech_folder = self._get_actual_mech_folder_no_cache_check(evolution_level)
            actual_level = int(actual_mech_folder.name[4:])  # Extract number from "Mech1", "Mech2", etc.

            if animation_type == "rest":
                filename = f"mech_{actual_level}_rest_100speed.cache"
            else:
                filename = f"mech_{actual_level}_100speed.cache"

            return self.cache_dir / filename
        except:
            # Fallback to direct evolution level if folder lookup fails
            return cache_path

    def _get_walk_scale_factor(self, evolution_level: int) -> float:
        """
        Get the exact scale factor used for walk animations.
        This ensures rest animations use identical scaling for visual consistency.
        """
        if evolution_level in self._walk_scale_factors:
            return self._walk_scale_factors[evolution_level]

        try:
            # Load walk animation frames to calculate actual scale factor
            mech_folder = self._get_actual_mech_folder(evolution_level)
            # Special case for Level 8: Use optimized smaller images with pattern 8_XXXX.png
            if evolution_level == 8:
                pattern = re.compile(rf'{evolution_level}_(\d{{4}})\.png')
            else:
                pattern = re.compile(rf'{evolution_level}_walk_(\d{{4}})\.png')
            png_files = [f for f in sorted(mech_folder.glob('*.png')) if pattern.match(f.name)]

            if not png_files:
                logger.warning(f"No walk PNG files found for level {evolution_level}, using fallback scale factor")
                self._walk_scale_factors[evolution_level] = 1.0
                return 1.0

            # Analyze frames to determine cropping bounds (same logic as _process_frames)
            min_x, min_y, max_x, max_y = float('inf'), float('inf'), 0, 0

            for png_file in png_files[:3]:  # Sample first 3 frames for efficiency
                with Image.open(png_file) as frame:
                    # Apply pre-cropping if needed (same logic as _process_frames)
                    if evolution_level == 4:
                        frame_height = frame.size[1]
                        frame = frame.crop((0, 45, frame.size[0], frame_height - 13))
                    elif evolution_level == 5:
                        frame_height = frame.size[1]
                        frame = frame.crop((0, 22, frame.size[0], frame_height - 14))
                    elif evolution_level == 6:
                        frame_height = frame.size[1]
                        frame = frame.crop((0, 48, frame.size[0], frame_height - 12))

                    bbox = frame.getbbox()
                    if bbox:
                        min_x = min(min_x, bbox[0])
                        min_y = min(min_y, bbox[1])
                        max_x = max(max_x, bbox[2])
                        max_y = max(max_y, bbox[3])

            if min_x == float('inf'):
                logger.warning(f"No content found in walk frames for level {evolution_level}")
                self._walk_scale_factors[evolution_level] = 1.0
                return 1.0

            # Calculate crop dimensions
            crop_width = max_x - min_x
            crop_height = max_y - min_y

            # Get walk canvas size and calculate scale factor (same logic as _process_frames)
            canvas_width, canvas_height = self.get_expected_canvas_size(evolution_level, "walk")
            max_mech_height = int(canvas_height * 0.90)
            max_mech_width = int(canvas_width * 0.90)

            scale_factor = min(max_mech_width / crop_width, max_mech_height / crop_height)

            # Cache the result
            self._walk_scale_factors[evolution_level] = scale_factor
            logger.debug(f"Calculated walk scale factor for level {evolution_level}: {scale_factor:.3f}")

            return scale_factor

        except Exception as e:
            logger.error(f"Error calculating walk scale factor for level {evolution_level}: {e}")
            self._walk_scale_factors[evolution_level] = 1.0
            return 1.0

    def _get_actual_mech_folder_no_cache_check(self, evolution_level: int) -> Path:
        """Original logic for getting mech folder without cache check"""
        mech_folder = self.assets_dir / f"Mech{evolution_level}"
        if not mech_folder.exists():
            # Fallback to Mech1
            mech_folder = self.assets_dir / "Mech1"
            if not mech_folder.exists():
                raise FileNotFoundError(f"No Mech folders found in {self.assets_dir}")
        return mech_folder

    def _get_actual_mech_folder(self, evolution_level: int) -> Path:
        """Get the actual mech folder that will be used (with fallback logic for cached animations)"""
        # If we have a cached animation, return virtual path (doesn't need to exist)
        cache_path = self.cache_dir / f"mech_{evolution_level}_100speed.cache"
        if cache_path.exists():
            return self.assets_dir / f"Mech{evolution_level}"

        # Use original logic for when PNG files are needed
        return self._get_actual_mech_folder_no_cache_check(evolution_level)

    def _load_and_process_frames(self, evolution_level: int, animation_type: str = "walk") -> List[Image.Image]:
        """Load PNG frames and process them with fixed canvas heights and preserved aspect ratio"""
        # Use the same folder detection logic as cache path
        mech_folder = self._get_actual_mech_folder(evolution_level)
        if mech_folder.name != f"Mech{evolution_level}":
            logger.warning(f"Mech{evolution_level} not found, using {mech_folder.name}")

        # Get fixed canvas size for this evolution level and animation type
        canvas_width, canvas_height = self.get_expected_canvas_size(evolution_level, animation_type)

        # Find PNG files with animation pattern
        import re
        png_files = []

        # Pattern depends on animation type: walk or rest
        if animation_type == "rest":
            # Rest pattern: 1_rest_0000.png, 2_rest_0000.png, etc.
            pattern = re.compile(rf"{evolution_level}_rest_(\d{{4}})\.png")
        else:
            # Walk pattern: 1_walk_0000.png, 2_walk_0000.png, etc.
            # Special case for Level 8: Use optimized smaller images with pattern 8_XXXX.png
            if evolution_level == 8:
                pattern = re.compile(rf"{evolution_level}_(\d{{4}})\.png")
            else:
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

                # Special handling for mechs with invisible glow/effects issues
                if animation_type == "walk":
                    # Walk animation pre-cropping (existing logic)
                    if evolution_level == 4:
                        # Pre-crop 45 pixels from top and 13 pixels from bottom for Mech 4
                        frame_width, frame_height = frame.size
                        frame = frame.crop((0, 45, frame_width, frame_height - 13))
                        logger.debug(f"Mech 4 walk pre-crop: removed 45px from top, 13px from bottom, new size: {frame.size}")
                    elif evolution_level == 5:
                        # Pre-crop 22 pixels from top and 14 pixels from bottom for Mech 5
                        frame_width, frame_height = frame.size
                        frame = frame.crop((0, 22, frame_width, frame_height - 14))
                        logger.debug(f"Mech 5 walk pre-crop: removed 22px from top, 14px from bottom, new size: {frame.size}")
                    elif evolution_level == 6:
                        # Pre-crop 48 pixels from top and 12 pixels from bottom for Mech 6
                        frame_width, frame_height = frame.size
                        frame = frame.crop((0, 48, frame_width, frame_height - 12))
                        logger.debug(f"Mech 6 walk pre-crop: removed 48px from top, 12px from bottom, new size: {frame.size}")

                elif animation_type == "rest":
                    # Rest animation pre-cropping (offline mechs) - remove invisible parts, keep smart cropping disabled
                    frame_width, frame_height = frame.size

                    # Define top crop values for each offline mech level (das war super!)
                    rest_top_crop = {
                        1: 135, 2: 135, 3: 135,  # Level 1,2,3: 135px from top
                        4: 110,                   # Level 4: 110px from top
                        5: 85,                    # Level 5: 85px from top
                        6: 100,                   # Level 6: 100px from top
                        7: 96,                    # Level 7: 96px from top
                        8: 125,                   # Level 8: 125px from top
                        9: 100,                   # Level 9: 100px from top
                        10: 45                    # Level 10: 45px from top
                    }

                    top_crop_pixels = rest_top_crop.get(evolution_level, 0)
                    if top_crop_pixels > 0:
                        frame = frame.crop((0, top_crop_pixels, frame_width, frame_height))
                        logger.debug(f"Mech {evolution_level} rest pre-crop: removed {top_crop_pixels}px from top, new size: {frame.size}")

                all_frames.append(frame)

                # Find bounding box of non-transparent pixels - for BOTH walk and rest
                bbox = frame.getbbox()
                if bbox:
                    x1, y1, x2, y2 = bbox
                    min_x = min(min_x, x1)
                    min_y = min(min_y, y1)
                    max_x = max(max_x, x2)
                    max_y = max(max_y, y2)

        # Calculate unified crop dimensions for entire animation (smart crop for both walk and rest)
        if min_x == float('inf'):
            # Fallback if no content found
            crop_width, crop_height = 64, 64
            logger.warning(f"No content found in frames, using fallback size")
        else:
            crop_width = max_x - min_x
            crop_height = max_y - min_y
            logger.debug(f"Smart crop found: {crop_width}x{crop_height} (from {min_x},{min_y} to {max_x},{max_y})")

        # Scale to fit within fixed canvas height while preserving aspect ratio
        if animation_type == "rest":
            # REST (offline) mech: Much smaller to show "weak/offline" state
            max_mech_height = int(canvas_height * 0.45)  # 45% of 160px = 72px max (klein!)
            max_mech_width = int(canvas_width * 0.45)    # 45% of 270px = 121px max
            logger.debug(f"REST mech using SMALL scale: max {max_mech_width}x{max_mech_height}")
        else:
            # WALK mech: Normal size
            max_mech_height = int(canvas_height * 0.90)  # 90% margin
            max_mech_width = int(canvas_width * 0.90)    # 90% margin
            logger.debug(f"WALK mech using NORMAL scale: max {max_mech_width}x{max_mech_height}")

        # Calculate scale factor to fit within both width and height constraints
        scale_factor = min(max_mech_width / crop_width, max_mech_height / crop_height)
        logger.debug(f"Final scale factor {scale_factor:.3f}")

        mech_width = int(crop_width * scale_factor)
        mech_height = int(crop_height * scale_factor)

        logger.debug(f"Canvas scaling: canvas {canvas_width}x{canvas_height}, mech {mech_width}x{mech_height}, scale {scale_factor:.3f}")

        # Process all frames with unified cropping and fixed canvas scaling
        frames = []
        for frame in all_frames:
            # Apply unified crop to this frame
            if min_x != float('inf'):
                cropped = frame.crop((min_x, min_y, max_x, max_y))
            else:
                cropped = frame

            # Scale mech to fit within fixed canvas - NEAREST for crystal sharp pixel art
            scaled_mech = cropped.resize((mech_width, mech_height), Image.NEAREST)

            # Create fixed-size canvas and center mech both horizontally and vertically
            canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
            x_offset = (canvas_width - mech_width) // 2
            y_offset = (canvas_height - mech_height) // 2

            canvas.paste(scaled_mech, (x_offset, y_offset), scaled_mech)
            frames.append(canvas)

        logger.debug(f"Processed {len(frames)} frames for evolution {evolution_level} with fixed canvas {canvas_width}x{canvas_height}")
        return frames

    def _smart_crop_frames(self, frames: List[Image.Image]) -> List[Image.Image]:
        """
        Smart crop all frames to remove transparent borders while maintaining aspect ratio.
        Finds the minimum bounding box that contains all non-transparent content across all frames.
        """
        if not frames:
            return frames

        # Find the collective bounding box across all frames
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = 0, 0

        for frame in frames:
            bbox = frame.getbbox()
            if bbox:
                frame_min_x, frame_min_y, frame_max_x, frame_max_y = bbox
                min_x = min(min_x, frame_min_x)
                min_y = min(min_y, frame_min_y)
                max_x = max(max_x, frame_max_x)
                max_y = max(max_y, frame_max_y)

        # If no content found, return original frames
        if min_x == float('inf'):
            return frames

        # Add minimal padding for rest animations (more aggressive cropping)
        padding = 2  # Reduced from 5 to 2 for better cropping
        original_width, original_height = frames[0].size
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x = min(original_width, max_x + padding)
        max_y = min(original_height, max_y + padding)

        # Crop all frames to the collective bounding box
        cropped_frames = []
        for frame in frames:
            cropped = frame.crop((min_x, min_y, max_x, max_y))
            cropped_frames.append(cropped)

        logger.debug(f"Smart crop: {original_width}x{original_height} → {max_x-min_x}x{max_y-min_y} (bbox: {min_x},{min_y},{max_x},{max_y})")
        return cropped_frames

    def _create_unified_webp(self, frames: List[Image.Image], base_duration: int = 125) -> bytes:
        """Create MAXIMUM QUALITY WebP animation with ZERO compromises - file size irrelevant"""
        buffer = BytesIO()
        frames[0].save(
            buffer,
            format='WebP',
            save_all=True,
            append_images=frames[1:],
            duration=base_duration,
            loop=0,
            lossless=True,        # LOSSLESS = absolute zero color loss!
            quality=100,          # Maximum quality setting
            method=6,             # SLOWEST compression = BEST quality (method 6 = maximum effort)
            exact=True,           # Preserve exact pixel colors
            minimize_size=False,  # Never sacrifice quality for size
            allow_mixed=False     # Force pure lossless, no mixed mode
        )

        buffer.seek(0)
        return buffer.getvalue()

    def pre_generate_animation(self, evolution_level: int, animation_type: str = "walk"):
        """Pre-generate and cache unified animation for given evolution level and type"""
        cache_path = self.get_cached_animation_path(evolution_level, animation_type)

        # Check if already cached
        if cache_path.exists():
            logger.debug(f"Animation already cached for evolution {evolution_level} ({animation_type})")
            return

        logger.info(f"Pre-generating {animation_type} animation for evolution level {evolution_level}")

        try:
            # Load and process frames
            frames = self._load_and_process_frames(evolution_level, animation_type)

            # Create unified WebP animation (for both Discord and Web UI)
            unified_webp = self._create_unified_webp(frames)
            # Obfuscate the WebP data before writing to disk
            obfuscated_data = self._obfuscate_data(unified_webp)
            with open(cache_path, 'wb') as f:
                f.write(obfuscated_data)
            logger.info(f"Generated {animation_type} animation: {cache_path} ({len(unified_webp)} bytes, obfuscated: {len(obfuscated_data)} bytes)")

        except Exception as e:
            logger.error(f"Failed to pre-generate {animation_type} animation for evolution {evolution_level}: {e}")

    def pre_generate_all_animations(self):
        """Pre-generate walk animations for all available evolution levels"""
        logger.info("Pre-generating all mech walk animations...")

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

        # Generate walk animations for each level
        for level in evolution_levels:
            self.pre_generate_animation(level, "walk")

        logger.info(f"Walk animation pre-generation complete for {len(evolution_levels)} evolution levels")

    def pre_generate_rest_animation(self, evolution_level: int):
        """Pre-generate rest (offline) animation for a specific evolution level"""
        if evolution_level >= 11:
            logger.info(f"Skipping rest animation for level {evolution_level} - level 11+ never goes offline")
            return

        logger.info(f"Pre-generating rest animation for evolution level {evolution_level}")
        self.pre_generate_animation(evolution_level, "rest")

    def pre_generate_all_rest_animations(self):
        """Pre-generate rest animations for levels 1-10 (level 11 never goes offline)"""
        logger.info("Pre-generating all mech rest animations (offline states)...")

        # Check what evolution levels we have, but only generate rest for 1-10
        evolution_levels = []
        for folder in self.assets_dir.iterdir():
            if folder.is_dir() and folder.name.startswith("Mech"):
                try:
                    level = int(folder.name[4:])  # Extract number from "Mech1", "Mech2", etc.
                    if level <= 10:  # Only levels 1-10 can go offline
                        evolution_levels.append(level)
                except ValueError:
                    continue

        evolution_levels.sort()
        logger.info(f"Found evolution levels for rest animations: {evolution_levels}")

        # Generate rest animations for each level 1-10
        for level in evolution_levels:
            self.pre_generate_rest_animation(level)

        logger.info(f"Rest animation pre-generation complete for {len(evolution_levels)} evolution levels")

    def get_animation_with_speed_and_power(self, evolution_level: int, speed_level: float, power_level: float = 1.0) -> bytes:
        """
        Get animation with adjusted speed, automatically selecting rest vs walk based on power

        Args:
            evolution_level: Mech evolution level
            speed_level: Desired speed (0-101)
            power_level: Current power level (0.0 = offline/rest, >0 = walk)

        Returns:
            Animation bytes with adjusted speed
        """
        # Determine animation type based on power
        if power_level <= 0.0 and evolution_level <= 10:
            animation_type = "rest"
            logger.debug(f"Using REST animation for evolution {evolution_level} (power: {power_level})")
        else:
            animation_type = "walk"
            logger.debug(f"Using WALK animation for evolution {evolution_level} (power: {power_level})")

        # Get cached animation path for the correct type
        cache_path = self.get_cached_animation_path(evolution_level, animation_type)

        # Ensure animation is cached
        if not cache_path.exists():
            logger.info(f"Cache miss - generating {animation_type} animation for evolution {evolution_level}")
            self.pre_generate_animation(evolution_level, animation_type)

        # Read cached animation and deobfuscate
        with open(cache_path, 'rb') as f:
            obfuscated_data = f.read()
        animation_data = self._deobfuscate_data(obfuscated_data)

        # For REST animations: Use constant speed (base 8 FPS) since offline mechs don't change speed
        if animation_type == "rest":
            logger.debug(f"Using constant speed for REST animation (power=0): evolution {evolution_level}")
            return animation_data  # Return cached version at base 8 FPS speed

        # For WALK animations: Apply speed adjustment based on power level
        # Calculate speed adjustment - 8 FPS base (125ms) with 80%-120% range
        base_duration = 125  # Match cached animation: 8 FPS = 125ms per frame
        speed_factor = 0.8 + (speed_level / 100.0) * 0.4  # 80% to 120% range
        speed_factor = max(0.8, min(1.2, speed_factor))  # Clamp to safe range
        new_duration = max(50, int(base_duration / speed_factor))  # Min 50ms for readability

        # If speed is exactly 100% (speed_level = 50), return cached version as-is
        if abs(speed_level - 50.0) < 5.0:
            logger.debug(f"Using cached {animation_type} animation at 100% speed for evolution {evolution_level}")
            return animation_data

        # Otherwise, adjust speed by re-encoding with new duration
        logger.debug(f"Adjusting {animation_type} speed for evolution {evolution_level}: {speed_level} → {new_duration}ms/frame")

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
            logger.error(f"Failed to parse cached {animation_type} animation: {e}")
            return animation_data  # Return original if parsing fails

        # Re-encode with new duration and MAXIMUM QUALITY - file size irrelevant
        buffer = BytesIO()
        try:
            frames[0].save(
                buffer,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=new_duration,
                loop=0,
                lossless=True,        # LOSSLESS = absolute zero color loss!
                quality=100,          # Maximum quality setting
                method=6,             # SLOWEST compression = BEST quality (method 6 = maximum effort)
                exact=True,           # Preserve exact pixel colors
                minimize_size=False,  # Never sacrifice quality for size
                allow_mixed=False     # Force pure lossless, no mixed mode
            )

            buffer.seek(0)
            adjusted_data = buffer.getvalue()
            logger.debug(f"Speed-adjusted {animation_type} animation: {len(adjusted_data)} bytes")
            return adjusted_data

        except Exception as e:
            logger.error(f"Failed to adjust {animation_type} animation speed: {e}")
            return animation_data  # Return original if adjustment fails

    def get_current_mech_animation(self, evolution_level: int) -> bytes:
        """
        Auto-animation: Get current mech animation with automatic power/speed detection

        This is the single source of truth for all mech animations:
        - Automatically queries current mech power (with decimals to avoid rounding issues)
        - Calculates appropriate speed level
        - Selects walk/rest animation based on power
        - Returns ready-to-use animation bytes

        Args:
            evolution_level: Mech evolution level (1-11)

        Returns:
            Animation bytes ready for Discord/WebUI display
        """
        try:
            # Single source of truth: get current mech state
            from services.mech.mech_service import get_mech_service
            mech_service = get_mech_service()

            # Use decimal power to avoid rounding issues (0.5+ power should show as active)
            current_power = float(mech_service.get_power_with_decimals())

            # Calculate speed level from current power
            speed_level = self._calculate_speed_level_from_power(current_power, evolution_level)

            # Log the unified animation logic
            logger.debug(f"Auto-animation: evolution={evolution_level}, power={current_power:.4f}, speed={speed_level}")

            # Delegate to unified power-based animation selection
            return self.get_animation_with_speed_and_power(evolution_level, speed_level, current_power)

        except Exception as e:
            logger.error(f"Error in auto-animation for evolution {evolution_level}: {e}")
            # Fallback to basic walk animation at normal speed
            return self.get_animation_with_speed_and_power(evolution_level, 50.0, 1.0)

    def _calculate_speed_level_from_power(self, current_power: float, evolution_level: int) -> float:
        """
        Calculate speed level from current power using evolution-specific max power

        Centralized speed calculation logic (moved from png_to_webp_service)
        """
        if current_power <= 0:
            return 0

        try:
            # Use the speed system that considers evolution-specific max power
            from services.mech.speed_levels import get_combined_mech_status

            # Get speed status using the power system
            speed_status = get_combined_mech_status(current_power)
            speed_level = speed_status['speed']['level']

            logger.debug(f"Calculated speed level {speed_level} for power ${current_power:.4f} at evolution {evolution_level}")
            return float(speed_level)

        except Exception as e:
            logger.error(f"Error calculating speed level: {e}")
            # Fallback to simple calculation
            return min(100, current_power)

    def clear_cache(self):
        """Clear all cached animations to force regeneration with new PNG files"""
        logger.info("Clearing animation cache to use new high-resolution PNG files...")
        self.cleanup_old_animations(keep_hours=0)  # Remove all cached files
        logger.info("✅ Animation cache cleared - new walk animations will be generated")

    def cleanup_old_animations(self, keep_hours: int = 24):
        """Remove cached animations older than specified hours"""
        if keep_hours == 0:
            # Remove all cached files
            for cache_file in self.cache_dir.glob("*.cache"):
                try:
                    cache_file.unlink()
                    logger.debug(f"Removed cache file: {cache_file.name}")
                except Exception as e:
                    logger.warning(f"Could not remove cache file {cache_file}: {e}")
            logger.info("Cleared all cached animations")
        else:
            # Remove files older than keep_hours
            cutoff_time = time.time() - (keep_hours * 3600)
            for cache_file in self.cache_dir.glob("*.cache"):
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

        # Read cached animation and deobfuscate
        with open(cache_path, 'rb') as f:
            obfuscated_data = f.read()
        animation_data = self._deobfuscate_data(obfuscated_data)

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

        # Re-encode with new duration and MAXIMUM QUALITY - file size irrelevant
        buffer = BytesIO()
        try:
            frames[0].save(
                buffer,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=new_duration,
                loop=0,
                lossless=True,        # LOSSLESS = absolute zero color loss!
                quality=100,          # Maximum quality setting
                method=6,             # SLOWEST compression = BEST quality (method 6 = maximum effort)
                exact=True,           # Preserve exact pixel colors
                minimize_size=False,  # Never sacrifice quality for size
                allow_mixed=False     # Force pure lossless, no mixed mode
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