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
    resolution: str = "small"  # "small" or "big" - for high-res support


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

        # EVENT-BASED animation cache for Discord buttons
        self._animation_memory_cache = {}


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

    def get_expected_canvas_size(self, evolution_level: int, animation_type: str = "walk", resolution: str = "small") -> Tuple[int, int]:
        """Get expected canvas size for an evolution level using predefined heights"""
        # For big resolution, delegate to high-res service
        if resolution == "big":
            from services.mech.mech_high_res_service import get_mech_high_res_service
            high_res_service = get_mech_high_res_service()
            return high_res_service.get_canvas_size_for_resolution(evolution_level, resolution, animation_type)

        # Fixed heights per evolution level for small walk animations
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

    def get_cached_animation_path(self, evolution_level: int, animation_type: str = "walk", resolution: str = "small") -> Path:
        """Get path for cached animation file (unified for Discord and Web UI, with resolution support)"""
        # For cache-only operations, use the requested evolution level directly
        # This prevents recursion when PNG folders are deleted
        if resolution == "big":
            if animation_type == "rest":
                filename = f"mech_{evolution_level}_rest_100speed_big.cache"
            else:
                filename = f"mech_{evolution_level}_100speed_big.cache"
        else:
            # Original small mech filenames for backward compatibility
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

            if resolution == "big":
                if animation_type == "rest":
                    filename = f"mech_{actual_level}_rest_100speed_big.cache"
                else:
                    filename = f"mech_{actual_level}_100speed_big.cache"
            else:
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

    def _get_actual_mech_folder(self, evolution_level: int, resolution: str = "small") -> Path:
        """Get the actual mech folder that will be used (with fallback logic for cached animations)"""
        # If we have a cached animation, return virtual path (doesn't need to exist)
        cache_path = self.cache_dir / f"mech_{evolution_level}_100speed.cache"
        if cache_path.exists():
            base_path = self.assets_dir / f"Mech{evolution_level}"
            if resolution == "big":
                return base_path / "big"
            else:
                return base_path / "small"

        # Use original logic for when PNG files are needed
        base_path = self._get_actual_mech_folder_no_cache_check(evolution_level)

        # Add resolution subfolder support
        if resolution == "big":
            big_path = base_path / "big"
            # Fallback to small if big doesn't exist
            if big_path.exists():
                return big_path
            else:
                return base_path / "small"
        else:
            small_path = base_path / "small"
            # Fallback to root if small doesn't exist (backward compatibility)
            if small_path.exists():
                return small_path
            else:
                return base_path

    def _load_and_process_frames(self, evolution_level: int, animation_type: str = "walk", resolution: str = "small") -> List[Image.Image]:
        """Load PNG frames and process them with fixed canvas heights and preserved aspect ratio"""
        # Use the same folder detection logic as cache path
        mech_folder = self._get_actual_mech_folder(evolution_level, resolution)
        # Check if we're using the correct Mech folder (parent folder name for resolution subfolders)
        expected_mech = f"Mech{evolution_level}"
        actual_mech = mech_folder.parent.name if mech_folder.name in ["big", "small"] else mech_folder.name
        if actual_mech != expected_mech:
            logger.warning(f"{expected_mech} not found, using {actual_mech} with {resolution} resolution")

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
                    # REST pre-cropping - COMPLETE ORIGINAL VALUES for small mechs, proportional for big mechs
                    frame_width, frame_height = frame.size

                    # Determine if we're processing big or small resolution
                    is_big_resolution = resolution == "big" if resolution else False

                    # Uniform REST pre-cropping: All offline mechs use 60px from top
                    rest_top_crop_small = {
                        1: 60, 2: 60, 3: 60,     # Level 1,2,3: 60px from top
                        4: 60,                    # Level 4: 60px from top
                        5: 60,                    # Level 5: 60px from top
                        6: 60,                    # Level 6: 60px from top
                        7: 60,                    # Level 7: 60px from top
                        8: 60,                    # Level 8: 60px from top
                        9: 60,                    # Level 9: 60px from top
                        10: 60                    # Level 10: 60px from top
                    }

                    small_crop_value = rest_top_crop_small.get(evolution_level, 0)

                    if small_crop_value > 0:
                        if is_big_resolution:
                            # Big REST: Uniform 116px cropping for ALL levels (manually verified)
                            # All levels use 116px÷60px = 1.9333 ratio for consistent offline appearance
                            uniform_ratio = 116/60  # 1.9333 - gives exactly 116px for all levels
                            size_ratios = {1: uniform_ratio, 2: uniform_ratio, 3: uniform_ratio, 4: uniform_ratio, 5: uniform_ratio, 6: uniform_ratio, 7: uniform_ratio, 8: uniform_ratio, 9: uniform_ratio, 10: uniform_ratio}
                            ratio = size_ratios.get(evolution_level, 1.3)  # Default fallback
                            big_crop_value = int(small_crop_value * ratio)
                            frame = frame.crop((0, big_crop_value, frame_width, frame_height))
                            logger.debug(f"Mech {evolution_level} big rest pre-crop: removed {big_crop_value}px from top (proportional, ratio {ratio:.2f}x), new size: {frame.size}")
                        else:
                            # Small REST: Original value
                            frame = frame.crop((0, small_crop_value, frame_width, frame_height))
                            logger.debug(f"Mech {evolution_level} small rest pre-crop: removed {small_crop_value}px from top (original), new size: {frame.size}")

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

    def pre_generate_animation(self, evolution_level: int, animation_type: str = "walk", resolution: str = "small"):
        """Pre-generate and cache unified animation for given evolution level, type, and resolution"""
        cache_path = self.get_cached_animation_path(evolution_level, animation_type, resolution)

        # Check if already cached
        if cache_path.exists():
            logger.debug(f"Animation already cached for evolution {evolution_level} ({animation_type}, {resolution})")
            return

        logger.info(f"Pre-generating {animation_type} animation for evolution level {evolution_level} ({resolution} resolution)")

        try:
            # Load and process frames
            frames = self._load_and_process_frames(evolution_level, animation_type, resolution)

            # Create unified WebP animation (for both Discord and Web UI)
            unified_webp = self._create_unified_webp(frames)
            # Obfuscate the WebP data before writing to disk
            obfuscated_data = self._obfuscate_data(unified_webp)
            with open(cache_path, 'wb') as f:
                f.write(obfuscated_data)
            logger.info(f"Generated {animation_type} animation ({resolution}): {cache_path} ({len(unified_webp)} bytes, obfuscated: {len(obfuscated_data)} bytes)")

        except Exception as e:
            logger.error(f"Failed to pre-generate {animation_type} animation for evolution {evolution_level} ({resolution}): {e}")

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

    def pre_generate_big_animation(self, evolution_level: int, animation_type: str = "walk"):
        """Pre-generate big mech animation for a specific evolution level (native resolution after crop)"""
        logger.info(f"Pre-generating big {animation_type} animation for evolution level {evolution_level}")
        self.pre_generate_animation(evolution_level, animation_type, "big")

    def pre_generate_all_big_animations(self):
        """Pre-generate all big mech walk and rest animations (native resolution)"""
        logger.info("Pre-generating ALL big mech animations (walk + rest) at native resolution...")

        # Check what evolution levels we have
        evolution_levels = []
        for folder in self.assets_dir.iterdir():
            if folder.is_dir() and folder.name.startswith("Mech"):
                try:
                    level = int(folder.name[4:])  # Extract number from "Mech1", "Mech2", etc.

                    # Check if big version exists
                    big_folder = folder / "big"
                    if big_folder.exists():
                        evolution_levels.append(level)
                    else:
                        logger.warning(f"No big folder found for Mech{level}, skipping big animation generation")
                except ValueError:
                    continue

        evolution_levels.sort()
        logger.info(f"Found big mech levels: {evolution_levels}")

        # Generate both walk and rest animations for each level
        for level in evolution_levels:
            # Generate walk animation
            self.pre_generate_big_animation(level, "walk")

            # Generate rest animation (only for levels 1-10, level 11 never goes offline)
            if level <= 10:
                self.pre_generate_big_animation(level, "rest")
            else:
                logger.info(f"Skipping rest animation for big Mech{level} - level 11+ never goes offline")

        logger.info(f"Big mech animation pre-generation complete for {len(evolution_levels)} evolution levels")

    def pre_generate_all_unified_animations(self):
        """
        Pre-generate ALL animations in BOTH resolutions (small + big) for unified cache.
        Service First: Single method to populate complete animation cache.
        """
        logger.info("🚀 Pre-generating UNIFIED animation cache (small + big resolutions)...")

        # Step 1: Generate all small animations (walk + rest)
        logger.info("📦 Generating small resolution animations...")
        self.pre_generate_all_animations()      # Walk animations
        self.pre_generate_all_rest_animations() # Rest animations

        # Step 2: Generate all big animations (walk + rest)
        logger.info("📦 Generating big resolution animations...")
        self.pre_generate_all_big_animations()  # Walk + Rest animations

        logger.info("✅ Unified animation cache complete!")
        logger.info("   • Small animations: walk + rest for all levels")
        logger.info("   • Big animations: walk + rest for all levels")
        logger.info("   • Consistent animation selection logic across resolutions")

    def get_animation_with_speed_and_power_big(self, evolution_level: int, speed_level: float, power_level: float = 1.0) -> bytes:
        """
        Get big mech animation with adjusted speed, automatically selecting rest vs walk based on power
        Returns native resolution animations after smart cropping (no scaling)
        """
        # Determine animation type based on power
        if power_level <= 0.0 and evolution_level <= 10:
            animation_type = "rest"
        else:
            animation_type = "walk"

        # PERFORMANCE FIX: Check memory cache first for speed-adjusted big animations
        cache_key = f"big_level_{evolution_level}_{animation_type}_{speed_level:.1f}"
        if cache_key in self._animation_memory_cache:
            logger.debug(f"Memory cache HIT for big {animation_type} animation: level {evolution_level}, speed {speed_level}")
            return self._animation_memory_cache[cache_key]['animation_bytes']

        # Get cached big animation
        cache_path = self.get_cached_animation_path(evolution_level, animation_type, "big")

        if cache_path.exists():
            # Load obfuscated data and deobfuscate
            with open(cache_path, 'rb') as f:
                obfuscated_data = f.read()

            animation_data = self._deobfuscate_data(obfuscated_data)

            # For REST animations: Use constant speed (no adjustment)
            if animation_type == "rest":
                logger.debug(f"Using constant speed for big REST animation (power=0): evolution {evolution_level}")
                return animation_data  # Return cached version at base 8 FPS speed

            # For WALK animations: Apply speed adjustment based on power level (same logic as small mechs)
            # Calculate speed adjustment - 8 FPS base (125ms) with 80%-120% range
            base_duration = 125  # Match cached animation: 8 FPS = 125ms per frame
            speed_factor = 0.8 + (speed_level / 100.0) * 0.4  # 80% to 120% range
            speed_factor = max(0.8, min(1.2, speed_factor))  # Clamp to safe range
            new_duration = max(50, int(base_duration / speed_factor))  # Min 50ms for readability

            # If speed is exactly 100% (speed_level = 50), return cached version as-is
            if abs(speed_level - 50.0) < 5.0:
                logger.debug(f"Using cached big {animation_type} animation at 100% speed for evolution {evolution_level}")

                # PERFORMANCE FIX: Store base animation in memory cache too
                self._animation_memory_cache[cache_key] = {
                    'animation_bytes': animation_data,
                    'cached_at': time.time()
                }
                return animation_data

            # Otherwise, adjust speed by re-encoding with new duration
            logger.debug(f"Adjusting big {animation_type} speed for evolution {evolution_level}: {speed_level} → {new_duration}ms/frame")

            # Load the cached animation and re-save with new duration (same logic as small mechs)
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
                logger.error(f"Failed to parse cached big {animation_type} animation: {e}")
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

                # PERFORMANCE FIX: Store speed-adjusted animation in memory cache
                self._animation_memory_cache[cache_key] = {
                    'animation_bytes': adjusted_data,
                    'cached_at': time.time()
                }
                logger.debug(f"Speed-adjusted big {animation_type} animation cached in memory: {len(adjusted_data)} bytes")
                return adjusted_data

            except Exception as e:
                logger.error(f"Failed to adjust big {animation_type} animation speed: {e}")
                return animation_data  # Return original if adjustment fails

        else:
            logger.error(f"Big {animation_type} animation for evolution {evolution_level} not found in cache: {cache_path}")
            # Fallback to generating on-demand (not recommended for production)
            frames = self._load_and_process_frames(evolution_level, animation_type, "big")
            data = self._create_unified_webp(frames)
            logger.warning(f"Generated big {animation_type} animation on-demand for evolution {evolution_level}: {len(data)} bytes")
            return data

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
        """Handle donation completion events for cache invalidation and immediate re-caching."""
        try:
            # Extract relevant data from event
            event_info = event_data.data
            reason = f"Donation completed: ${event_info.get('amount', 'unknown')}"

            # Invalidate cache since power/level may have changed
            self.invalidate_animation_cache(reason)

            logger.info(f"Animation cache invalidated due to donation event: {reason}")

            # PROACTIVE RE-CACHING: Immediately cache new animations for current state
            # This prevents 2-second delays when user clicks "Mech Details" after donations
            try:
                import asyncio
                # Schedule immediate re-caching (non-blocking)
                asyncio.create_task(self._async_recache_current_animations(reason="donation_event"))
                logger.info("Immediate animation re-caching scheduled after donation event")
            except Exception as recache_error:
                logger.warning(f"Could not schedule immediate re-caching: {recache_error}")

        except Exception as e:
            logger.error(f"Error handling donation event: {e}")

    def _handle_state_change_event(self, event_data):
        """Handle mech state change events for selective cache invalidation and re-caching."""
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

                # PROACTIVE RE-CACHING: Schedule immediate animation refresh
                try:
                    import asyncio
                    asyncio.create_task(self._async_recache_current_animations(reason="state_change_event"))
                    logger.info("Immediate animation re-caching scheduled after state change")
                except Exception as recache_error:
                    logger.warning(f"Could not schedule re-caching after state change: {recache_error}")
            else:
                logger.debug(f"Minor power change ignored: {old_power:.2f} → {new_power:.2f}")

        except Exception as e:
            logger.error(f"Error handling state change event: {e}")

    def invalidate_animation_cache(self, reason: str = "Manual invalidation"):
        """Manually invalidate the entire animation cache (for donation events or system updates)."""
        # Clear memory cache
        cache_count = len(self._animation_memory_cache)
        self._animation_memory_cache.clear()

        # Also clear file caches (big animations) to ensure consistency
        file_count = 0
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
                file_count += 1
            except Exception as e:
                logger.warning(f"Could not remove cache file {cache_file}: {e}")

        logger.info(f"Animation cache invalidated: {cache_count} memory entries + {file_count} file caches cleared ({reason})")

    def get_cache_status(self) -> dict:
        """Get detailed cache status for monitoring and debugging."""
        cache_stats = {
            'total_entries': len(self._animation_memory_cache),
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
    # INITIAL CACHE WARMUP (used for container startup and events)
    # ========================================================================

    async def perform_initial_cache_warmup(self):
        """Perform initial animation cache warmup on container startup."""
        try:
            logger.info("Performing initial animation cache warmup...")

            # Get current mech status from cache service
            from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
            from services.mech.speed_levels import get_combined_mech_status

            cache_service = get_mech_status_cache_service()
            cache_request = MechStatusCacheRequest(include_decimals=True)
            mech_result = cache_service.get_cached_status(cache_request)

            if not mech_result.success:
                logger.warning("Could not get mech status for warmup - skipping")
                return

            current_level = mech_result.level
            current_power = mech_result.power

            # Calculate current speed level
            speed_status = get_combined_mech_status(current_power)
            current_speed_level = speed_status['speed']['level']

            logger.info(f"Cache warmup: Level {current_level}, Power {current_power:.2f}, Speed {current_speed_level}")

            # Proactively cache animations for current speed level
            # This prevents live re-encoding during Discord interactions

            # Determine which animation types to cache based on level
            animation_types = ["walk"]  # All levels have walk animations
            if current_level <= 10:
                animation_types.append("rest")  # Only levels 1-10 have rest animations

            logger.debug(f"Caching animation types for Level {current_level}: {animation_types}")

            for animation_type in animation_types:
                try:
                    # Cache small animation with current speed
                    small_key = f"small_level_{current_level}_{animation_type}_{current_speed_level:.1f}"
                    if small_key not in self._animation_memory_cache:
                        logger.debug(f"Pre-caching small {animation_type} animation for level {current_level}, speed {current_speed_level}")
                        self.get_animation_with_speed_and_power(current_level, current_speed_level, current_power)

                    # Cache big animation with current speed
                    big_key = f"big_level_{current_level}_{animation_type}_{current_speed_level:.1f}"
                    if big_key not in self._animation_memory_cache:
                        logger.debug(f"Pre-caching big {animation_type} animation for level {current_level}, speed {current_speed_level}")
                        self.get_animation_with_speed_and_power_big(current_level, current_speed_level, current_power)

                except Exception as cache_error:
                    logger.error(f"Failed to pre-cache {animation_type} animation: {cache_error}")

            logger.info(f"Initial cache warmup complete - cached animations for speed level {current_speed_level}")

        except Exception as e:
            logger.error(f"Error during initial cache warmup: {e}")

    async def _async_recache_current_animations(self, reason: str = "event_trigger"):
        """Async wrapper for immediate animation re-caching after events."""
        try:
            logger.debug(f"Starting async animation re-caching: {reason}")
            await self.perform_initial_cache_warmup()
            logger.info(f"Async animation re-caching completed: {reason}")
        except Exception as e:
            logger.error(f"Error during async animation re-caching: {e}")

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