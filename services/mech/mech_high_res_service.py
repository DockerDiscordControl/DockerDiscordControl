#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech High Resolution Service                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech High Resolution Service - Handles big/small mech resolution detection and scaling.
Provides proportional smart cropping parameters for variable size ratios (2.5x-3.0x).
"""

import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class MechResolutionRequest:
    """Request for mech resolution analysis."""
    evolution_level: int
    preferred_resolution: str = "small"  # "small" or "big"


@dataclass
class MechResolutionResult:
    """Result containing mech resolution information."""
    success: bool
    error: Optional[str] = None

    # Resolution info
    available_resolution: str = "small"  # "small" or "big"
    size_ratio: Optional[float] = None   # big/small ratio (e.g., 3.0)

    # Paths
    assets_folder: Optional[Path] = None
    has_big_version: bool = False

    # Smart cropping adjustments
    cropping_adjustments: Optional[Dict[str, Any]] = None


class MechHighResService:
    """Service for managing high-resolution mech assets."""

    def __init__(self):
        self.assets_dir = Path(__file__).parent.parent.parent / "assets" / "mech_evolutions"
        self._size_ratio_cache: Dict[int, float] = {}

    def get_mech_resolution_info(self, request: MechResolutionRequest) -> MechResolutionResult:
        """
        Get resolution information for a mech level.

        Args:
            request: MechResolutionRequest with evolution level and preferred resolution

        Returns:
            MechResolutionResult with available resolution and scaling info
        """
        try:
            level = request.evolution_level
            preferred = request.preferred_resolution

            # Check if big version exists
            big_folder = self.assets_dir / f"Mech{level}" / "big"
            small_folder = self.assets_dir / f"Mech{level}" / "small"

            if not small_folder.exists():
                return MechResolutionResult(
                    success=False,
                    error=f"No assets found for Mech level {level}"
                )

            has_big = self._has_big_version(level)

            # Determine actual resolution to use
            if preferred == "big" and has_big:
                actual_resolution = "big"
                folder_path = big_folder
            else:
                actual_resolution = "small"
                folder_path = small_folder

            # Calculate size ratio if big version exists
            size_ratio = None
            if has_big:
                size_ratio = self._get_size_ratio(level)

            # Get cropping adjustments for the chosen resolution
            cropping_adjustments = self._get_cropping_adjustments(level, actual_resolution)

            return MechResolutionResult(
                success=True,
                available_resolution=actual_resolution,
                size_ratio=size_ratio,
                assets_folder=folder_path,
                has_big_version=has_big,
                cropping_adjustments=cropping_adjustments
            )

        except (IOError, OSError) as e:
            # File system errors (folder access, path operations)
            logger.error(f"File system error getting mech resolution info for level {request.evolution_level}: {e}", exc_info=True)
            return MechResolutionResult(
                success=False,
                error=f"File system error: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data processing errors (calculations, dictionary access)
            logger.error(f"Data error getting mech resolution info for level {request.evolution_level}: {e}", exc_info=True)
            return MechResolutionResult(
                success=False,
                error=f"Data processing error: {str(e)}"
            )

    def _has_big_version(self, evolution_level: int) -> bool:
        """Check if a mech level has big version available."""
        try:
            big_folder = self.assets_dir / f"Mech{evolution_level}" / "big"
            if not big_folder.exists():
                return False

            # Check for walk files
            walk_files = list(big_folder.glob(f"{evolution_level}_walk_*.png"))
            return len(walk_files) > 0

        except (IOError, OSError, PermissionError) as e:
            # File system errors (folder access, path operations, permissions)
            logger.debug(f"File system error checking big version for level {evolution_level}: {e}")
            return False
        except (ValueError, TypeError) as e:
            # Data processing errors (path operations, list operations)
            logger.debug(f"Data error checking big version for level {evolution_level}: {e}")
            return False

    def _get_size_ratio(self, evolution_level: int) -> float:
        """Get the size ratio between big and small versions."""
        if evolution_level in self._size_ratio_cache:
            return self._size_ratio_cache[evolution_level]

        try:
            small_path = self.assets_dir / f"Mech{evolution_level}" / "small" / f"{evolution_level}_walk_0001.png"
            big_path = self.assets_dir / f"Mech{evolution_level}" / "big" / f"{evolution_level}_walk_0001.png"

            if not (small_path.exists() and big_path.exists()):
                return 1.0

            with Image.open(small_path) as small_img:
                small_size = small_img.size

            with Image.open(big_path) as big_img:
                big_size = big_img.size

            # Use width ratio (assuming proportional scaling)
            ratio = big_size[0] / small_size[0]
            self._size_ratio_cache[evolution_level] = ratio

            logger.debug(f"Mech level {evolution_level} size ratio: {ratio:.2f}x")
            return ratio

        except (IOError, OSError) as e:
            # File I/O errors (image file access)
            logger.debug(f"File I/O error calculating size ratio for level {evolution_level}: {e}")
            return 1.0
        except (ValueError, TypeError, ZeroDivisionError) as e:
            # Calculation errors (PIL operations, ratio calculations)
            logger.debug(f"Calculation error calculating size ratio for level {evolution_level}: {e}")
            return 1.0

    def _get_cropping_adjustments(self, evolution_level: int, resolution: str) -> Dict[str, Any]:
        """Get smart cropping adjustments for the specified resolution."""
        # Base cropping adjustments for small mechs (REST/offline animations use uniform 60px in animation_cache_service)
        # These values are for WALK animations and canvas calculations
        small_adjustments = {
            1: {"top": 60, "bottom": 10},    # Mech 1: uniform crop
            2: {"top": 60, "bottom": 10},    # Mech 2: uniform crop
            3: {"top": 60, "bottom": 10},    # Mech 3: uniform crop
            4: {"top": 45, "bottom": 13},    # Mech 4: enhanced pre-cropping
            5: {"top": 22, "bottom": 14},    # Mech 5: custom pre-cropping
            6: {"top": 48, "bottom": 12},    # Mech 6: custom pre-cropping
            7: {"top": 60, "bottom": 10},    # Mech 7: uniform crop
            8: {"top": 60, "bottom": 10},    # Mech 8: uniform crop
            9: {"top": 60, "bottom": 10},    # Mech 9: uniform crop
            10: {"top": 60, "bottom": 10},   # Mech 10: uniform crop
        }

        base_adjustment = small_adjustments.get(evolution_level, {"top": 0, "bottom": 0})

        if resolution == "small":
            return base_adjustment

        # For big resolution, scale the adjustments proportionally
        if resolution == "big":
            ratio = self._get_size_ratio(evolution_level)
            return {
                "top": int(base_adjustment["top"] * ratio),
                "bottom": int(base_adjustment["bottom"] * ratio)
            }

        return base_adjustment

    def get_canvas_size_for_resolution(self, evolution_level: int, resolution: str, animation_type: str = "walk") -> Tuple[int, int]:
        """Get expected canvas size for the specified resolution."""
        # Base canvas sizes for small mechs (existing logic)
        small_walk_heights = {
            1: 100, 2: 100, 3: 100,  # Mech1-3: ~100px height
            4: 150, 5: 150,           # Mech4-5: ~150px height
            6: 170,                   # Mech 6: ~170px height
            7: 100, 8: 100,           # Mech 7-8: ~100px height
            9: 230,                   # Mech 9: ~230px height
            10: 250,                  # Mech 10: ~250px height
            11: 270                   # Mech 11: ~270px height
        }

        base_height = small_walk_heights.get(evolution_level, 100)

        if animation_type == "rest":
            base_height *= 2  # Rest animations are double height

        if resolution == "small":
            return (270, base_height)

        # For big resolution, scale proportionally but keep aspect ratio
        if resolution == "big":
            ratio = self._get_size_ratio(evolution_level)
            # For big mechs, we use native resolution after smart cropping
            # Don't scale the canvas, let it be the natural size
            return (int(270 * ratio), int(base_height * ratio))

        return (270, base_height)


# Global service instance
_mech_high_res_service: Optional[MechHighResService] = None


def get_mech_high_res_service() -> MechHighResService:
    """Get the global mech high resolution service instance."""
    global _mech_high_res_service
    if _mech_high_res_service is None:
        _mech_high_res_service = MechHighResService()
    return _mech_high_res_service