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
from dataclasses import dataclass
from datetime import datetime
from PIL import Image
from io import BytesIO
import discord

from utils.logging_utils import get_module_logger

logger = get_module_logger('animation_cache_service')


# ============================================================================
# SERVICE FIRST REQUEST/RESULT PATTERNS
# ============================================================================

@dataclass
class MechAnimationRequest:
    """
    Service First request for mech animation generation.

    Contains all required information to generate animations without
    requiring the service to query other services for state information.
    """
    evolution_level: int
    power_level: float = 1.0
    speed_level: float = 50.0
    include_metadata: bool = False


@dataclass
class MechAnimationResult:
    """
    Service First result for mech animation generation.

    Contains the animation bytes and comprehensive metadata about
    the generation process and cache status.
    """
    success: bool
    animation_bytes: Optional[bytes] = None

    # Animation metadata
    evolution_level: int = 0
    animation_type: str = ""  # "walk" or "rest"
    actual_speed_level: float = 0.0
    frame_count: int = 0
    canvas_size: Tuple[int, int] = (0, 0)

    # Cache metadata
    cache_hit: bool = False
    cache_key: str = ""
    generation_time_ms: float = 0.0

    # Error information
    error_message: Optional[str] = None

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

        # EVENT-BASED animation cache for Discord buttons - predictive caching system
        self._animation_memory_cache = {}
        self._last_cached_state = None  # Track last cached power/level for change detection

        # Predictive cache holds: current level + one level lower (for decay prediction)
        self._predictive_cache_enabled = True

        # Track significant changes for event-based invalidation
        self._significant_power_change_threshold = 0.5  # Invalidate if power changes by 0.5+

        # Background maintenance task configuration (4-hour intervals)
        self._maintenance_task = None
        self._maintenance_running = False
        self._maintenance_interval = 14400.0  # 4 hours in seconds

        # SERVICE FIRST: Event-based cache invalidation setup
        self._setup_event_listeners()

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
        elif animation_type == "status_overview":
            # Status overview animations for /ss command: reduce height by 2/3 (only 1/3 of original)
            # Rule: STATUS_OVERVIEW height = WALK height / 3 (rounded up)
            status_overview_heights = {
                1: 34,    # Walk 100px / 3 = 33.3 → 34px
                2: 34,    # Walk 100px / 3 = 33.3 → 34px
                3: 34,    # Walk 100px / 3 = 33.3 → 34px
                4: 50,    # Walk 150px / 3 = 50px
                5: 50,    # Walk 150px / 3 = 50px
                6: 57,    # Walk 170px / 3 = 56.7 → 57px
                7: 34,    # Walk 100px / 3 = 33.3 → 34px
                8: 34,    # Walk 100px / 3 = 33.3 → 34px
                9: 77,    # Walk 230px / 3 = 76.7 → 77px
                10: 84,   # Walk 250px / 3 = 83.3 → 84px
                11: 90    # Walk 270px / 3 = 90px
            }
            canvas_height = status_overview_heights.get(evolution_level, 34)  # Fallback to 34
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

            # ZERO SCALING: Always return 1.0 (no scaling) for pure crop result
            scale_factor = 1.0

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

        # ZERO SCALING: No canvas size needed - use pure crop result directly

        # Find PNG files with animation pattern
        import re
        png_files = []

        # Pattern depends on animation type: walk or rest
        if animation_type == "rest":
            # Rest pattern: 1_rest_0000.png, 2_rest_0000.png, etc.
            pattern = re.compile(rf"{evolution_level}_rest_(\d{{4}})\.png")
        else:
            # Walk pattern: 1_walk_0000.png, 2_walk_0000.png, etc.
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
                    # Walk animation pre-cropping (CORRECTED for native asset sizes)
                    if evolution_level == 4:
                        # Pre-crop 10 pixels from top and 5 pixels from bottom for Mech 4 (64x64 native)
                        frame_width, frame_height = frame.size
                        frame = frame.crop((0, 10, frame_width, frame_height - 5))
                        logger.debug(f"Mech 4 walk pre-crop: removed 10px from top, 5px from bottom, new size: {frame.size}")
                    elif evolution_level == 5:
                        # Pre-crop 8 pixels from top and 6 pixels from bottom for Mech 5 (64x64 native)
                        frame_width, frame_height = frame.size
                        frame = frame.crop((0, 8, frame_width, frame_height - 6))
                        logger.debug(f"Mech 5 walk pre-crop: removed 8px from top, 6px from bottom, new size: {frame.size}")
                    elif evolution_level == 6:
                        # Pre-crop 15 pixels from top and 8 pixels from bottom for Mech 6 (96x96 native)
                        frame_width, frame_height = frame.size
                        frame = frame.crop((0, 15, frame_width, frame_height - 8))
                        logger.debug(f"Mech 6 walk pre-crop: removed 15px from top, 8px from bottom, new size: {frame.size}")

                elif animation_type == "rest":
                    # REST pre-cropping (super!) + neue width-based Skalierung
                    frame_width, frame_height = frame.size

                    # CORRECTED pre-cropping für REST (optimized for native asset sizes)
                    # Adjusted values to work properly with native 128px height REST assets
                    rest_top_crop = {
                        1: 25, 2: 25, 3: 25,     # Level 1,2,3: 25px from top (conservative for 64x128)
                        4: 20,                    # Level 4: 20px from top (conservative for 64x128)
                        5: 16,                    # Level 5: 16px from top (conservative for 64x128)
                        6: 30,                    # Level 6: 30px from top (conservative for 96x128)
                        7: 35,                    # Level 7: 35px from top (conservative for 96x128)
                        8: 35,                    # Level 8: 35px from top (same as Level 7)
                        9: 40,                    # Level 9: 40px from top (conservative for 128x128)
                        10: 18                    # Level 10: 18px from top (conservative for 128x128)
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

        # KOMPLETT KEINE SKALIERUNG: Nur pures Smart Cropping, sonst nichts!
        # Direkt das gecroppte Resultat verwenden - ZERO weitere Manipulation

        logger.debug(f"Using pure crop result: {crop_width}x{crop_height} (ZERO scaling, ZERO canvas manipulation)")

        # Process all frames with unified cropping - PURE crop result only
        frames = []
        for frame in all_frames:
            # Apply unified crop to this frame
            if min_x != float('inf'):
                cropped = frame.crop((min_x, min_y, max_x, max_y))
            else:
                cropped = frame

            # DIREKTES Resultat ohne jegliche weitere Veränderung!
            frames.append(cropped)

        logger.debug(f"Processed {len(frames)} frames for evolution {evolution_level} with pure crop size {crop_width}x{crop_height}")
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
            allow_mixed=False,    # Force pure lossless, no mixed mode
            dpi=(300, 300)        # HIGH DPI for ultra-sharp rendering
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
                allow_mixed=False,    # Force pure lossless, no mixed mode
                dpi=(300, 300)        # HIGH DPI for ultra-sharp rendering
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
            # SERVICE FIRST VIOLATION: This method should be refactored to accept power as parameter
            # For now, reverting to working state while we refactor the calling services
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
            cache_service = get_mech_status_cache_service()
            cache_request = MechStatusCacheRequest(include_decimals=True)
            cached_state = cache_service.get_cached_status(cache_request)

            if not cached_state.success:
                logger.error("Failed to get cached mech state for animation")
                return None

            # Use decimal power to avoid rounding issues (0.5+ power should show as active)
            current_power = float(cached_state.power)

            # Calculate speed level from current power
            speed_level = self._calculate_speed_level_from_power(current_power, evolution_level)

            # Log the unified animation logic
            logger.debug(f"Auto-animation: evolution={evolution_level}, power={current_power:.4f}, speed={speed_level}")

            # EVENT-BASED PERFORMANCE: Check for significant state changes and update predictive cache
            current_state = {
                'evolution_level': evolution_level,
                'power': current_power,
                'speed': speed_level
            }

            # Check if we need to update our predictive cache (significant state change detected)
            cache_needs_update = self._check_state_change_significance(current_state)

            if cache_needs_update:
                logger.info(f"Significant state change detected - updating predictive animation cache")
                self._update_predictive_cache(evolution_level, current_power, speed_level)
                self._last_cached_state = current_state.copy()

            # Try to get animation from predictive cache
            cache_key = f"anim_{evolution_level}_{current_power:.2f}_{speed_level:.1f}"

            if cache_key in self._animation_memory_cache:
                cached_entry = self._animation_memory_cache[cache_key]
                logger.debug(f"Predictive cache hit: {cache_key}")
                return cached_entry['animation_bytes']

            # Cache miss - generate animation and update predictive cache
            logger.debug(f"Predictive cache miss: {cache_key} - generating and caching")
            animation_bytes = self.get_animation_with_speed_and_power(evolution_level, speed_level, current_power)

            if animation_bytes:
                # Store in predictive cache + generate one level lower for decay protection
                self._store_in_predictive_cache(evolution_level, current_power, speed_level, animation_bytes)
                self._last_cached_state = current_state.copy()

            return animation_bytes

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
                allow_mixed=False,    # Force pure lossless, no mixed mode
                dpi=(300, 300)        # HIGH DPI for ultra-sharp rendering
            )

            buffer.seek(0)
            adjusted_data = buffer.getvalue()
            logger.debug(f"Speed-adjusted animation: {len(adjusted_data)} bytes")
            return adjusted_data

        except Exception as e:
            logger.error(f"Failed to adjust animation speed: {e}")
            return animation_data  # Return original if adjustment fails

    # ========================================================================
    # SERVICE FIRST COMPLIANT ANIMATION METHODS
    # ========================================================================

    def get_mech_animation(self, request: MechAnimationRequest) -> MechAnimationResult:
        """
        Service First compliant method for mech animation generation.

        This method follows Service First principles by:
        - Accepting all required data via the request object
        - Not querying other services for state information
        - Returning comprehensive result with metadata
        - Being stateless and deterministic

        Args:
            request: MechAnimationRequest with all required parameters

        Returns:
            MechAnimationResult with animation bytes and metadata
        """
        start_time = time.time()

        try:
            # Validate request parameters
            if request.evolution_level < 1 or request.evolution_level > 11:
                return MechAnimationResult(
                    success=False,
                    error_message=f"Invalid evolution level: {request.evolution_level} (must be 1-11)"
                )

            # Use the existing Service First compliant method
            animation_bytes = self.get_animation_with_speed_and_power(
                evolution_level=request.evolution_level,
                speed_level=request.speed_level,
                power_level=request.power_level
            )

            if animation_bytes is None:
                return MechAnimationResult(
                    success=False,
                    error_message="Failed to generate animation bytes"
                )

            # Determine animation type based on power level
            animation_type = "rest" if request.power_level <= 0.0 and request.evolution_level <= 10 else "walk"

            # Get canvas size for metadata
            canvas_size = self.get_expected_canvas_size(request.evolution_level, animation_type)

            # Calculate generation time
            generation_time = (time.time() - start_time) * 1000

            # Build comprehensive result
            result = MechAnimationResult(
                success=True,
                animation_bytes=animation_bytes,
                evolution_level=request.evolution_level,
                animation_type=animation_type,
                actual_speed_level=request.speed_level,
                canvas_size=canvas_size,
                generation_time_ms=generation_time
            )

            # Add cache metadata if requested
            if request.include_metadata:
                # Check if this was a cache hit by timing (very fast = cache hit)
                result.cache_hit = generation_time < 10.0  # < 10ms = likely cache hit
                result.cache_key = f"mech_{request.evolution_level}_{animation_type}_{request.speed_level}"

            logger.debug(f"Service First animation generated: level={request.evolution_level}, "
                        f"type={animation_type}, speed={request.speed_level}, time={generation_time:.1f}ms")

            return result

        except Exception as e:
            logger.error(f"Error in Service First animation generation: {e}")
            return MechAnimationResult(
                success=False,
                error_message=str(e),
                generation_time_ms=(time.time() - start_time) * 1000
            )

    # ========================================================================
    # EVENT-BASED PREDICTIVE CACHING METHODS
    # ========================================================================

    def _check_state_change_significance(self, current_state: dict) -> bool:
        """Check if current state has changed significantly enough to warrant cache update."""
        if self._last_cached_state is None:
            return True  # First time - always update

        last_state = self._last_cached_state

        # Check for significant power change (0.5+ power difference)
        power_change = abs(current_state['power'] - last_state['power'])
        if power_change >= self._significant_power_change_threshold:
            logger.debug(f"Significant power change detected: {power_change:.2f}")
            return True

        # Check for evolution level change (new mech!)
        if current_state['evolution_level'] != last_state['evolution_level']:
            logger.debug(f"Evolution level changed: {last_state['evolution_level']} → {current_state['evolution_level']}")
            return True

        # Check for major speed change (crossing important thresholds)
        speed_change = abs(current_state['speed'] - last_state['speed'])
        if speed_change >= 10.0:  # 10+ speed level change
            logger.debug(f"Major speed change detected: {speed_change:.1f}")
            return True

        return False

    def _update_predictive_cache(self, evolution_level: int, current_power: float, speed_level: float):
        """Update predictive cache with current + lower level animations for decay protection."""
        try:
            # Clear old cache entries for this evolution level
            keys_to_remove = [k for k in self._animation_memory_cache.keys() if f"anim_{evolution_level}_" in k]
            for key in keys_to_remove:
                del self._animation_memory_cache[key]
                logger.debug(f"Cleared old cache entry: {key}")

            # Generate current animation
            current_animation = self.get_animation_with_speed_and_power(evolution_level, speed_level, current_power)
            if current_animation:
                current_key = f"anim_{evolution_level}_{current_power:.2f}_{speed_level:.1f}"
                self._animation_memory_cache[current_key] = {
                    'animation_bytes': current_animation,
                    'cached_at': time.time(),
                    'cache_type': 'current'
                }
                logger.debug(f"Cached current animation: {current_key} ({len(current_animation)} bytes)")

            # Generate predictive animation (lower power level for decay)
            if current_power > 1.0:  # Only if there's room to go lower
                lower_power = max(0.0, current_power - 1.0)  # 1 power level lower
                lower_speed = self._calculate_speed_level_from_power(lower_power, evolution_level)

                lower_animation = self.get_animation_with_speed_and_power(evolution_level, lower_speed, lower_power)
                if lower_animation:
                    lower_key = f"anim_{evolution_level}_{lower_power:.2f}_{lower_speed:.1f}"
                    self._animation_memory_cache[lower_key] = {
                        'animation_bytes': lower_animation,
                        'cached_at': time.time(),
                        'cache_type': 'predictive_lower'
                    }
                    logger.debug(f"Cached predictive lower animation: {lower_key} ({len(lower_animation)} bytes)")

        except Exception as e:
            logger.error(f"Error updating predictive cache: {e}")

    def _store_in_predictive_cache(self, evolution_level: int, current_power: float, speed_level: float, animation_bytes: bytes):
        """Store animation in predictive cache and generate companion lower-level animation."""
        try:
            # Store current animation
            current_key = f"anim_{evolution_level}_{current_power:.2f}_{speed_level:.1f}"
            self._animation_memory_cache[current_key] = {
                'animation_bytes': animation_bytes,
                'cached_at': time.time(),
                'cache_type': 'current'
            }

            # Generate and store predictive lower animation if enabled
            if self._predictive_cache_enabled and current_power > 1.0:
                lower_power = max(0.0, current_power - 1.0)
                lower_speed = self._calculate_speed_level_from_power(lower_power, evolution_level)

                lower_animation = self.get_animation_with_speed_and_power(evolution_level, lower_speed, lower_power)
                if lower_animation:
                    lower_key = f"anim_{evolution_level}_{lower_power:.2f}_{lower_speed:.1f}"
                    self._animation_memory_cache[lower_key] = {
                        'animation_bytes': lower_animation,
                        'cached_at': time.time(),
                        'cache_type': 'predictive_lower'
                    }
                    logger.debug(f"Generated predictive lower animation: {lower_key}")

        except Exception as e:
            logger.error(f"Error storing in predictive cache: {e}")

    def _setup_event_listeners(self):
        """Set up Service First event listeners for animation cache invalidation."""
        try:
            from services.infrastructure.event_manager import get_event_manager
            event_manager = get_event_manager()

            # Register listener for donation completion events
            event_manager.register_listener('donation_completed', self._handle_donation_event)

            # Register listener for mech state changes
            event_manager.register_listener('mech_state_changed', self._handle_state_change_event)

            logger.info("Event listeners registered for animation cache invalidation")

        except Exception as e:
            logger.error(f"Failed to setup event listeners: {e}")

    def _handle_donation_event(self, event_data):
        """Handle donation completion events for cache invalidation."""
        try:
            # Extract relevant data from event
            event_info = event_data.data
            reason = f"Donation completed: ${event_info.get('amount', 'unknown')}"

            # Invalidate cache since power/level may have changed
            self.invalidate_animation_cache(reason)

            logger.info(f"Animation cache invalidated due to donation event: {reason}")

        except Exception as e:
            logger.error(f"Error handling donation event: {e}")

    def _handle_state_change_event(self, event_data):
        """Handle mech state change events for selective cache invalidation."""
        try:
            # Extract state change information
            event_info = event_data.data
            old_power = event_info.get('old_power', 0)
            new_power = event_info.get('new_power', 0)

            # Only invalidate if power change is significant
            power_change = abs(new_power - old_power)
            if power_change >= self._significant_power_change_threshold:
                reason = f"Significant power change: {old_power:.2f} → {new_power:.2f}"
                self.invalidate_animation_cache(reason)
                logger.info(f"Animation cache invalidated due to state change: {reason}")
            else:
                logger.debug(f"Minor power change ignored: {old_power:.2f} → {new_power:.2f}")

        except Exception as e:
            logger.error(f"Error handling state change event: {e}")

    def invalidate_animation_cache(self, reason: str = "Manual invalidation"):
        """Manually invalidate the entire animation cache (for donation events or system updates)."""
        cache_count = len(self._animation_memory_cache)
        self._animation_memory_cache.clear()
        self._last_cached_state = None
        logger.info(f"Animation cache invalidated: {cache_count} entries cleared ({reason})")

    def get_cache_status(self) -> dict:
        """Get detailed cache status for monitoring and debugging."""
        cache_stats = {
            'total_entries': len(self._animation_memory_cache),
            'predictive_enabled': self._predictive_cache_enabled,
            'last_state': self._last_cached_state,
            'entries_by_type': {},
            'entries_detail': {}
        }

        # Categorize cache entries
        for key, entry in self._animation_memory_cache.items():
            cache_type = entry.get('cache_type', 'unknown')
            if cache_type not in cache_stats['entries_by_type']:
                cache_stats['entries_by_type'][cache_type] = 0
            cache_stats['entries_by_type'][cache_type] += 1

            # Detailed entry info
            age = time.time() - entry.get('cached_at', 0)
            cache_stats['entries_detail'][key] = {
                'type': cache_type,
                'size_bytes': len(entry['animation_bytes']),
                'age_seconds': round(age, 1)
            }

        return cache_stats

    # ========================================================================
    # BACKGROUND MAINTENANCE SYSTEM (4-HOUR INTERVALS)
    # ========================================================================

    async def start_maintenance_loop(self):
        """Start the 4-hour background maintenance loop for proactive animation cache updates."""
        if self._maintenance_running:
            logger.warning("Animation cache maintenance loop already running")
            return

        self._maintenance_running = True
        logger.info(f"Starting animation cache maintenance loop (interval: {self._maintenance_interval/3600:.1f} hours)")

        try:
            import asyncio
            while self._maintenance_running:
                await self._perform_maintenance_check()
                await asyncio.sleep(self._maintenance_interval)

        except asyncio.CancelledError:
            logger.info("Animation cache maintenance loop cancelled")
        except Exception as e:
            logger.error(f"Animation cache maintenance loop error: {e}")
        finally:
            self._maintenance_running = False
            logger.info("Animation cache maintenance loop stopped")

    async def _perform_maintenance_check(self):
        """Perform proactive maintenance: check if animations need updates due to power decay."""
        try:
            logger.info("Starting animation cache maintenance check...")

            # SERVICE FIRST VIOLATION: Maintenance should use Event Manager
            # For now, disabling maintenance until we implement event-based invalidation
            logger.info("Maintenance check disabled during Service First refactoring")
            return

            # TODO: Replace with Event Manager integration
            # The maintenance loop should listen for 'mech_state_changed' events
            # instead of polling the status cache service directly

            # Check if current state differs significantly from last cached state
            if self._last_cached_state:
                power_change = abs(current_power - self._last_cached_state['power'])
                level_change = evolution_level != self._last_cached_state['evolution_level']

                if power_change >= 0.25 or level_change:  # Lower threshold for maintenance
                    logger.info(f"Maintenance detected state change: power {power_change:.2f}, level change: {level_change}")

                    # Clear cache and let next access regenerate with current state
                    self.invalidate_animation_cache("Maintenance: detected power decay or level change")
                else:
                    logger.debug("Maintenance check: no significant changes detected")
            else:
                # First maintenance run - ensure cache is populated
                logger.info("First maintenance run - ensuring cache is populated")
                speed_level = self._calculate_speed_level_from_power(current_power, evolution_level)

                current_state = {
                    'evolution_level': evolution_level,
                    'power': current_power,
                    'speed': speed_level
                }
                self._update_predictive_cache(evolution_level, current_power, speed_level)
                self._last_cached_state = current_state

            logger.info("Animation cache maintenance check completed")

        except Exception as e:
            logger.error(f"Error during animation cache maintenance: {e}")

    def stop_maintenance_loop(self):
        """Stop the background maintenance loop."""
        self._maintenance_running = False
        if self._maintenance_task:
            self._maintenance_task.cancel()
            self._maintenance_task = None
        logger.info("Animation cache maintenance loop stop requested")

    def get_status_overview_animation(self, evolution_level: int, power_level: float = 1.0) -> bytes:
        """
        Get compact status overview animation for /ss command

        Creates a smaller animation (1/3 height) with transparent padding to maintain
        270px width. Perfect for Discord status displays where space is limited.

        Args:
            evolution_level: Mech evolution level (1-11)
            power_level: Current power level (0.0 = offline/rest, >0 = walk)

        Returns:
            Compact animation bytes optimized for status overview
        """
        try:
            from PIL import Image, ImageSequence
            from io import BytesIO

            # Determine animation type based on power (same logic as normal animations)
            if power_level <= 0.0 and evolution_level <= 10:
                animation_type = "rest"
                logger.debug(f"Status Overview: Using REST animation for evolution {evolution_level}")
            else:
                animation_type = "walk"
                logger.debug(f"Status Overview: Using WALK animation for evolution {evolution_level}")

            # Get the normal-sized animation first
            normal_animation_bytes = self.get_animation_with_speed_and_power(evolution_level, 50.0, power_level)

            # Load the WebP animation
            original_image = Image.open(BytesIO(normal_animation_bytes))

            # Get target dimensions
            target_canvas_size = self.get_expected_canvas_size(evolution_level, "status_overview")
            target_width, target_height = target_canvas_size

            logger.debug(f"Status Overview: Resizing from original to {target_width}x{target_height}")

            # Process each frame
            processed_frames = []
            durations = []

            for frame in ImageSequence.Iterator(original_image):
                # Convert to RGBA if not already
                frame = frame.convert("RGBA")

                # Get the frame's actual content size (excluding transparent areas)
                bbox = frame.getbbox()

                if bbox:
                    # Crop to content
                    cropped_frame = frame.crop(bbox)

                    # Calculate scale factor to fit target height while maintaining aspect ratio
                    original_height = cropped_frame.height
                    scale_factor = target_height / original_height
                    new_width = int(cropped_frame.width * scale_factor)
                    new_height = target_height

                    # Resize the cropped content
                    resized_frame = cropped_frame.resize((new_width, new_height), Image.LANCZOS)

                    # Create target canvas with transparent background
                    canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))

                    # Center the resized content horizontally
                    x_offset = (target_width - new_width) // 2
                    canvas.paste(resized_frame, (x_offset, 0), resized_frame)

                    processed_frames.append(canvas)
                else:
                    # Empty frame - create transparent canvas
                    canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
                    processed_frames.append(canvas)

                # Get frame duration (fallback to 125ms for 8 FPS)
                frame_duration = getattr(frame, 'info', {}).get('duration', 125)
                durations.append(frame_duration)

            # Save as WebP animation with maximum quality
            output_buffer = BytesIO()
            if processed_frames:
                processed_frames[0].save(
                    output_buffer,
                    format='WebP',
                    save_all=True,
                    append_images=processed_frames[1:],
                    duration=durations,
                    loop=0,                   # Infinite loop
                    lossless=True,           # LOSSLESS = absolute zero color loss!
                    quality=100,             # Maximum quality setting
                    method=6,                # SLOWEST compression = BEST quality
                    exact=True,              # Preserve exact pixel colors
                    minimize_size=False,     # Never sacrifice quality for size
                    allow_mixed=False,       # Force pure lossless, no mixed mode
                    dpi=(300, 300)           # HIGH DPI for ultra-sharp rendering
                )

            animation_bytes = output_buffer.getvalue()

            logger.info(f"Status Overview animation created: evolution {evolution_level} → {len(animation_bytes):,} bytes ({target_width}x{target_height})")
            return animation_bytes

        except Exception as e:
            logger.error(f"Error creating status overview animation: {e}")
            # Fallback: create a simple transparent canvas
            try:
                target_size = self.get_expected_canvas_size(evolution_level, "status_overview")
                fallback_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                buffer = BytesIO()
                fallback_img.save(buffer, format='WebP', lossless=True, quality=100, dpi=(300, 300))
                return buffer.getvalue()
            except:
                # Ultimate fallback
                return b''

    def get_discord_optimized_animation(self, evolution_level: int, power_level: float = 1.0) -> bytes:
        """
        Get Discord-optimized animation (50% size from full resolution for best quality)

        Creates a half-size animation by downscaling from full resolution. This gives
        better quality than generating small animations directly, while being more
        compact for Discord display.

        Args:
            evolution_level: Mech evolution level (1-11)
            power_level: Current power level (0.0 = offline/rest, >0 = walk)

        Returns:
            Discord-optimized animation bytes (50% size, high quality)
        """
        try:
            from PIL import Image, ImageSequence
            from io import BytesIO

            # Determine animation type based on power (same logic as normal animations)
            if power_level <= 0.0 and evolution_level <= 10:
                animation_type = "rest"
                logger.debug(f"Discord Optimized: Using REST animation for evolution {evolution_level}")
            else:
                animation_type = "walk"
                logger.debug(f"Discord Optimized: Using WALK animation for evolution {evolution_level}")

            # Get the full-size animation first
            full_size_bytes = self.get_animation_with_speed_and_power(evolution_level, 50.0, power_level)

            # Load the WebP animation
            original_image = Image.open(BytesIO(full_size_bytes))

            # ZERO SCALING for Discord: Use native animation size directly
            # No more 270px canvas or height reduction - pure native size
            actual_size = original_image.size  # Use the actual animation size (native)

            logger.debug(f"Discord Zero-Scaling: Using native animation size {actual_size[0]}x{actual_size[1]} directly")

            # ZERO SCALING: Return the original animation bytes directly without any processing
            logger.info(f"Discord Zero-Scaling animation: evolution {evolution_level} → {len(full_size_bytes):,} bytes ({actual_size[0]}x{actual_size[1]})")
            return full_size_bytes

        except Exception as e:
            logger.error(f"Error creating Discord optimized animation: {e}")
            # Fallback: create a simple transparent canvas - 270px width, 50% height
            try:
                original_size = self.get_expected_canvas_size(evolution_level, "walk")
                target_size = (270, original_size[1] // 2)  # Keep 270px width, reduce height by 50%
                fallback_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                buffer = BytesIO()
                fallback_img.save(buffer, format='WebP', lossless=True, quality=100, dpi=(300, 300))
                return buffer.getvalue()
            except:
                # Ultimate fallback
                return b''

# Singleton instance
_animation_cache_service = None

def get_animation_cache_service() -> AnimationCacheService:
    """Get or create the singleton animation cache service instance"""
    global _animation_cache_service
    if _animation_cache_service is None:
        _animation_cache_service = AnimationCacheService()
    return _animation_cache_service