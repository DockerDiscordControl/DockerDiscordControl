"""
Unified Mech Animation Service
=============================

This service provides a single, clean interface for generating mech animations.
It replaces the complex sync/async duplication in SpriteMechAnimator.

Architecture:
1. Load encrypted mech frames based on evolution level
2. Scale frames to target size (default 270x171) using NEAREST resampling
3. Generate GIF with variable speed based on speed_level
4. Crop vertical transparent pixels automatically
5. Save to temp folder for Discord/WebUI access

Usage:
    service = MechAnimationService()
    filepath = service.generate_animation(
        evolution_level=5,
        speed_level=50.0,
        target_size=(270, 171),
        overlay=True
    )

Key Benefits:
- Single source of truth for animation logic
- File-based output (no sync/async complexity)
- Clear parameter interface
- Automatic vertical cropping
- Centralized caching and optimization

IMPORTANT DOCUMENTATION FOR FUTURE SESSIONS:
============================================

This service completely replaces the old sync/async wrapper approach.

Key Design Decisions:
1. FILE-BASED OUTPUT: Instead of returning bytes/discord.File, we save to /tmp/claude/mech_animations/
2. SINGLE LOGIC PATH: No more sync/async duplication - one method generates, clients read file
3. CLEAR PARAMETERS: evolution_level, speed_level, target_size, overlay
4. VERTICAL CROPPING: Automatically removes transparent pixels above/below mech
5. CACHING: Uses filename-based caching - if file exists, return path immediately
6. PIXEL-PERFECT SCALING: Uses Image.NEAREST for crisp pixel art scaling

Integration Points:
- Discord Bot: Calls generate_animation(), then creates discord.File from filepath
- Web UI: Calls generate_animation(), then serves file content as HTTP response
- Both use the same generated files - no duplication

Trigger Conditions:
- New animation needed when:
  * Evolution level changes (major power milestones)
  * Speed level changes by >=1.0 (whole power units)
  * Target size changes (unlikely)
  * Overlay on/off changes

Performance:
- File-based caching eliminates duplicate generation
- Only generates when parameters actually change
- Cleanup system prevents disk space issues
"""

import os
import hashlib
import logging
from typing import Tuple, Optional, List
from PIL import Image
from io import BytesIO
import tempfile
import time

logger = logging.getLogger(__name__)

