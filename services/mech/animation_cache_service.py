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
        # V2.0 Cache-Only Architecture: Use correct path for Docker vs Local
        import os
        if os.path.exists("/app/cached_animations"):
            # Docker environment - V2.0 cache-only (no PNG sources)
            self.assets_dir = None  # V2.0: PNG sources not available in container
            self.cache_dir = Path("/app/cached_animations")
        else:
            # Local development environment
            self.assets_dir = Path("/Volumes/appdata/dockerdiscordcontrol/assets/mech_evolutions")
            self.cache_dir = Path("/Volumes/appdata/dockerdiscordcontrol/cached_animations")

        # Create cache directory
        self.cache_dir.mkdir(exist_ok=True)

        # Cache for walk scale factors to ensure rest mechs use identical scaling
        self._walk_scale_factors = {}

        # ULTRA-FOCUSED: Only 2 cache entries for 100% hot path coverage
        self._focused_cache = {
            'current_small': None,  # Small animation for current level+speed (Discord Overview)
            'current_big': None     # Big animation for current level+speed (Discord Expanded + Web UI)
        }

        # Current state tracking for cache validity
        self._current_level = None
        self._current_speed = None
        self._current_power = None
        self._current_animation_type = None  # 'walk' or 'rest'

        # Power change threshold for focused cache invalidation
        self._significant_power_change_threshold = 1.0  # Only invalidate on power changes >= $1

        # SERVICE FIRST: Event-based cache invalidation setup
        self._setup_event_listeners()

        logger.info(f"Animation Cache Service initialized")
        logger.info(f"Assets dir: {self.assets_dir}")
        logger.info(f"Cache dir: {self.cache_dir}")
        logger.info(f"Base animation speed: 8 FPS (125ms per frame)")
        logger.info(f"Ultra-focused cache: 2 entries only (current_small + current_big for hot path)")

    def _quantize_speed(self, speed_level: float) -> float:
        """
        MEMORY OPTIMIZATION: Quantize speed to 20 buckets instead of 102 individual values.
        Reduces cache entries by 80% with minimal quality impact (5% granularity vs 1%).

        Args:
            speed_level: Original speed level (0-101)

        Returns:
            Quantized speed level (0, 5, 10, 15, ..., 100)
        """
        # Special case: preserve exact 0 and 101 for rest/transcendent animations
        if speed_level <= 0:
            return 0.0
        if speed_level >= 101:
            return 101.0

        # Quantize to 5% buckets: 5, 10, 15, 20, ..., 100
        quantized = round(speed_level / 5.0) * 5.0
        return max(5.0, min(100.0, quantized))

    def _update_current_state(self, level: int, speed: float, power: float):
        """Update current state tracking for cache validity."""
        animation_type = "rest" if power <= 0.0 and level <= 10 else "walk"

        # Check if state changed
        state_changed = (
            self._current_level != level or
            self._current_speed != speed or
            self._current_power != power or
            self._current_animation_type != animation_type
        )

        if state_changed:
            logger.debug(f"State change detected: L{level} S{speed:.1f} P{power:.2f} {animation_type}")
            # Clear cache on state change
            self._focused_cache['current_small'] = None
            self._focused_cache['current_big'] = None

            # Update tracked state
            self._current_level = level
            self._current_speed = speed
            self._current_power = power
            self._current_animation_type = animation_type

    def _is_current_state(self, level: int, speed: float, power: float) -> bool:
        """Check if requested animation matches current cached state."""
        animation_type = "rest" if power <= 0.0 and level <= 10 else "walk"
        return (
            self._current_level == level and
            self._current_speed == speed and
            self._current_power == power and
            self._current_animation_type == animation_type
        )

    def _store_in_focused_cache(self, resolution: str, animation_bytes: bytes):
        """Store animation in focused cache (only for current state)."""
        cache_key = 'current_small' if resolution == 'small' else 'current_big'
        self._focused_cache[cache_key] = {
            'animation_bytes': animation_bytes,
            'cached_at': time.time(),
            'size_bytes': len(animation_bytes)
        }
        logger.debug(f"Focused cache stored: {cache_key} ({len(animation_bytes):,} bytes)")

    def _get_from_focused_cache(self, resolution: str) -> Optional[bytes]:
        """Get animation from focused cache."""
        cache_key = 'current_small' if resolution == 'small' else 'current_big'
        entry = self._focused_cache.get(cache_key)
        if entry:
            return entry['animation_bytes']
        return None

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
        except (OSError, ValueError, AttributeError, KeyError) as e:
            # Fallback to direct evolution level if folder lookup fails
            logger.debug(f"Folder lookup failed, using fallback path: {e}")
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

        except (IOError, OSError) as e:
            # File I/O errors (cannot read PNG files)
            logger.error(f"File error calculating walk scale factor for level {evolution_level}: {e}", exc_info=True)
            self._walk_scale_factors[evolution_level] = 1.0
            return 1.0
        except (ValueError, AttributeError, TypeError) as e:
            # Image processing errors (getbbox, crop operations)
            logger.error(f"Image processing error calculating walk scale factor for level {evolution_level}: {e}", exc_info=True)
            self._walk_scale_factors[evolution_level] = 1.0
            return 1.0

    def _get_actual_mech_folder_no_cache_check(self, evolution_level: int) -> Path:
        """Original logic for getting mech folder without cache check"""
        # V2.0 Cache-Only: PNG sources not available in container
        if self.assets_dir is None:
            raise FileNotFoundError("V2.0 Cache-Only: PNG sources not available, use cached animations only")

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

        # ========================================================================
        # FIXED: Mech 10 Big Walk Animation - Using Native High-Quality PNGs
        # ========================================================================
        # SOLUTION APPLIED (Nov 16, 2024):
        #   - Received corrected 412x412 big PNGs from Fiverr artist
        #   - Automatically aligned Frame 1 (-9px) and Frame 3 (-12px)
        #   - Alignment quality improved: 21px → 18px variation
        #   - Relative quality: 3.2% (better than small: 4.2%)
        #   - No upscaling needed - using native high-quality big PNGs
        # ========================================================================
        actual_resolution = resolution
        upscale_factor = None

        # Use the same folder detection logic as cache path
        mech_folder = self._get_actual_mech_folder(evolution_level, actual_resolution)
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
                    # Determine if we're processing big or small resolution
                    is_big_resolution = resolution == "big" if resolution else False

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
                    elif evolution_level == 10:
                        # TEST: Mech 10 NO CROPPING for big resolution (testing full frame)
                        frame_width, frame_height = frame.size
                        if is_big_resolution:
                            # TEST: No cropping for big version - use full 412x412 frame
                            logger.info(f"🚨 PRE-CROP BYPASS: Mech 10 walk (big) - NO CROPPING - using full frame {frame.size}")
                        else:
                            # Small version (128x128): Keep original crop values
                            top_crop = 12
                            bottom_crop = 21
                            frame = frame.crop((0, top_crop, frame_width, frame_height - bottom_crop))
                            logger.debug(f"Mech 10 walk pre-crop (small): removed {top_crop}px from top, {bottom_crop}px from bottom, new size: {frame.size}")

                elif animation_type == "rest":
                    # REST pre-cropping - COMPLETE ORIGINAL VALUES for small mechs, proportional for big mechs
                    frame_width, frame_height = frame.size

                    # Determine if we're processing big or small resolution
                    is_big_resolution = resolution == "big" if resolution else False

                    # Uniform REST pre-cropping: All offline mechs use 60px from top (verified correct)
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
                            # Big REST: Uniform 116px cropping for ALL levels (manually verified, from commit 448b0b5 - matches cache files)
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
                # Special handling for Level 4 rest small: use custom bbox to detect weak feet pixels
                if evolution_level == 4 and animation_type == "rest" and resolution == "small":
                    bbox = self._get_bbox_with_alpha_threshold(frame, alpha_threshold=10)
                    logger.debug(f"Level 4 rest small: Using custom bbox with alpha_threshold=10")
                else:
                    # Standard bbox detection for all other animations
                    bbox = frame.getbbox()

                if bbox:
                    x1, y1, x2, y2 = bbox
                    min_x = min(min_x, x1)
                    min_y = min(min_y, y1)
                    max_x = max(max_x, x2)
                    max_y = max(max_y, y2)

        # TEST: Mech 10 Big Walk - NO unified cropping (skip smart crop entirely)
        if evolution_level == 10 and resolution == "big" and animation_type == "walk":
            logger.info(f"🚨 BYPASS ACTIVE: Mech 10 Big Walk - SKIPPING unified smart crop - using full 412x412 frames")
            logger.info(f"🚨 BYPASS: evolution_level={evolution_level}, resolution={resolution}, animation_type={animation_type}")
            logger.info(f"🚨 BYPASS: Frame count={len(all_frames)}, First frame size={all_frames[0].size if all_frames else 'NO FRAMES'}")
            frames = all_frames  # Use frames as-is without any unified cropping
            crop_width, crop_height = all_frames[0].size if all_frames else (412, 412)
            logger.info(f"🚨 BYPASS: Final dimensions will be {crop_width}x{crop_height}")
        else:
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

    def _get_bbox_with_alpha_threshold(self, frame: Image.Image, alpha_threshold: int = 10) -> tuple:
        """
        Get bounding box with custom alpha threshold to detect weak/semi-transparent pixels (like feet).
        Standard getbbox() only detects fully opaque pixels (alpha=255), this detects alpha>=threshold.
        """
        if frame.mode != 'RGBA':
            # Fallback to standard getbbox for non-RGBA images
            return frame.getbbox()

        # Pure PIL approach without numpy
        width, height = frame.size
        min_x, min_y = width, height
        max_x, max_y = -1, -1

        # Scan each pixel for alpha >= threshold
        for y in range(height):
            for x in range(width):
                pixel = frame.getpixel((x, y))
                alpha = pixel[3] if len(pixel) >= 4 else 255  # Get alpha channel

                if alpha >= alpha_threshold:
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        # Check if any visible pixels were found
        if max_x == -1 or max_y == -1:
            return None

        # Return as (left, top, right, bottom) - same format as getbbox()
        return (min_x, min_y, max_x + 1, max_y + 1)

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

        except (IOError, OSError) as e:
            # File I/O errors (reading PNG frames or writing cache file)
            logger.error(f"File I/O error pre-generating {animation_type} animation for evolution {evolution_level} ({resolution}): {e}", exc_info=True)
        except (ValueError, TypeError, AttributeError) as e:
            # Image processing errors (frame loading, WebP creation)
            logger.error(f"Image processing error pre-generating {animation_type} animation for evolution {evolution_level} ({resolution}): {e}", exc_info=True)

    def pre_generate_all_animations(self):
        """Pre-generate walk animations for all available evolution levels"""
        # V2.0 Cache-Only: Skip pre-generation if PNG sources not available
        if self.assets_dir is None:
            logger.info("V2.0 Cache-Only: Using pre-built cached animations, skipping PNG-based pre-generation")
            return

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
        # V2.0 Cache-Only: Skip pre-generation if PNG sources not available
        if self.assets_dir is None:
            logger.info("V2.0 Cache-Only: Using pre-built cached rest animations, skipping PNG-based pre-generation")
            return

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
        # V2.0 Cache-Only: Skip pre-generation if PNG sources not available
        if self.assets_dir is None:
            logger.info("V2.0 Cache-Only: Using pre-built cached big animations, skipping PNG-based pre-generation")
            return

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
        Get big mech animation with adjusted speed, automatically selecting rest vs walk based on power.
        ULTRA-FOCUSED: Only caches current state for hot path (Discord Expanded + Web UI).
        """
        # Determine animation type based on power
        animation_type = "rest" if power_level <= 0.0 and evolution_level <= 10 else "walk"

        # Update current state tracking
        self._update_current_state(evolution_level, speed_level, power_level)

        # HOT PATH: Check focused cache for current state
        if self._is_current_state(evolution_level, speed_level, power_level):
            cached_animation = self._get_from_focused_cache('big')
            if cached_animation:
                logger.debug(f"🚀 FOCUSED CACHE HIT: big animation L{evolution_level} S{speed_level:.1f} P{power_level:.2f}")
                return cached_animation

        # Get cached big animation from file
        cache_path = self.get_cached_animation_path(evolution_level, animation_type, "big")

        if cache_path.exists():
            # Load obfuscated data and deobfuscate
            with open(cache_path, 'rb') as f:
                obfuscated_data = f.read()

            animation_data = self._deobfuscate_data(obfuscated_data)

            # For REST animations: Use constant speed (no adjustment)
            if animation_type == "rest":
                logger.debug(f"Using constant speed for big REST animation (power=0): evolution {evolution_level}")
                # Store in focused cache for current state
                if self._is_current_state(evolution_level, speed_level, power_level):
                    self._store_in_focused_cache('big', animation_data)
                return animation_data  # Return cached version at base 8 FPS speed

            # For WALK animations: Apply speed adjustment based on power level
            # Calculate speed adjustment - 8 FPS base (125ms) with 80%-120% range
            base_duration = 125  # Match cached animation: 8 FPS = 125ms per frame
            speed_factor = 0.8 + (speed_level / 100.0) * 0.4  # 80% to 120% range
            speed_factor = max(0.8, min(1.2, speed_factor))  # Clamp to safe range
            new_duration = max(50, int(base_duration / speed_factor))  # Min 50ms for readability

            # If speed is exactly 100% (speed_level = 50), return cached version as-is
            if abs(speed_level - 50.0) < 5.0:
                logger.debug(f"Using cached big {animation_type} animation at 100% speed for evolution {evolution_level}")
                # Store in focused cache for current state
                if self._is_current_state(evolution_level, speed_level, power_level):
                    self._store_in_focused_cache('big', animation_data)
                return animation_data

            # Otherwise, adjust speed by re-encoding with new duration
            logger.debug(f"Adjusting big {animation_type} speed for evolution {evolution_level}: {speed_level} → {new_duration}ms/frame")

            # PERFORMANCE: Check disk cache for speed-adjusted big animations
            # Round speed to nearest 10 to reduce cache variations (e.g., 95-100 → 100)
            speed_rounded = int(round(speed_level / 10.0) * 10)
            speed_cache_filename = f"big_{animation_type}_L{evolution_level}_S{speed_rounded}.webp"
            speed_cache_path = self.cache_dir / speed_cache_filename

            # Try to load from speed-adjusted cache
            if speed_cache_path.exists():
                try:
                    with open(speed_cache_path, 'rb') as f:
                        cached_speed_data = f.read()
                    logger.debug(f"🚀 SPEED CACHE HIT: Loaded big {animation_type} L{evolution_level} S{speed_rounded} from disk ({len(cached_speed_data)} bytes)")
                    # Store in focused cache for ultra-fast access next time
                    if self._is_current_state(evolution_level, speed_level, power_level):
                        self._store_in_focused_cache('big', cached_speed_data)
                    return cached_speed_data
                except (IOError, OSError) as e:
                    logger.warning(f"Failed to load speed cache {speed_cache_path}: {e}")
                    # Continue to re-encode below

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
            except (IOError, OSError, ValueError, TypeError) as e:
                # Image parsing errors (PIL Image.open, seek operations)
                logger.error(f"Failed to parse cached big {animation_type} animation: {e}", exc_info=True)
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

                # PERFORMANCE: Save speed-adjusted animation to disk cache for future reuse
                try:
                    with open(speed_cache_path, 'wb') as f:
                        f.write(adjusted_data)
                    logger.info(f"💾 SPEED CACHE SAVED: big {animation_type} L{evolution_level} S{speed_rounded} → {speed_cache_path} ({len(adjusted_data)} bytes)")
                except (IOError, OSError) as e:
                    logger.warning(f"Failed to save speed cache to {speed_cache_path}: {e}")

                # Store speed-adjusted animation in focused cache for current state
                if self._is_current_state(evolution_level, speed_level, power_level):
                    self._store_in_focused_cache('big', adjusted_data)
                logger.debug(f"Speed-adjusted big {animation_type} animation: {len(adjusted_data)} bytes")
                return adjusted_data

            except (IOError, OSError, ValueError, TypeError, AttributeError) as e:
                # WebP encoding errors (PIL save operation)
                logger.error(f"Failed to adjust big {animation_type} animation speed: {e}", exc_info=True)
                # Store original data in focused cache as fallback
                if self._is_current_state(evolution_level, speed_level, power_level):
                    self._store_in_focused_cache('big', animation_data)
                return animation_data  # Return original if adjustment fails

        else:
            logger.error(f"Big {animation_type} animation for evolution {evolution_level} not found in cache: {cache_path}")
            # Fallback to generating on-demand (not recommended for production)
            frames = self._load_and_process_frames(evolution_level, animation_type, "big")
            data = self._create_unified_webp(frames)
            logger.warning(f"Generated big {animation_type} animation on-demand for evolution {evolution_level}: {len(data)} bytes")

            # BUGFIX: Store on-demand generated animation in BOTH focused cache AND file cache
            # This prevents the "not found in cache" error on subsequent startups
            try:
                # Save to file cache (obfuscated)
                obfuscated_data = self._obfuscate_data(data)
                with open(cache_path, 'wb') as f:
                    f.write(obfuscated_data)
                logger.debug(f"Saved on-demand big {animation_type} animation to file cache: {cache_path}")
            except (IOError, OSError) as save_error:
                # File I/O errors (writing cache file)
                logger.error(f"Failed to save on-demand big animation to file: {save_error}", exc_info=True)

            # Store in focused cache for current state
            if self._is_current_state(evolution_level, speed_level, power_level):
                self._store_in_focused_cache('big', data)
            return data

    def get_animation_with_speed_and_power(self, evolution_level: int, speed_level: float, power_level: float = 1.0) -> bytes:
        """
        Get animation with adjusted speed, automatically selecting rest vs walk based on power.
        ULTRA-FOCUSED: Only caches current state for hot path (Discord Overview).

        Args:
            evolution_level: Mech evolution level
            speed_level: Desired speed (0-101)
            power_level: Current power level (0.0 = offline/rest, >0 = walk)

        Returns:
            Animation bytes with adjusted speed
        """
        # Determine animation type based on power
        animation_type = "rest" if power_level <= 0.0 and evolution_level <= 10 else "walk"
        logger.debug(f"Using {animation_type.upper()} animation for evolution {evolution_level} (power: {power_level})")

        # Update current state tracking
        self._update_current_state(evolution_level, speed_level, power_level)

        # HOT PATH: Check focused cache for current state
        if self._is_current_state(evolution_level, speed_level, power_level):
            cached_animation = self._get_from_focused_cache('small')
            if cached_animation:
                logger.debug(f"🚀 FOCUSED CACHE HIT: small animation L{evolution_level} S{speed_level:.1f} P{power_level:.2f}")
                return cached_animation

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
            # Store in focused cache for current state
            if self._is_current_state(evolution_level, speed_level, power_level):
                self._store_in_focused_cache('small', animation_data)
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
            # Store in focused cache for current state
            if self._is_current_state(evolution_level, speed_level, power_level):
                self._store_in_focused_cache('small', animation_data)
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
        except (IOError, OSError, ValueError, TypeError) as e:
            # Image parsing errors (PIL Image.open, seek operations)
            logger.error(f"Failed to parse cached {animation_type} animation: {e}", exc_info=True)
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
            # Store in focused cache for current state
            if self._is_current_state(evolution_level, speed_level, power_level):
                self._store_in_focused_cache('small', adjusted_data)
            return adjusted_data

        except (IOError, OSError, ValueError, TypeError, AttributeError) as e:
            # WebP encoding errors (PIL save operation)
            logger.error(f"Failed to adjust {animation_type} animation speed: {e}", exc_info=True)
            # Store original data in focused cache as fallback
            if self._is_current_state(evolution_level, speed_level, power_level):
                self._store_in_focused_cache('small', animation_data)
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
                except (IOError, OSError, PermissionError) as e:
                    # File deletion errors (permission denied, file in use, etc.)
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
                except (IOError, OSError, PermissionError) as e:
                    # File deletion errors (permission denied, file in use, etc.)
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
        except (IOError, OSError, ValueError, TypeError) as e:
            # Image parsing errors (PIL Image.open, seek operations)
            logger.error(f"Failed to parse cached animation: {e}", exc_info=True)
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

        except (IOError, OSError, ValueError, TypeError, AttributeError) as e:
            # WebP encoding errors (PIL save operation)
            logger.error(f"Failed to adjust animation speed: {e}", exc_info=True)
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

        except (IOError, OSError) as e:
            # File I/O errors (reading cache files)
            logger.error(f"File I/O error in Service First animation generation: {e}", exc_info=True)
            return MechAnimationResult(
                success=False,
                error_message=f"File I/O error: {e}",
                generation_time_ms=(time.time() - start_time) * 1000
            )
        except (ValueError, TypeError, AttributeError) as e:
            # Image processing or data errors
            logger.error(f"Data error in Service First animation generation: {e}", exc_info=True)
            return MechAnimationResult(
                success=False,
                error_message=f"Data processing error: {e}",
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

        except (ImportError, AttributeError, RuntimeError) as e:
            # Event manager setup errors (import failure, manager not available, etc.)
            logger.error(f"Failed to setup event listeners: {e}", exc_info=True)

    def _handle_donation_event(self, event_data):
        """Handle donation completion events for cache invalidation and immediate re-caching."""
        try:
            # Extract relevant data from event
            event_info = event_data.data
            reason = f"Donation completed: ${event_info.get('amount', 'unknown')}"

            # Invalidate cache since power/level may have changed
            # For event-driven invalidation, only clear memory cache to allow fast re-caching
            self.invalidate_memory_cache_only(reason)

            logger.info(f"Animation cache invalidated due to donation event: {reason}")

            # PROACTIVE RE-CACHING: Immediately cache new animations for current state
            # This prevents 2-second delays when user clicks "Mech Details" after donations
            try:
                import asyncio

                # Check if there's a running event loop
                try:
                    loop = asyncio.get_running_loop()
                    # Event loop is running - use async task
                    asyncio.create_task(self._async_recache_current_animations(reason="donation_event"))
                    logger.info("Immediate animation re-caching scheduled after donation event (async)")
                except RuntimeError:
                    # No event loop running - use synchronous re-caching
                    logger.info("No event loop running - performing synchronous re-caching after donation event")
                    self._sync_recache_current_animations(reason="donation_event")

            except (RuntimeError, AttributeError) as recache_error:
                # Re-caching scheduling errors (asyncio errors, etc.)
                logger.warning(f"Could not schedule immediate re-caching: {recache_error}")

        except (KeyError, ValueError, AttributeError, TypeError) as e:
            # Event data parsing errors
            logger.error(f"Error handling donation event: {e}", exc_info=True)

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
                # For event-driven invalidation, only clear memory cache to allow fast re-caching
                self.invalidate_memory_cache_only(reason)
                logger.info(f"Animation cache invalidated due to state change: {reason}")

                # PROACTIVE RE-CACHING: Schedule immediate animation refresh
                try:
                    import asyncio

                    # Check if there's a running event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # Event loop is running - use async task
                        asyncio.create_task(self._async_recache_current_animations(reason="state_change_event"))
                        logger.info("Immediate animation re-caching scheduled after state change (async)")
                    except RuntimeError:
                        # No event loop running - use synchronous re-caching
                        logger.info("No event loop running - performing synchronous re-caching after state change")
                        self._sync_recache_current_animations(reason="state_change_event")

                except (RuntimeError, AttributeError) as recache_error:
                    # Re-caching scheduling errors (asyncio errors, etc.)
                    logger.warning(f"Could not schedule re-caching after state change: {recache_error}")
            else:
                logger.debug(f"Minor power change ignored: {old_power:.2f} → {new_power:.2f}")

        except (KeyError, ValueError, AttributeError, TypeError) as e:
            # Event data parsing errors
            logger.error(f"Error handling state change event: {e}", exc_info=True)

    def invalidate_memory_cache_only(self, reason: str = "Event-driven invalidation"):
        """Invalidate only focused cache, keeping file cache for fast re-caching."""
        cache_count = 0
        if self._focused_cache['current_small'] is not None:
            self._focused_cache['current_small'] = None
            cache_count += 1
        if self._focused_cache['current_big'] is not None:
            self._focused_cache['current_big'] = None
            cache_count += 1
        logger.info(f"Focused cache invalidated: {cache_count} entries cleared ({reason})")

    def invalidate_animation_cache(self, reason: str = "Manual invalidation"):
        """Manually invalidate the entire animation cache (for donation events or system updates)."""
        # Clear focused cache
        cache_count = 0
        if self._focused_cache['current_small'] is not None:
            self._focused_cache['current_small'] = None
            cache_count += 1
        if self._focused_cache['current_big'] is not None:
            self._focused_cache['current_big'] = None
            cache_count += 1

        # Also clear file caches (big animations) to ensure consistency
        file_count = 0
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
                file_count += 1
            except (IOError, OSError, PermissionError) as e:
                # File deletion errors (permission denied, file in use, etc.)
                logger.warning(f"Could not remove cache file {cache_file}: {e}")

        logger.info(f"Animation cache invalidated: {cache_count} focused entries + {file_count} file caches cleared ({reason})")

    def get_cache_status(self) -> dict:
        """Get detailed cache status for monitoring and debugging with focused cache info."""
        total_memory = 0
        total_entries = 0
        entries_by_type = {'small': {'count': 0, 'total_size_mb': 0}, 'big': {'count': 0, 'total_size_mb': 0}}
        entries_detail = {}

        # Check focused cache entries
        for cache_key, entry in self._focused_cache.items():
            if entry is not None:
                cache_type = 'small' if cache_key == 'current_small' else 'big'
                entry_size = entry.get('size_bytes', 0)
                total_memory += entry_size
                total_entries += 1

                entries_by_type[cache_type]['count'] += 1
                entries_by_type[cache_type]['total_size_mb'] += round(entry_size / (1024 * 1024), 2)

                # Detailed entry info
                age = time.time() - entry.get('cached_at', 0)
                entries_detail[cache_key] = {
                    'type': cache_type,
                    'size_bytes': entry_size,
                    'size_mb': round(entry_size / (1024 * 1024), 2),
                    'age_seconds': round(age, 1),
                    'current_state': True  # Always true for focused cache
                }

        cache_stats = {
            'cache_type': 'ultra_focused',
            'total_entries': total_entries,
            'max_entries': 2,  # Ultra-focused: only 2 entries max
            'memory_usage_bytes': total_memory,
            'memory_usage_mb': round(total_memory / (1024 * 1024), 2),
            'entries_by_type': entries_by_type,
            'entries_detail': entries_detail,
            'current_state': {
                'level': self._current_level,
                'speed': self._current_speed,
                'power': self._current_power,
                'animation_type': self._current_animation_type
            }
        }

        return cache_stats

    # ========================================================================
    # INITIAL CACHE WARMUP (used for container startup and events)
    # ========================================================================

    async def perform_initial_cache_warmup(self):
        """Perform initial animation cache warmup on container startup."""
        try:
            logger.info("Performing initial animation cache warmup...")

            # Get current mech status from MechDataStore (Single Point of Truth)
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest
            from services.mech.speed_levels import get_combined_mech_status

            data_store = get_mech_data_store()
            data_request = MechDataRequest(include_decimals=True)
            mech_result = data_store.get_comprehensive_data(data_request)

            if not mech_result.success:
                logger.warning("Could not get mech status for warmup - skipping")
                return

            current_level = mech_result.current_level
            current_power = mech_result.current_power

            # Calculate current speed level
            # SPECIAL CASE: Level 11 is maximum level - always use Speed Level 100 (same logic as MechWebService)
            if current_level >= 11:
                current_speed_level = 100  # Level 11 always has maximum speed (divine speed)
                logger.debug(f"Level 11 cache warmup using maximum speed level: {current_speed_level}")
            else:
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
                    # ULTRA-FOCUSED: Pre-cache both small and big animations for current state
                    logger.debug(f"Pre-caching small {animation_type} animation for level {current_level}, speed {current_speed_level}")
                    self.get_animation_with_speed_and_power(current_level, current_speed_level, current_power)

                    logger.debug(f"Pre-caching big {animation_type} animation for level {current_level}, speed {current_speed_level}")
                    self.get_animation_with_speed_and_power_big(current_level, current_speed_level, current_power)

                except (IOError, OSError, ValueError, TypeError, AttributeError) as cache_error:
                    # Animation caching errors (file I/O, image processing)
                    logger.error(f"Failed to pre-cache {animation_type} animation: {cache_error}", exc_info=True)

            logger.info(f"Initial cache warmup complete - cached animations for speed level {current_speed_level}")

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service initialization errors (data store unavailable, etc.)
            logger.error(f"Error during initial cache warmup: {e}", exc_info=True)

    def _perform_sync_cache_warmup(self):
        """Perform synchronous animation cache warmup (fallback when no event loop)."""
        try:
            logger.info("Performing sync animation cache warmup...")

            # Get current mech status from MechDataStore (Single Point of Truth)
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest
            from services.mech.speed_levels import get_combined_mech_status

            data_store = get_mech_data_store()
            data_request = MechDataRequest(include_decimals=True)
            mech_result = data_store.get_comprehensive_data(data_request)

            if not mech_result.success:
                logger.warning("Could not get mech status for sync warmup - skipping")
                return

            current_level = mech_result.current_level
            current_power = mech_result.current_power

            # Calculate current speed level
            # SPECIAL CASE: Level 11 is maximum level - always use Speed Level 100 (same logic as MechWebService)
            if current_level >= 11:
                current_speed_level = 100  # Level 11 always has maximum speed (divine speed)
                logger.debug(f"Level 11 sync cache warmup using maximum speed level: {current_speed_level}")
            else:
                speed_status = get_combined_mech_status(current_power)
                current_speed_level = speed_status['speed']['level']

            logger.info(f"Sync cache warmup: Level {current_level}, Power {current_power:.2f}, Speed {current_speed_level}")

            # Determine which animation types to cache based on level
            animation_types = ["walk"]  # All levels have walk animations
            if current_level <= 10:
                animation_types.append("rest")  # Only levels 1-10 have rest animations

            logger.debug(f"Caching animation types for Level {current_level}: {animation_types}")

            for animation_type in animation_types:
                try:
                    # ULTRA-FOCUSED: Pre-cache both small and big animations for current state
                    logger.debug(f"Pre-caching small {animation_type} animation for level {current_level}, speed {current_speed_level}")
                    self.get_animation_with_speed_and_power(current_level, current_speed_level, current_power)

                    logger.debug(f"Pre-caching big {animation_type} animation for level {current_level}, speed {current_speed_level}")
                    self.get_animation_with_speed_and_power_big(current_level, current_speed_level, current_power)

                except (IOError, OSError, ValueError, TypeError, AttributeError) as cache_error:
                    # Animation caching errors (file I/O, image processing)
                    logger.error(f"Failed to pre-cache {animation_type} animation: {cache_error}", exc_info=True)

            logger.info(f"Sync cache warmup complete - cached animations for speed level {current_speed_level}")

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service initialization errors (data store unavailable, etc.)
            logger.error(f"Error during sync cache warmup: {e}", exc_info=True)

    def _sync_recache_current_animations(self, reason: str = "event_trigger"):
        """SERVICE FIRST: Synchronous animation re-caching via MechWebService (fallback when no event loop)."""
        try:
            logger.debug(f"Starting SERVICE FIRST sync animation re-caching: {reason}")
            self._perform_service_first_sync_warmup()
            logger.info(f"SERVICE FIRST sync animation re-caching completed: {reason}")
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service call errors (web service unavailable, sync errors, etc.)
            logger.error(f"Error during SERVICE FIRST sync animation re-caching: {e}", exc_info=True)

    async def _async_recache_current_animations(self, reason: str = "event_trigger"):
        """SERVICE FIRST: Async animation re-caching via MechWebService."""
        try:
            logger.debug(f"Starting SERVICE FIRST async animation re-caching: {reason}")
            await self._perform_service_first_async_warmup()
            logger.info(f"SERVICE FIRST async animation re-caching completed: {reason}")
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service call errors (web service unavailable, async errors, etc.)
            logger.error(f"Error during SERVICE FIRST async animation re-caching: {e}", exc_info=True)

    def _perform_service_first_sync_warmup(self):
        """SERVICE FIRST: Synchronous animation warmup using MechWebService."""
        try:
            # SERVICE FIRST: Use MechWebService for animation requests
            from services.web.mech_web_service import get_mech_web_service, MechAnimationRequest
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest

            web_service = get_mech_web_service()
            data_store = get_mech_data_store()

            # Get current mech status via MechDataStore (Single Point of Truth)
            data_request = MechDataRequest(include_decimals=True)
            mech_result = data_store.get_comprehensive_data(data_request)

            if not mech_result.success:
                logger.warning("SERVICE FIRST sync warmup: Could not get mech status - skipping")
                return

            current_power = mech_result.current_power
            logger.info(f"SERVICE FIRST sync warmup: Power {current_power:.2f}")

            # Cache both small and big animations via service requests
            for resolution in ["small", "big"]:
                try:
                    request = MechAnimationRequest(
                        force_power=current_power,
                        resolution=resolution
                    )
                    result = web_service.get_live_animation(request)

                    if result.success:
                        logger.debug(f"SERVICE FIRST: Cached {resolution} animation ({len(result.animation_bytes)} bytes)")
                    else:
                        logger.warning(f"SERVICE FIRST: Failed to cache {resolution} animation: {result.error}")

                except (ValueError, TypeError, AttributeError) as e:
                    # Animation request/processing errors
                    logger.error(f"SERVICE FIRST sync warmup error for {resolution}: {e}", exc_info=True)

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service initialization errors (web service unavailable, data store errors, etc.)
            logger.error(f"SERVICE FIRST sync warmup failed: {e}", exc_info=True)

    async def _perform_service_first_async_warmup(self):
        """SERVICE FIRST: Async animation warmup using MechWebService."""
        try:
            # SERVICE FIRST: Use MechWebService for animation requests
            from services.web.mech_web_service import get_mech_web_service, MechAnimationRequest
            from services.mech.mech_data_store import get_mech_data_store, MechDataRequest

            web_service = get_mech_web_service()
            data_store = get_mech_data_store()

            # Get current mech status via MechDataStore (Single Point of Truth)
            data_request = MechDataRequest(include_decimals=True)
            mech_result = data_store.get_comprehensive_data(data_request)

            if not mech_result.success:
                logger.warning("SERVICE FIRST async warmup: Could not get mech status - skipping")
                return

            current_power = mech_result.current_power
            logger.info(f"SERVICE FIRST async warmup: Power {current_power:.2f}")

            # Cache both small and big animations via service requests (async-compatible)
            for resolution in ["small", "big"]:
                try:
                    request = MechAnimationRequest(
                        force_power=current_power,
                        resolution=resolution
                    )
                    # Note: MechWebService.get_live_animation is sync, but we can call it from async context
                    result = web_service.get_live_animation(request)

                    if result.success:
                        logger.debug(f"SERVICE FIRST: Cached {resolution} animation ({len(result.animation_bytes)} bytes)")
                    else:
                        logger.warning(f"SERVICE FIRST: Failed to cache {resolution} animation: {result.error}")

                except (ValueError, TypeError, AttributeError) as e:
                    # Animation request/processing errors
                    logger.error(f"SERVICE FIRST async warmup error for {resolution}: {e}", exc_info=True)

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service initialization errors (web service unavailable, data store errors, etc.)
            logger.error(f"SERVICE FIRST async warmup failed: {e}", exc_info=True)

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
            # UNIFIED SPEED CALCULATION: Use same logic as MechWebService (fully unified!)
            if evolution_level >= 11:
                speed_level = 100  # Level 11 always has maximum speed (divine speed)
                logger.debug(f"Status Overview: Level 11 using maximum speed level: {speed_level}")
            else:
                # Use actual power-based speed calculation (same as MechWebService)
                from services.mech.speed_levels import get_combined_mech_status
                speed_status = get_combined_mech_status(power_level)
                speed_level = speed_status['speed']['level']
                logger.debug(f"Status Overview: Level {evolution_level} using calculated speed level: {speed_level} (power: {power_level})")

            normal_animation_bytes = self.get_animation_with_speed_and_power(evolution_level, speed_level, power_level)

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

        except (IOError, OSError) as e:
            # File I/O errors (reading cache files)
            logger.error(f"File I/O error creating status overview animation: {e}", exc_info=True)
            # Fallback: create a simple transparent canvas
            try:
                target_size = self.get_expected_canvas_size(evolution_level, "status_overview")
                fallback_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                buffer = BytesIO()
                fallback_img.save(buffer, format='WebP', lossless=True, quality=100, dpi=(300, 300))
                return buffer.getvalue()
            except (IOError, OSError, ValueError, TypeError):
                # Ultimate fallback (fallback creation failed)
                return b''
        except (ValueError, TypeError, AttributeError) as e:
            # Image processing errors (PIL operations)
            logger.error(f"Image processing error creating status overview animation: {e}", exc_info=True)
            # Fallback: create a simple transparent canvas
            try:
                target_size = self.get_expected_canvas_size(evolution_level, "status_overview")
                fallback_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                buffer = BytesIO()
                fallback_img.save(buffer, format='WebP', lossless=True, quality=100, dpi=(300, 300))
                return buffer.getvalue()
            except (IOError, OSError, ValueError, TypeError):
                # Ultimate fallback (fallback creation failed)
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

        except (IOError, OSError) as e:
            # File I/O errors (reading cache files)
            logger.error(f"File I/O error creating Discord optimized animation: {e}", exc_info=True)
            # Fallback: create a simple transparent canvas - 270px width, 50% height
            try:
                original_size = self.get_expected_canvas_size(evolution_level, "walk")
                target_size = (270, original_size[1] // 2)  # Keep 270px width, reduce height by 50%
                fallback_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                buffer = BytesIO()
                fallback_img.save(buffer, format='WebP', lossless=True, quality=100, dpi=(300, 300))
                return buffer.getvalue()
            except (IOError, OSError, ValueError, TypeError):
                # Ultimate fallback (fallback creation failed)
                return b''
        except (ValueError, TypeError, AttributeError) as e:
            # Image processing errors (PIL operations)
            logger.error(f"Image processing error creating Discord optimized animation: {e}", exc_info=True)
            # Fallback: create a simple transparent canvas - 270px width, 50% height
            try:
                original_size = self.get_expected_canvas_size(evolution_level, "walk")
                target_size = (270, original_size[1] // 2)  # Keep 270px width, reduce height by 50%
                fallback_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                buffer = BytesIO()
                fallback_img.save(buffer, format='WebP', lossless=True, quality=100, dpi=(300, 300))
                return buffer.getvalue()
            except (IOError, OSError, ValueError, TypeError):
                # Ultimate fallback (fallback creation failed)
                return b''

# Singleton instance
_animation_cache_service = None

def get_animation_cache_service() -> AnimationCacheService:
    """Get or create the singleton animation cache service instance"""
    global _animation_cache_service
    if _animation_cache_service is None:
        _animation_cache_service = AnimationCacheService()
    return _animation_cache_service