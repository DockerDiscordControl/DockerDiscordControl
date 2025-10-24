"""
Mech Display Cache Service - Pre-renders all mech display images for instant Discord loading.

Prevents Discord interaction timeouts by pre-generating:
1. Shadow silhouettes for locked mechs (levels 1-11)
2. Display animations for unlocked mechs (with consistent speed/power)
"""

import io
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MechDisplayCacheRequest:
    """Request to pre-render mech display images."""
    evolution_level: Optional[int] = None  # None = all levels
    force_regenerate: bool = False  # Force regeneration even if cache exists


@dataclass(frozen=True)
class MechDisplayCacheResult:
    """Result of mech display cache operation."""
    success: bool
    message: str
    levels_processed: int = 0


@dataclass(frozen=True)
class MechDisplayImageRequest:
    """Request to get a pre-rendered mech display image."""
    evolution_level: int
    image_type: str  # 'unlocked' or 'shadow'


@dataclass(frozen=True)
class MechDisplayImageResult:
    """Result containing pre-rendered mech display image."""
    success: bool
    image_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    error_message: Optional[str] = None


class MechDisplayCacheService:
    """Service for pre-rendering and serving mech display images."""

    def __init__(self):
        # Use correct path for Docker vs Local (consistent with AnimationCacheService)
        import os
        if os.path.exists("/app/cached_animations"):
            # Docker environment - V2.0 cache-only mode
            self.cache_dir = Path("/app/cached_displays")
        else:
            # Local development environment
            self.cache_dir = Path("/Volumes/appdata/dockerdiscordcontrol/cached_displays")

        # Create cache directory for display images
        self.cache_dir.mkdir(exist_ok=True)

        logger.info(f"MechDisplayCacheService initialized with cache dir: {self.cache_dir}")

    def pre_render_all_displays(self, request: MechDisplayCacheRequest) -> MechDisplayCacheResult:
        """Pre-render all mech display images for instant loading."""
        try:
            levels_to_process = [request.evolution_level] if request.evolution_level else list(range(1, 12))
            processed_count = 0
            skipped_count = 0

            logger.info(f"Pre-rendering mech display images for levels: {levels_to_process}")

            for level in levels_to_process:
                # Check if pre-rendering is needed
                shadow_needed = self._is_pre_rendering_needed(level, 'shadow', request.force_regenerate)
                unlocked_needed = self._is_pre_rendering_needed(level, 'unlocked', request.force_regenerate)

                if not shadow_needed and not unlocked_needed:
                    logger.debug(f"Level {level} display images already cached and up-to-date")
                    skipped_count += 1
                    processed_count += 1  # Count as processed since it's available
                    continue

                # Pre-render only what's needed
                shadow_success = True
                unlocked_success = True

                if shadow_needed:
                    shadow_success = self._pre_render_shadow_image(level, force=True)

                if unlocked_needed:
                    unlocked_success = self._pre_render_unlocked_image(level, force=True)

                if shadow_success and unlocked_success:
                    processed_count += 1
                    logger.debug(f"Successfully pre-rendered Level {level} display images")
                else:
                    logger.warning(f"Failed to pre-render some images for Level {level}")

            if skipped_count > 0:
                message = f"Pre-rendered display images for {processed_count}/{len(levels_to_process)} levels ({skipped_count} already cached)"
            else:
                message = f"Pre-rendered display images for {processed_count}/{len(levels_to_process)} levels"
            logger.info(message)

            return MechDisplayCacheResult(
                success=processed_count > 0,
                message=message,
                levels_processed=processed_count
            )

        except Exception as e:
            error_msg = f"Error pre-rendering mech display images: {e}"
            logger.error(error_msg, exc_info=True)
            return MechDisplayCacheResult(
                success=False,
                message=error_msg
            )

    def _is_pre_rendering_needed(self, evolution_level: int, image_type: str, force_regenerate: bool) -> bool:
        """Check if pre-rendering is needed for a specific level and image type."""
        if force_regenerate:
            return True

        # Check if cache file exists
        if image_type == 'shadow':
            cache_path = self.cache_dir / f"mech_{evolution_level}_shadow.webp"
        else:  # unlocked
            cache_path = self.cache_dir / f"mech_{evolution_level}_unlocked.webp"

        if not cache_path.exists():
            logger.debug(f"Pre-rendering needed for Level {evolution_level} {image_type}: file missing")
            return True

        # Check if source files are newer (optional optimization for future updates)
        try:
            from services.mech.animation_cache_service import get_animation_cache_service
            cache_service = get_animation_cache_service()

            # Get source PNG folder for this level
            source_folder = cache_service._get_actual_mech_folder(evolution_level)

            if source_folder.exists():
                # Find the newest PNG file
                png_files = list(source_folder.glob(f"{evolution_level}_*.png"))
                if png_files:
                    newest_png_time = max(f.stat().st_mtime for f in png_files)
                    cache_time = cache_path.stat().st_mtime

                    if newest_png_time > cache_time:
                        logger.debug(f"Pre-rendering needed for Level {evolution_level} {image_type}: source files newer")
                        return True
        except Exception as e:
            logger.debug(f"Could not check source file timestamps: {e}")

        return False

    def _pre_render_shadow_image(self, evolution_level: int, force: bool = False) -> bool:
        """Pre-render shadow silhouette for locked mech display."""
        try:
            from PIL import Image
            from services.mech.animation_cache_service import get_animation_cache_service

            cache_service = get_animation_cache_service()
            shadow_path = self.cache_dir / f"mech_{evolution_level}_shadow.webp"

            # Skip if already exists and not forced
            if shadow_path.exists() and not force:
                logger.debug(f"Shadow image already exists for Level {evolution_level}")
                return True

            # Get the cached WebP animation
            webp_bytes = cache_service.get_animation_with_speed(evolution_level, 100.0)

            if not webp_bytes:
                logger.error(f"No animation data for Level {evolution_level}")
                return False

            # Load the first frame from WebP bytes
            with Image.open(io.BytesIO(webp_bytes)) as cached_webp:
                # Get first frame (already perfectly cropped and sized!)
                first_frame = cached_webp.copy().convert('RGBA')

                # Create silhouette: keep transparent pixels transparent, make all others black
                silhouette_data = []
                for pixel in first_frame.getdata():
                    r, g, b, a = pixel
                    if a == 0:
                        # Keep transparent pixels transparent
                        silhouette_data.append((0, 0, 0, 0))
                    else:
                        # Make all non-transparent pixels black
                        silhouette_data.append((0, 0, 0, min(180, a)))  # Semi-transparent black

                # Create silhouette image (same size as cached WebP!)
                silhouette_img = Image.new('RGBA', first_frame.size)
                silhouette_img.putdata(silhouette_data)

                # Save as static WebP to cache
                silhouette_img.save(
                    shadow_path,
                    format='WebP',
                    lossless=True,
                    quality=100,
                    method=6  # Maximum compression quality
                )

                logger.debug(f"Pre-rendered shadow image: {shadow_path}")
                return True

        except Exception as e:
            logger.error(f"Error pre-rendering shadow for Level {evolution_level}: {e}", exc_info=True)
            return False

    def _pre_render_unlocked_image(self, evolution_level: int, force: bool = False) -> bool:
        """Pre-render display animation for unlocked mech display."""
        try:
            # OPTIMIZED: Use pre-rendered big walk animations directly (100 speed)
            from services.mech.animation_cache_service import get_animation_cache_service

            animation_service = get_animation_cache_service()
            unlocked_path = self.cache_dir / f"mech_{evolution_level}_unlocked.webp"

            # Skip if already exists and not forced
            if unlocked_path.exists() and not force:
                logger.debug(f"Unlocked image already exists for Level {evolution_level}")
                return True

            # Get pre-rendered big walk animation (100 speed = high power = walking)
            animation_bytes = animation_service.get_animation_with_speed_and_power_big(evolution_level, 100.0, 100.0)

            if not animation_bytes:
                logger.error(f"No pre-rendered big animation for Level {evolution_level}")
                return False

            # Save pre-rendered animation to cache
            with open(unlocked_path, 'wb') as f:
                f.write(animation_bytes)

            logger.debug(f"Pre-rendered unlocked image: {unlocked_path}")
            return True

        except Exception as e:
            logger.error(f"Error pre-rendering unlocked for Level {evolution_level}: {e}", exc_info=True)
            return False

    def get_mech_display_image(self, request: MechDisplayImageRequest) -> MechDisplayImageResult:
        """Get pre-rendered mech display image for instant Discord loading."""
        try:
            if request.image_type == 'shadow':
                image_path = self.cache_dir / f"mech_{request.evolution_level}_shadow.webp"
                filename = f"mech_shadow_{request.evolution_level}.webp"
            elif request.image_type == 'unlocked':
                image_path = self.cache_dir / f"mech_{request.evolution_level}_unlocked.webp"
                filename = f"mech_level_{request.evolution_level}.webp"
            else:
                return MechDisplayImageResult(
                    success=False,
                    error_message=f"Invalid image type: {request.image_type}"
                )

            if not image_path.exists():
                # Fallback: generate on-demand if not pre-rendered
                logger.warning(f"Pre-rendered image not found: {image_path}, generating on-demand")

                if request.image_type == 'shadow':
                    if not self._pre_render_shadow_image(request.evolution_level):
                        return MechDisplayImageResult(
                            success=False,
                            error_message=f"Failed to generate shadow for Level {request.evolution_level}"
                        )
                else:  # unlocked
                    if not self._pre_render_unlocked_image(request.evolution_level):
                        return MechDisplayImageResult(
                            success=False,
                            error_message=f"Failed to generate unlocked for Level {request.evolution_level}"
                        )

            # Load pre-rendered image
            with open(image_path, 'rb') as f:
                image_bytes = f.read()

            return MechDisplayImageResult(
                success=True,
                image_bytes=image_bytes,
                filename=filename
            )

        except Exception as e:
            error_msg = f"Error loading mech display image: {e}"
            logger.error(error_msg, exc_info=True)
            return MechDisplayImageResult(
                success=False,
                error_message=error_msg
            )

    def clear_cache(self) -> MechDisplayCacheResult:
        """Clear all pre-rendered display images."""
        try:
            deleted_count = 0

            for image_file in self.cache_dir.glob("mech_*_*.webp"):
                image_file.unlink()
                deleted_count += 1

            message = f"Cleared {deleted_count} pre-rendered display images"
            logger.info(message)

            return MechDisplayCacheResult(
                success=True,
                message=message,
                levels_processed=deleted_count
            )

        except Exception as e:
            error_msg = f"Error clearing display cache: {e}"
            logger.error(error_msg, exc_info=True)
            return MechDisplayCacheResult(
                success=False,
                message=error_msg
            )


# Singleton instance
_mech_display_cache_service: Optional[MechDisplayCacheService] = None


def get_mech_display_cache_service() -> MechDisplayCacheService:
    """Get the singleton MechDisplayCacheService instance."""
    global _mech_display_cache_service

    if _mech_display_cache_service is None:
        _mech_display_cache_service = MechDisplayCacheService()

    return _mech_display_cache_service