class MechAnimationService:
    """
    Unified service for mech animation generation.

    This service handles all mech animation creation with a clean, single interface.
    Both Discord bot and Web UI use this service to generate consistent animations.
    """

    def __init__(self, temp_dir: str = "/tmp/claude/mech_animations"):
        """
        Initialize the mech animation service.

        Args:
            temp_dir: Directory for temporary animation files
        """
        self.temp_dir = temp_dir
        self.frames_per_animation = 8  # All mech sprites have 8 frames
        self.max_file_size = 500_000  # 500KB Discord limit

        # Ensure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)

        # Load encryption handler
        from services.mech.mech_evolution_loader import get_mech_loader
        self.mech_loader = get_mech_loader()

        logger.info(f"MechAnimationService initialized with temp_dir: {self.temp_dir}")

    def generate_animation(self,
                          evolution_level: int,
                          speed_level: float,
                          target_size: Tuple[int, int] = (270, 171),
                          overlay: bool = True,
                          donor_name: str = "",
                          amount: str = "") -> str:
        """
        Generate a mech animation and return the filepath.

        This is the main entry point for animation generation.

        Args:
            evolution_level: Mech evolution level (1-11)
            speed_level: Animation speed (0-101, higher = faster)
            target_size: Target canvas size in pixels (width, height)
            overlay: Whether to add power consumption overlay
            donor_name: Donor name for overlay text
            amount: Donation amount for overlay text

        Returns:
            str: Filepath to the generated GIF animation

        Process:
        1. Generate cache key from parameters
        2. Check if animation already exists
        3. If not, create new animation:
           - Load encrypted frames for evolution level
           - Scale frames to target size
           - Apply speed-based frame duration
           - Add overlay if requested
           - Crop vertical transparent pixels
           - Save to temp directory
        4. Return filepath
        """
        # Generate unique cache key
        cache_key = self._generate_cache_key(
            evolution_level, speed_level, target_size, overlay, donor_name, amount
        )

        # Check if animation already exists
        filepath = os.path.join(self.temp_dir, f"{cache_key}.gif")
        if os.path.exists(filepath):
            logger.debug(f"Using cached animation: {filepath}")
            return filepath

        logger.info(f"Generating new animation: evolution={evolution_level}, speed={speed_level}, size={target_size}")

        try:
            # Step 1: Load frames for evolution level
            frames = self._load_mech_frames(evolution_level)

            # Step 2: Scale frames to target size
            scaled_frames = self._scale_frames(frames, target_size)

            # Step 3: Calculate frame duration from speed
            frame_duration_ms = self._calculate_frame_duration(speed_level)

            # Step 4: Add overlay if requested
            if overlay and donor_name and amount:
                scaled_frames = self._add_overlay(scaled_frames, donor_name, amount, speed_level)

            # Step 5: Crop vertical transparent pixels
            cropped_frames = self._crop_vertical_transparent(scaled_frames)

            # Step 6: Enhance colors before GIF conversion
            enhanced_frames = self._enhance_colors(cropped_frames)

            # Step 7: Save as GIF
            self._save_gif(enhanced_frames, filepath, frame_duration_ms)

            logger.info(f"Animation saved: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Error generating animation: {e}")
            # Return fallback animation path
            return self._create_fallback_animation(evolution_level, target_size)

    def _generate_cache_key(self, evolution_level: int, speed_level: float,
                           target_size: Tuple[int, int], overlay: bool,
                           donor_name: str, amount: str) -> str:
        """Generate unique cache key for animation parameters."""
        # Create normalized key for better cache hits
        # Round speed to 1 decimal place for better cache efficiency
        speed_rounded = round(speed_level, 1)
        key_data = f"evo_{evolution_level}_speed_{speed_rounded}_size_{target_size[0]}x{target_size[1]}_overlay_{overlay}"

        # For overlay animations, include donor info
        if overlay and donor_name and amount:
            key_data += f"_donor_{donor_name}_amount_{amount}"

        # Use MD5 hash for consistent filename
        return hashlib.md5(key_data.encode()).hexdigest()[:12]  # 12 chars is enough

    def _load_mech_frames(self, evolution_level: int) -> List[Image.Image]:
        """
        Load encrypted mech frames for the given evolution level.

        Args:
            evolution_level: Evolution level (1-11)

        Returns:
            List[Image.Image]: List of PIL Image frames
        """
        try:
            # Load WebP animation bytes for evolution level
            webp_bytes = self.mech_loader.get_mech_animation(evolution_level)
            if not webp_bytes:
                logger.warning(f"No animation for level {evolution_level}, using level 1")
                webp_bytes = self.mech_loader.get_mech_animation(1)

            if not webp_bytes:
                raise Exception("Unable to load any animation")

            # Convert WebP animation to PIL frames
            frames = []
            with Image.open(BytesIO(webp_bytes)) as webp_image:
                # Extract all frames from WebP animation
                try:
                    frame_count = 0
                    while True:
                        webp_image.seek(frame_count)
                        # Convert frame to RGBA for consistency
                        frame = webp_image.copy().convert('RGBA')
                        frames.append(frame)
                        frame_count += 1

                        # Safety limit
                        if frame_count >= self.frames_per_animation:
                            break
                except EOFError:
                    # End of frames reached
                    pass

            logger.debug(f"Loaded {len(frames)} frames for evolution level {evolution_level}")
            return frames

        except Exception as e:
            logger.error(f"Error loading frames for evolution {evolution_level}: {e}")
            return []

    def _scale_frames(self, frames: List[Image.Image], target_size: Tuple[int, int]) -> List[Image.Image]:
        """
        Scale frames to target size while preserving aspect ratio and centering with transparent padding.

        Args:
            frames: List of PIL Image frames
            target_size: Target canvas size (width, height)

        Returns:
            List[Image.Image]: List of scaled and centered frames
        """
        if not frames:
            return []

        scaled_frames = []
        target_width, target_height = target_size

        for frame in frames:
            original_width, original_height = frame.size

            # Calculate scaling factor to fit within target size while preserving aspect ratio
            scale_w = target_width / original_width
            scale_h = target_height / original_height
            scale = min(scale_w, scale_h)  # Use smaller scale to fit within bounds

            # Calculate new size maintaining aspect ratio
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)

            # Scale the frame with preserved aspect ratio
            scaled_frame = frame.resize((new_width, new_height), Image.NEAREST)

            # Create target canvas with transparent background
            canvas = Image.new('RGBA', target_size, (0, 0, 0, 0))

            # Center the scaled frame on the canvas
            offset_x = (target_width - new_width) // 2
            offset_y = (target_height - new_height) // 2

            # Paste scaled frame onto center of canvas
            canvas.paste(scaled_frame, (offset_x, offset_y), scaled_frame if scaled_frame.mode == 'RGBA' else None)

            scaled_frames.append(canvas)

        logger.debug(f"Scaled {len(frames)} frames to {target_size} with aspect ratio preserved")
        return scaled_frames

    def _enhance_colors(self, frames: List[Image.Image]) -> List[Image.Image]:
        """
        AGGRESSIVE color enhancement using HSV manipulation and selective boosting.

        This approach directly manipulates HSV values for more dramatic results
        than simple RGB enhancement, specifically targeting mech colors.

        Args:
            frames: List of PIL Image frames

        Returns:
            List[Image.Image]: Aggressively color-enhanced frames
        """
        if not frames:
            return []

        try:
            from PIL import ImageEnhance
            import colorsys

            enhanced_frames = []

            for frame in frames:
                # Convert to RGB for pixel manipulation
                rgba_frame = frame.convert('RGBA')
                width, height = rgba_frame.size

                # Create new image for enhanced result
                enhanced_data = []

                # Process each pixel using PIL's load() method
                pixels = rgba_frame.load()

                for y in range(height):
                    row = []
                    for x in range(width):
                        r, g, b, a = pixels[x, y]

                        # Skip transparent pixels
                        if a == 0:
                            row.append((r, g, b, a))
                            continue

                        # Convert RGB to HSV for targeted color manipulation
                        h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)

                        # ONLY enhance RED colors - leave everything else unchanged
                        # Red colors (0.0-0.1 and 0.9-1.0): +100% boost (EXTREME)
                        if (h < 0.1 or h > 0.9) and s > 0.1:  # Red range with some saturation
                            s = min(1.0, s * 2.0)  # 100% saturation boost for reds only
                            v = min(1.0, v * 1.30)  # 30% brightness boost for reds only

                        # All other colors: NO CHANGE (keep original values)

                        # Convert back to RGB
                        new_r, new_g, new_b = colorsys.hsv_to_rgb(h, s, v)

                        # Update pixel
                        row.append((
                            int(new_r * 255),
                            int(new_g * 255),
                            int(new_b * 255),
                            a  # Keep original alpha
                        ))

                    enhanced_data.extend(row)

                # Create new image from enhanced data
                enhanced = Image.new('RGBA', (width, height))
                enhanced.putdata(enhanced_data)

                # No additional global enhancements - only red color boosting
                enhanced_frames.append(enhanced)

            logger.debug(f"Selective RED enhancement applied to {len(frames)} frames (+100% red saturation only)")
            return enhanced_frames

        except Exception as e:
            logger.warning(f"Aggressive color enhancement failed, falling back to simple enhancement: {e}")
            # Fallback to simple enhancement
            try:
                from PIL import ImageEnhance
                enhanced_frames = []
                for frame in frames:
                    enhanced = frame.copy()
                    enhanced = ImageEnhance.Color(enhanced).enhance(2.0)
                    enhanced = ImageEnhance.Contrast(enhanced).enhance(1.5)
                    enhanced_frames.append(enhanced)
                return enhanced_frames
            except:
                return frames

    def _calculate_frame_duration(self, speed_level: float) -> int:
        """
        Calculate frame duration in milliseconds based on speed level.

        Args:
            speed_level: Speed level (0-101, higher = faster)

        Returns:
            int: Frame duration in milliseconds

        Speed mapping (optimized for 8 frames):
        - 0: 280ms (slowest)
        - 100: 20ms (fastest)
        - Eased curve for smooth progression
        """
        if speed_level <= 0:
            return 280  # Slowest speed
        if speed_level >= 101:
            return 20   # Fastest speed

        # Normalize to 0-1 range
        x = min(1.0, max(0.0, speed_level / 100.0))

        # Apply ease-out curve for natural feel
        eased = 1 - (1 - x) ** 3

        # Map to duration range (280ms to 20ms)
        duration = int(round(280 - 260 * eased))

        logger.debug(f"Speed {speed_level} -> Duration {duration}ms")
        return duration

    def _add_overlay(self, frames: List[Image.Image], donor_name: str, amount: str, speed_level: float) -> List[Image.Image]:
        """
        Add power consumption overlay to frames.

        Args:
            frames: List of PIL Image frames
            donor_name: Donor name for display
            amount: Donation amount for display
            speed_level: Current speed level for display

        Returns:
            List[Image.Image]: Frames with overlay added
        """
        # TODO: Implement overlay logic from existing system
        # For now, return frames unchanged
        logger.debug(f"Overlay requested for {donor_name}: {amount} (speed: {speed_level})")
        return frames

    def _crop_vertical_transparent(self, frames: List[Image.Image]) -> List[Image.Image]:
        """
        Crop vertical transparent pixels to minimize canvas height.

        Args:
            frames: List of PIL Image frames

        Returns:
            List[Image.Image]: Frames with vertical transparent pixels cropped

        Process:
        1. Find the bounding box of non-transparent pixels across all frames
        2. Crop all frames to this bounding box
        3. Maintain horizontal centering within target width
        """
        if not frames:
            return []

        # Find global bounding box across all frames
        global_min_y = float('inf')
        global_max_y = 0

        for frame in frames:
            if frame.mode != 'RGBA':
                frame = frame.convert('RGBA')

            # Get alpha channel
            alpha = frame.split()[-1]  # Last channel is alpha

            # Find non-transparent pixels
            bbox = alpha.getbbox()
            if bbox:
                _, min_y, _, max_y = bbox
                global_min_y = min(global_min_y, min_y)
                global_max_y = max(global_max_y, max_y)

        # If no content found, return original frames
        if global_min_y == float('inf'):
            logger.warning("No non-transparent content found, skipping crop")
            return frames

        # Crop all frames to the global bounding box (vertical only)
        cropped_frames = []
        original_width = frames[0].width
        crop_height = global_max_y - global_min_y

        for frame in frames:
            # Crop vertically only, keep full width
            cropped = frame.crop((0, global_min_y, original_width, global_max_y))
            cropped_frames.append(cropped)

        logger.info(f"Cropped frames vertically: {frames[0].height} -> {crop_height} pixels")
        return cropped_frames

    def _save_gif(self, frames: List[Image.Image], filepath: str, duration_ms: int):
        """
        Save frames as optimized GIF animation.

        Args:
            frames: List of PIL Image frames
            filepath: Output filepath
            duration_ms: Frame duration in milliseconds
        """
        if not frames:
            raise ValueError("No frames to save")

        # Save as GIF with better color preservation
        # Note: optimize=False preserves more colors but increases file size
        frames[0].save(
            filepath,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            duration=duration_ms,
            loop=0,  # Infinite loop
            optimize=False,  # Disable optimization to preserve colors better
            disposal=2  # Clear frame before next
        )

        # Check file size
        file_size = os.path.getsize(filepath)
        if file_size > self.max_file_size:
            logger.warning(f"Animation file size ({file_size} bytes) exceeds limit ({self.max_file_size} bytes)")

        logger.info(f"GIF saved: {filepath} ({file_size} bytes, {len(frames)} frames, {duration_ms}ms/frame)")

    def _create_fallback_animation(self, evolution_level: int, target_size: Tuple[int, int]) -> str:
        """
        Create a simple fallback animation when main generation fails.

        Args:
            evolution_level: Requested evolution level
            target_size: Target size

        Returns:
            str: Filepath to fallback animation
        """
        fallback_path = os.path.join(self.temp_dir, f"fallback_evo{evolution_level}.gif")

        try:
            # Create simple static image as fallback
            fallback_image = Image.new('RGBA', target_size, (47, 49, 54, 255))  # Discord dark theme color

            # Add simple text indicating fallback
            try:
                from PIL import ImageDraw
                draw = ImageDraw.Draw(fallback_image)
                draw.text((10, 10), f"Mech {evolution_level}", fill=(255, 255, 255, 255))
            except:
                pass  # If text fails, just use solid color

            fallback_image.save(fallback_path, format='GIF')
        except Exception as e:
            logger.error(f"Failed to create fallback animation: {e}")
            # Create minimal fallback
            with open(fallback_path, 'wb') as f:
                f.write(b'GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00;')

        logger.info(f"Created fallback animation: {fallback_path}")
        return fallback_path

    def cleanup_old_animations(self, max_age_hours: int = 24):
        """
        Clean up old animation files to prevent disk space issues.

        Args:
            max_age_hours: Maximum age in hours before cleanup
        """
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        cleaned_count = 0
        for filename in os.listdir(self.temp_dir):
            if filename.endswith('.gif'):
                filepath = os.path.join(self.temp_dir, filename)
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > max_age_seconds:
                        try:
                            os.remove(filepath)
                            cleaned_count += 1
                        except OSError:
                            pass

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old animation files")

    # === COMPATIBILITY METHODS FOR MIGRATION ===
    # These methods provide compatibility with existing Discord/WebUI code during migration

    def create_donation_animation_sync(self, donor_name: str, amount: str, total_donations: float) -> bytes:
        """
        Compatibility method for Web UI - generates animation and returns bytes.

        Args:
            donor_name: Donor name
            amount: Donation amount string
            total_donations: Total donations for evolution level calculation

        Returns:
            bytes: GIF animation data
        """
        try:
            from services.mech.mech_evolutions import get_evolution_level
            from services.mech.mech_service import get_mech_service

            # Calculate parameters
            evolution_level = get_evolution_level(total_donations)
            mech_service = get_mech_service()
            current_power = float(mech_service.get_state().Power)

            # Calculate speed level (existing logic)
            speed_level = self._calculate_speed_level(total_donations, current_power)

            # Generate animation file
            filepath = self.generate_animation(
                evolution_level=evolution_level,
                speed_level=speed_level,
                target_size=(270, 171),
                overlay=True,
                donor_name=donor_name,
                amount=amount
            )

            # Read and return bytes
            with open(filepath, 'rb') as f:
                return f.read()

        except Exception as e:
            logger.error(f"Error in compatibility sync method: {e}")
            return self._create_error_gif_bytes()

    async def create_donation_animation(self, donor_name: str, amount: str, total_donations: float, show_overlay: bool = True):
        """
        Compatibility method for Discord Bot - generates animation and returns discord.File.

        Args:
            donor_name: Donor name
            amount: Donation amount string
            total_donations: Total donations for evolution level calculation
            show_overlay: Whether to show overlay

        Returns:
            discord.File: Discord file object
        """
        try:
            import discord
            from services.mech.mech_evolutions import get_evolution_level
            from services.mech.mech_service import get_mech_service

            # Calculate parameters
            evolution_level = get_evolution_level(total_donations)
            mech_service = get_mech_service()
            current_power = float(mech_service.get_state().Power)

            # Calculate speed level (existing logic)
            speed_level = self._calculate_speed_level(total_donations, current_power)

            # Generate animation file
            filepath = self.generate_animation(
                evolution_level=evolution_level,
                speed_level=speed_level,
                target_size=(270, 171),
                overlay=show_overlay,
                donor_name=donor_name if show_overlay else "",
                amount=amount if show_overlay else ""
            )

            # Create discord.File from filepath
            return discord.File(filepath, filename=f"mech_animation_{int(time.time())}.gif")

        except Exception as e:
            logger.error(f"Error in compatibility async method: {e}")
            # Return error file
            error_path = self._create_fallback_animation(1, (270, 171))
            return discord.File(error_path, filename="error_animation.gif")

    # === STATUS VIEW COMPATIBILITY METHODS ===
    # These methods provide compatibility for /ss status views

    async def create_expanded_status_animation_async(self, power_level: float, total_donations: float):
        """Create animation with power consumption overlay for expanded /ss status view"""
        return await self.create_donation_animation("Status", "0.00", total_donations, show_overlay=True)

    async def create_collapsed_status_animation_async(self, power_level: float, total_donations: float):
        """Create animation without overlay for collapsed /ss status view"""
        return await self.create_donation_animation("Status", "0.00", total_donations, show_overlay=False)

    def create_expanded_status_animation_sync(self, power_level: float, total_donations: float) -> bytes:
        """Create animation with power consumption overlay for expanded /ss status view (sync)"""
        return self.create_donation_animation_sync("Status", "0.00", total_donations)

    def create_collapsed_status_animation_sync(self, power_level: float, total_donations: float) -> bytes:
        """Create animation without overlay for collapsed /ss status view (sync)"""
        return self.create_donation_animation_sync("Status", "0.00", total_donations)

    def _calculate_speed_level(self, total_donations: float, current_power: float) -> float:
        """
        Calculate speed level from donations and power.

        Power-based speed calculation with stretching for high levels.
        Speed resets with Power on evolution and scales based on level difficulty.

        Args:
            total_donations: Total cumulative donations (for level determination)
            current_power: Current Power value (for speed within level)

        Returns:
            Speed level 0..101 where 101 is OMEGA speed
        """
        if total_donations <= 0:
            return 0.0

        try:
            from services.mech.mech_evolutions import get_evolution_level, EVOLUTION_THRESHOLDS

            lvl = max(1, min(11, get_evolution_level(total_donations)))

            # NEW: Simple Power = Speed with stretching
            # 1 Power = 1 Speed Level (base)
            # Stretching factor makes it harder at high levels

            # Stretching factor: higher levels need more Power per speed unit
            # Level 1-3: 1x (1 Power = 1 Speed)
            # Level 4-6: 1.5x (1.5 Power = 1 Speed)
            # Level 7-9: 2x (2 Power = 1 Speed)
            # Level 10-11: 3x (3 Power = 1 Speed)
            if lvl <= 3:
                stretch_factor = 1.0
            elif lvl <= 6:
                stretch_factor = 1.5
            elif lvl <= 9:
                stretch_factor = 2.0
            else:
                stretch_factor = 3.0

            # Direct calculation: Power / stretch = Speed
            # 30 Power at Level 2 (stretch 1.0) = 30 Speed
            # 30 Power at Level 8 (stretch 2.0) = 15 Speed
            base_speed = current_power / stretch_factor

            # Cap at 100, special case for OMEGA
            if lvl == 11 and base_speed >= 100:
                return 101.0

            return min(100.0, max(0.0, base_speed))

        except Exception as e:
            logger.error(f"Error calculating speed level: {e}")
            # Fallback calculation
            return min(100.0, max(0.0, current_power))

    def _create_error_gif_bytes(self) -> bytes:
        """Create error GIF as bytes."""
        try:
            error_img = Image.new('RGBA', (270, 171), (47, 49, 54, 255))
            buffer = BytesIO()
            error_img.save(buffer, format='GIF')
            return buffer.getvalue()
        except:
            # Minimal GIF fallback
            return b'GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00;'

# Global service instance
_mech_animation_service = None

def get_mech_animation_service() -> MechAnimationService:
    """
    Get the global mech animation service instance.

    Returns:
        MechAnimationService: The service instance
    """
    global _mech_animation_service
    if _mech_animation_service is None:
        _mech_animation_service = MechAnimationService()
    return _mech_animation_service

