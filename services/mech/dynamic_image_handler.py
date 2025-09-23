#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Dynamic Image Handler for Mech Animations      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Dynamic Image Handler for variable-sized mech images.
Handles different sizes, aspect ratios, and automatic scaling.
"""

import json
import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List
from PIL import Image, ImageOps
from dataclasses import dataclass
import base64
from io import BytesIO

logger = logging.getLogger(__name__)

@dataclass
class MechImageInfo:
    """Information about a mech image."""
    level: int
    name: str
    original_width: int
    original_height: int
    scale_factor: float
    position_offset_y: int
    frames: List[Image.Image]
    aspect_ratio: float
    
    @property
    def scaled_size(self) -> Tuple[int, int]:
        """Get scaled dimensions."""
        width = int(self.original_width * self.scale_factor)
        height = int(self.original_height * self.scale_factor)
        return width, height


class DynamicImageHandler:
    """Handles dynamic sizing and positioning of mech images."""
    
    def __init__(self, config_path: str = "services/mech/dynamic_size_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.image_cache: Dict[int, MechImageInfo] = {}
        
    def _load_config(self) -> Dict[str, Any]:
        """Load dynamic sizing configuration."""
        try:
            if self.config_path.exists():
                with self.config_path.open('r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"Dynamic size config not found at {self.config_path}")
                return self._get_default_config()
        except Exception as e:
            logger.error(f"Error loading dynamic size config: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "mech_image_settings": {
                "auto_detect_size": True,
                "preserve_aspect_ratio": True,
                "max_animation_width": 256,  # 50% smaller total image size
                "max_animation_height": 256,  # 50% smaller total image size
                "min_animation_width": 64,   # 50% smaller total image size
                "min_animation_height": 64   # 50% smaller total image size
            },
            "dynamic_sizing": {
                "enabled": True,
                "auto_center": True,
                "maintain_ground_contact": True
            }
        }
    
    def analyze_image(self, image: Image.Image, threshold: int = 10) -> Dict[str, Any]:
        """
        Intelligently analyze an image to find the actual mech content.
        
        Args:
            image: PIL Image to analyze
            threshold: Alpha threshold for considering a pixel as "content" (0-255)
        
        Returns:
            Detailed analysis including precise mech bounds
        """
        # Get basic dimensions
        width, height = image.size
        aspect_ratio = width / height if height > 0 else 1.0
        
        # Initialize bounds tracking
        min_x, min_y = width, height
        max_x, max_y = 0, 0
        has_content = False
        
        # More intelligent content detection
        if image.mode == 'RGBA':
            # Convert to RGBA if not already
            img_data = image.getdata()
            
            # First pass: Find the actual mech bounds (non-transparent pixels)
            for y in range(height):
                for x in range(width):
                    pixel = img_data[y * width + x]
                    # Check if pixel has meaningful opacity (not fully transparent)
                    if len(pixel) >= 4 and pixel[3] > threshold:
                        # Also check if it's not just a shadow (very dark pixels with low alpha)
                        is_shadow = pixel[3] < 50 and sum(pixel[:3]) < 30
                        if not is_shadow:
                            has_content = True
                            min_x = min(min_x, x)
                            min_y = min(min_y, y)
                            max_x = max(max_x, x)
                            max_y = max(max_y, y)
            
            # Fallback to getbbox if our intelligent detection found nothing
            if not has_content:
                bbox = image.getbbox()
                if bbox:
                    min_x, min_y, max_x, max_y = bbox
                    has_content = True
                    content_width = max_x - min_x
                    content_height = max_y - min_y
                else:
                    # Fully transparent image
                    content_width = width
                    content_height = height
                    min_x = min_y = 0
            else:
                content_width = max_x - min_x + 1
                content_height = max_y - min_y + 1
                
            # Second pass: Find the "center of mass" of the mech
            total_weight = 0
            center_x = 0
            center_y = 0
            
            if has_content:
                for y in range(min_y, min(max_y + 1, height)):
                    for x in range(min_x, min(max_x + 1, width)):
                        pixel = img_data[y * width + x]
                        if len(pixel) >= 4 and pixel[3] > threshold:
                            # Weight by opacity (more opaque = more important)
                            weight = pixel[3] / 255.0
                            center_x += x * weight
                            center_y += y * weight
                            total_weight += weight
                
                if total_weight > 0:
                    center_x = int(center_x / total_weight)
                    center_y = int(center_y / total_weight)
                else:
                    center_x = min_x + content_width // 2
                    center_y = min_y + content_height // 2
            else:
                center_x = width // 2
                center_y = height // 2
                
        else:
            # Non-RGBA images - use simple bbox
            bbox = image.getbbox()
            if bbox:
                min_x, min_y, max_x, max_y = bbox
                content_width = max_x - min_x
                content_height = max_y - min_y
            else:
                content_width = width
                content_height = height
                min_x = min_y = 0
            
            center_x = min_x + content_width // 2
            center_y = min_y + content_height // 2
            has_content = True
        
        # Calculate padding around content
        padding_left = min_x
        padding_right = width - max_x if has_content else 0
        padding_top = min_y
        padding_bottom = height - max_y if has_content else 0
        
        # Detect if mech is likely standing on ground (has pixels at bottom)
        is_grounded = False
        if has_content and image.mode == 'RGBA':
            # Check last few rows for content
            for y in range(max(0, max_y - 5), min(max_y + 1, height)):
                for x in range(min_x, min(max_x + 1, width)):
                    pixel = img_data[y * width + x]
                    if len(pixel) >= 4 and pixel[3] > threshold * 2:  # Higher threshold for ground detection
                        is_grounded = True
                        break
                if is_grounded:
                    break
        
        return {
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
            "has_content": has_content,
            "content_bounds": {
                "x": min_x,
                "y": min_y,
                "width": content_width,
                "height": content_height
            },
            "content_center": {
                "x": center_x,
                "y": center_y
            },
            "padding": {
                "left": padding_left,
                "right": padding_right,
                "top": padding_top,
                "bottom": padding_bottom
            },
            "is_grounded": is_grounded,
            "has_transparency": image.mode == 'RGBA',
            "is_animated": hasattr(image, 'n_frames') and image.n_frames > 1
        }
    
    def smart_resize(self, image: Image.Image, target_width: int, target_height: int,
                    maintain_aspect: bool = True, fit_mode: str = "contain") -> Image.Image:
        """
        Smart resize with multiple fit modes.
        
        Args:
            image: Source image
            target_width: Target width
            target_height: Target height
            maintain_aspect: Whether to maintain aspect ratio
            fit_mode: "contain" (fit inside), "cover" (fill area), or "stretch"
        """
        if not maintain_aspect or fit_mode == "stretch":
            return image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # Calculate scaling factors
        width_ratio = target_width / image.width
        height_ratio = target_height / image.height
        
        if fit_mode == "contain":
            # Scale to fit inside target dimensions
            scale = min(width_ratio, height_ratio)
        elif fit_mode == "cover":
            # Scale to cover target dimensions
            scale = max(width_ratio, height_ratio)
        else:
            scale = min(width_ratio, height_ratio)
        
        new_width = int(image.width * scale)
        new_height = int(image.height * scale)
        
        # Resize image
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        if fit_mode == "cover" and (new_width != target_width or new_height != target_height):
            # Crop to target dimensions
            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            right = left + target_width
            bottom = top + target_height
            resized = resized.crop((left, top, right, bottom))
        
        return resized
    
    def create_canvas_for_level(self, level: int) -> Tuple[Image.Image, Dict[str, int]]:
        """
        Create an appropriately sized canvas for a mech level.
        
        Returns:
            Tuple of (canvas image, positioning info dict)
        """
        level_config = self.config.get("mech_sizes_by_level", {}).get(str(level), {})
        settings = self.config.get("mech_image_settings", {})
        
        # Determine canvas size based on level (50% SMALLER TOTAL IMAGE)
        base_width = settings.get("max_animation_width", 256)  # 50% smaller total image
        base_height = settings.get("max_animation_height", 256)  # 50% smaller total image

        # Apply level-specific scaling
        scale_factor = level_config.get("scale_factor", 1.0)

        # Canvas size can grow with higher levels (50% SMALLER TOTAL IMAGE)
        if level >= 7:  # Larger mechs get bigger canvases
            canvas_width = min(int(base_width * 1.2), 320)  # 50% of 640px
            canvas_height = min(int(base_height * 1.2), 320)  # 50% of 640px
        elif level >= 5:
            canvas_width = base_width
            canvas_height = base_height
        else:  # Smaller mechs can use smaller canvases
            canvas_width = max(int(base_width * 0.8), settings.get("min_animation_width", 64))  # 50% of 128px
            canvas_height = max(int(base_width * 0.8), settings.get("min_animation_height", 64))  # 50% of 128px
        
        # Create transparent canvas
        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
        
        # Calculate positioning info
        composition = self.config.get("composition_rules", {})
        ground_line = int(canvas_height * composition.get("ground_line", 0.85))
        center_x = canvas_width // 2
        
        # Vertical offset for larger mechs
        offset_y = level_config.get("position_offset_y", 0)
        
        positioning = {
            "canvas_width": canvas_width,
            "canvas_height": canvas_height,
            "center_x": center_x,
            "ground_line": ground_line,
            "mech_base_y": ground_line + offset_y,
            "scale_factor": scale_factor
        }
        
        return canvas, positioning
    
    def composite_mech_on_canvas(self, mech_image: Image.Image, level: int,
                                 background: Optional[Image.Image] = None) -> Image.Image:
        """
        Intelligently composite a mech image onto an appropriately sized canvas.
        
        Args:
            mech_image: The mech sprite/image
            level: Mech evolution level (1-11)
            background: Optional background image
        
        Returns:
            Composited image ready for animation
        """
        # Create canvas and get positioning info
        canvas, pos_info = self.create_canvas_for_level(level)
        
        # Add background if provided
        if background:
            bg_resized = self.smart_resize(
                background, 
                pos_info["canvas_width"], 
                pos_info["canvas_height"],
                fit_mode="cover"
            )
            canvas.paste(bg_resized, (0, 0))
        
        # Intelligently analyze mech image
        mech_info = self.analyze_image(mech_image)
        
        # Calculate mech scaling
        scale_factor = pos_info["scale_factor"]
        
        # Smart scaling based on actual content bounds
        if self.config.get("dynamic_sizing", {}).get("enabled", True) and mech_info["has_content"]:
            # Use actual content dimensions instead of full image dimensions
            content_bounds = mech_info["content_bounds"]
            content_width = content_bounds["width"]
            content_height = content_bounds["height"]
            
            # Auto-fit mech content to canvas with padding
            padding = self.config.get("dynamic_sizing", {}).get("smart_cropping", {}).get("min_padding", 10)
            max_mech_height = pos_info["ground_line"] - padding
            max_mech_width = pos_info["canvas_width"] - (padding * 2)
            
            # Calculate best fit based on actual content size
            width_scale = max_mech_width / content_width if content_width > 0 else 1.0
            height_scale = max_mech_height / content_height if content_height > 0 else 1.0
            auto_scale = min(width_scale, height_scale) * scale_factor
            
            # Apply scale to full image (maintaining transparency padding)
            final_width = int(mech_image.width * auto_scale)
            final_height = int(mech_image.height * auto_scale)
            
            # Scale the content bounds too for positioning
            scaled_content_x = int(content_bounds["x"] * auto_scale)
            scaled_content_y = int(content_bounds["y"] * auto_scale)
            scaled_content_width = int(content_width * auto_scale)
            scaled_content_height = int(content_height * auto_scale)
            
            logger.debug(f"Level {level} mech: Original {mech_image.width}x{mech_image.height}, "
                        f"Content {content_width}x{content_height}, "
                        f"Scaled to {final_width}x{final_height}")
        else:
            # Use fixed scaling
            final_width = int(mech_image.width * scale_factor)
            final_height = int(mech_image.height * scale_factor)
            scaled_content_x = 0
            scaled_content_y = 0
            scaled_content_width = final_width
            scaled_content_height = final_height
        
        # Resize mech (use NEAREST for pixel art, LANCZOS for smooth art)
        resample_mode = Image.NEAREST if final_width < mech_image.width else Image.LANCZOS
        mech_resized = mech_image.resize((final_width, final_height), resample_mode)
        
        # Smart positioning based on content center and grounding
        if mech_info["has_content"] and self.config.get("dynamic_sizing", {}).get("auto_center", True):
            # Center based on actual content, not full image
            mech_x = pos_info["center_x"] - (scaled_content_x + scaled_content_width // 2)
            
            # If mech is grounded, align bottom of content with ground line
            if mech_info["is_grounded"]:
                mech_y = pos_info["mech_base_y"] - (scaled_content_y + scaled_content_height)
            else:
                # Floating mech - center vertically in available space
                available_height = pos_info["ground_line"]
                mech_y = (available_height - scaled_content_height) // 2 - scaled_content_y
        else:
            # Simple center positioning
            mech_x = pos_info["center_x"] - (final_width // 2)
            mech_y = pos_info["mech_base_y"] - final_height
        
        # Apply level-specific vertical offset
        mech_y += pos_info.get("position_offset_y", 0)
        
        # Ensure mech doesn't go out of bounds
        mech_x = max(0, min(mech_x, pos_info["canvas_width"] - final_width))
        mech_y = max(0, min(mech_y, pos_info["canvas_height"] - final_height))
        
        # Composite mech onto canvas
        if mech_resized.mode == 'RGBA':
            canvas.paste(mech_resized, (mech_x, mech_y), mech_resized)
        else:
            canvas.paste(mech_resized, (mech_x, mech_y))
        
        # Debug info overlay (optional)
        if self.config.get("debug_mode", False):
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            # Draw content bounds
            draw.rectangle([
                mech_x + scaled_content_x,
                mech_y + scaled_content_y,
                mech_x + scaled_content_x + scaled_content_width,
                mech_y + scaled_content_y + scaled_content_height
            ], outline=(255, 0, 0, 128), width=1)
            # Draw center point
            center_x = mech_x + mech_info["content_center"]["x"] * auto_scale
            center_y = mech_y + mech_info["content_center"]["y"] * auto_scale
            draw.ellipse([center_x-3, center_y-3, center_x+3, center_y+3], 
                        fill=(0, 255, 0, 200))
        
        return canvas
    
    def prepare_animation_frames(self, frames: List[Image.Image], level: int,
                                target_fps: int = 10, optimize: bool = True) -> List[Image.Image]:
        """
        Prepare frames for animation with optimal cropping and consistent sizing.
        Analyzes ALL frames to find the maximum envelope, then crops optimally.
        
        Args:
            frames: List of PIL images (frames)
            level: Mech evolution level
            target_fps: Target frames per second
            optimize: Whether to optimize for file size
        
        Returns:
            List of prepared frames with optimal cropping
        """
        if not frames:
            return []
        
        prepared_frames = []
        
        # SCHRITT 1: Envelope Detection - Analysiere ALLE Frames für maximale Bounds
        logger.info(f"Analyzing {len(frames)} frames for envelope detection...")
        
        # Track maximum bounds across all frames
        # Für Links/Rechts: Original behalten
        # Für Oben/Unten: Envelope Detection
        global_min_x = 0  # IMMER 0 - links nicht zuschneiden
        global_min_y = float('inf')  # Oben zuschneiden
        global_max_x = frames[0].width if frames else 0  # IMMER volle Breite - rechts nicht zuschneiden
        global_max_y = 0  # Unten zuschneiden
        has_any_content = False
        
        frame_analyses = []
        
        for i, frame in enumerate(frames):
            analysis = self.analyze_image(frame, threshold=10)
            frame_analyses.append(analysis)
            
            if analysis["has_content"]:
                has_any_content = True
                bounds = analysis["content_bounds"]
                
                # NUR vertikale Envelope erweitern (oben/unten)
                # Horizontale bleibt bei voller Breite
                global_min_y = min(global_min_y, bounds["y"])
                global_max_y = max(global_max_y, bounds["y"] + bounds["height"])
                
                logger.debug(f"Frame {i}: vertical bounds Y:{bounds['y']} to Y:{bounds['y'] + bounds['height']} "
                           f"(keeping full width: 0 to {frame.width})")
        
        if not has_any_content:
            logger.warning("No content found in any frame, using full image dimensions")
            global_min_x = 0
            global_min_y = 0
            global_max_x = frames[0].width
            global_max_y = frames[0].height
        
        # Berechne die Envelope
        # Breite = Original (keine seitliche Beschneidung)
        # Höhe = Optimiert (oben/unten beschnitten)
        envelope_width = int(global_max_x - global_min_x)  # Volle Breite
        envelope_height = int(global_max_y - global_min_y)  # Optimierte Höhe
        
        logger.info(f"Envelope detection complete for level {level}:")
        logger.info(f"  Vertical cropping: Y:{global_min_y} to Y:{global_max_y} (removed {global_min_y + (frames[0].height - global_max_y)}px)")
        logger.info(f"  Horizontal: Keeping full width ({envelope_width}px)")
        logger.info(f"  Final envelope: {envelope_width}x{envelope_height} (was {frames[0].width}x{frames[0].height})")
        
        # SCHRITT 2: Verwende das erste Frame als Referenz für Positionierung
        reference_frame = frames[0]
        reference_info = frame_analyses[0]
        
        # Determine final canvas size for this level
        canvas, pos_info = self.create_canvas_for_level(level)
        target_width = pos_info["canvas_width"]
        target_height = pos_info["canvas_height"]
        
        # SCHRITT 3: Berechne optimale Canvas-Größe und Skalierung
        scale_factor = pos_info["scale_factor"]
        
        if self.config.get("dynamic_sizing", {}).get("enabled", True) and has_any_content:
            # Minimales Padding um den Mech
            min_padding = self.config.get("dynamic_sizing", {}).get("smart_cropping", {}).get("min_padding", 5)
            
            # Berechne gewünschte Mech-Größe basierend auf Level (ORIGINAL QUALITÄT BEIBEHALTEN)
            # Mech behält ursprüngliche Qualität, aber wird auf kleinerem Canvas gerendert
            # Levels 1-4: kleinere Canvas aber volle Mech-Qualität
            # Levels 5-8: mittlere Canvas aber volle Mech-Qualität
            # Levels 9-11: große Canvas aber volle Mech-Qualität
            if level <= 4:
                target_mech_height = 200  # Original Mech-Qualität beibehalten
            elif level <= 8:
                target_mech_height = 300  # Original Mech-Qualität beibehalten
            else:
                target_mech_height = 400  # Original Mech-Qualität beibehalten
                
            # Skaliere basierend auf der geschätzten Nachrichtenbreite
            # Nachrichtenbreite für deutsche Version: ~320px
            estimated_message_width = 320  # Basierend auf "Klicke auf +, um die Mech-Details zu sehen"
            
            # Berechne Skalierung basierend auf beiden Dimensionen
            height_scale = target_mech_height / envelope_height if envelope_height > 0 else 1.0
            # Mech sollte etwa 90% der Nachrichtenbreite nutzen
            width_scale = (estimated_message_width * 0.9) / envelope_width if envelope_width > 0 else 1.0
            
            # Verwende die kleinere Skalierung, damit der Mech in beide Dimensionen passt
            final_scale = min(height_scale, width_scale) * scale_factor
            
            # Berechne finale Mech-Größe nach Skalierung
            final_mech_width = int(envelope_width * final_scale)
            final_mech_height = int(envelope_height * final_scale)
            
            # OPTIMALE Canvas-Größe: 
            # Breite basierend auf der Nachrichtenlänge
            # Discord verwendet etwa 7-8px pro Zeichen in der Standard-Schrift
            
            # Bestimme die Nachrichtenlänge basierend auf Sprache
            # Deutsch: "Klicke auf +, um die Mech-Details zu sehen" = 44 Zeichen
            # Englisch: "Click + to view Mech details" = 29 Zeichen
            # Französisch: könnte noch länger sein
            
            # Approximiere die Breite basierend auf der längsten erwarteten Nachricht
            # Discord Desktop: ~7px pro Zeichen + Padding
            # Mobile: Andere Skalierung, aber proportional
            
            chars_per_message = {
                "de": 44,  # "Klicke auf +, um die Mech-Details zu sehen"
                "en": 29,  # "Click + to view Mech details"
                "fr": 40,  # Geschätzt für Französisch
            }
            
            # Discord nutzt Whitney Font mit proportionaler Breite
            # Durchschnittliche Breiten in Discord Desktop (16px Schriftgröße):
            # Schmale Zeichen (i,l,t,f,r): ~4-5px
            # Normale Zeichen (a,e,n,s,c,h): ~7-8px  
            # Breite Zeichen (m,w,M,W): ~10-12px
            # Leerzeichen: ~4px
            # Sonderzeichen (+): ~8px
            
            # Genauere Berechnung für die deutsche Nachricht:
            # "Klicke auf +, um die Mech-Details zu sehen" 
            message_de = "Klicke auf +, um die Mech-Details zu sehen"
            message_en = "Click + to view Mech details"
            
            # Verwende die deutsche Version als Basis (längste)
            # Approximation: Durchschnitt 7px pro Zeichen ist realistisch
            char_count = len(message_de)
            avg_char_width = 6.5  # Etwas konservativer für deutsche Texte
            
            # Discord Field Name hat etwas Bold-Effekt, also +10%
            estimated_message_width = int(char_count * avg_char_width * 1.1)
            
            # Die tatsächliche Breite in Discord Desktop ist etwa 320-350px für die deutsche Nachricht
            optimal_canvas_width = min(estimated_message_width, 350)  # Realistischer Wert
            optimal_canvas_width = max(optimal_canvas_width, 280)  # Min für kurze Nachrichten
            optimal_canvas_height = final_mech_height + (min_padding * 2)  # Nur vertikales Padding
            
            # Begrenze Canvas-Größe auf sinnvolle Werte
            optimal_canvas_width = max(128, min(optimal_canvas_width, 512))
            optimal_canvas_height = max(128, min(optimal_canvas_height, 512))
            
            logger.info(f"Message-width optimized canvas:")
            logger.info(f'  Message text: "{message_de}"')
            logger.info(f"  Estimated message width: ~{estimated_message_width}px")
            logger.info(f"  Calculated canvas width: {optimal_canvas_width}px")
            logger.info(f"  Envelope: {envelope_width}x{envelope_height}")
            logger.info(f"  Scale factor: {final_scale:.3f}")
            logger.info(f"  Final mech size: {final_mech_width}x{final_mech_height}")
            logger.info(f"  Canvas: {optimal_canvas_width}x{optimal_canvas_height}px")
            
            # Override die Standard-Canvas-Größe mit der optimalen Größe
            target_width = optimal_canvas_width
            target_height = optimal_canvas_height
        else:
            # Fixed scaling fallback
            final_scale = scale_factor
            final_mech_width = int(envelope_width * final_scale)
            final_mech_height = int(envelope_height * final_scale)
        
        # SCHRITT 4: Erstelle optimal zugeschnittene Frames
        logger.info(f"Creating optimally cropped frames...")
        
        for i, frame in enumerate(frames):
            # SCHRITT 4a: Schneide das Frame auf die globale Envelope zu
            # Stelle sicher, dass Crop-Bereich innerhalb der Frame-Grenzen liegt
            crop_left = max(0, int(global_min_x))
            crop_top = max(0, int(global_min_y))
            crop_right = min(frame.width, int(global_max_x))
            crop_bottom = min(frame.height, int(global_max_y))
            
            # Sicherheitscheck: Crop-Bereich muss gültig sein
            if crop_right > crop_left and crop_bottom > crop_top:
                frame_cropped = frame.crop((crop_left, crop_top, crop_right, crop_bottom))
                logger.debug(f"Frame {i}: cropped from {frame.width}x{frame.height} "
                           f"to {frame_cropped.width}x{frame_cropped.height}")
            else:
                # Fallback: verwende original frame
                frame_cropped = frame
                logger.warning(f"Frame {i}: invalid crop bounds, using original")
            
            # SCHRITT 4b: Skaliere das zugeschnittene Frame
            scaled_width = int(frame_cropped.width * final_scale)
            scaled_height = int(frame_cropped.height * final_scale)
            
            resample_mode = Image.NEAREST if final_scale < 1.0 else Image.LANCZOS
            frame_scaled = frame_cropped.resize((scaled_width, scaled_height), resample_mode)
            
            # SCHRITT 4c: Positioniere auf dem optimalen Canvas
            # Horizontal: ZENTRIERT auf Discord Message Width
            # Vertikal: Minimales Padding
            if self.config.get("dynamic_sizing", {}).get("enabled", True) and has_any_content:
                min_padding = self.config.get("dynamic_sizing", {}).get("smart_cropping", {}).get("min_padding", 5)
                
                # X-Position: Zentriert auf der Discord-Breite
                # Der Mech wird in der Mitte der Discord-Nachricht positioniert
                canvas_x = (target_width - scaled_width) // 2
                
                # Falls das cropped Frame eine andere X-Position hatte (für Animation),
                # berechne den Offset relativ zur Original-Position
                if 'crop_left' in locals() and crop_left > 0:
                    # Behalte relative Position aus dem Original Frame
                    original_center = frames[0].width // 2
                    cropped_center = (crop_left + crop_right) // 2
                    offset = cropped_center - original_center
                    canvas_x += int(offset * final_scale)
                
                # Y-Position: Minimales Padding oben/unten
                if reference_info.get("is_grounded", False):
                    # Grounded: Am unteren Rand mit minimalem Padding
                    canvas_y = target_height - scaled_height - min_padding
                else:
                    # Floating: Zentriert mit minimalem Padding
                    canvas_y = (target_height - scaled_height) // 2
            else:
                # Fallback: Standard-Zentrierung
                canvas_x = (target_width - scaled_width) // 2
                canvas_y = (target_height - scaled_height) // 2
            
            # Bounds checking (sollte bei optimalem Canvas nicht nötig sein)
            canvas_x = max(0, min(canvas_x, target_width - scaled_width))
            canvas_y = max(0, min(canvas_y, target_height - scaled_height))
            
            # SCHRITT 4d: Erstelle finalen Frame
            final_canvas = Image.new('RGBA', (target_width, target_height), (0, 0, 0, 0))
            
            if frame_scaled.mode == 'RGBA':
                final_canvas.paste(frame_scaled, (canvas_x, canvas_y), frame_scaled)
            else:
                final_canvas.paste(frame_scaled, (canvas_x, canvas_y))
            
            prepared_frames.append(final_canvas)
            
            if i == 0:  # Log nur für das erste Frame
                logger.info(f"Frame processing complete:")
                logger.info(f"  Cropped: {frame.width}x{frame.height} → {frame_cropped.width}x{frame_cropped.height}")
                logger.info(f"  Scaled: {frame_cropped.width}x{frame_cropped.height} → {scaled_width}x{scaled_height}")
                logger.info(f"  Positioned: ({canvas_x}, {canvas_y}) on {target_width}x{target_height} canvas")
                
                # Berechne vertikale Einsparung
                original_height = frame.height
                cropped_height = frame_cropped.height
                vertical_savings = original_height - cropped_height
                savings_percent = (vertical_savings / original_height) * 100 if original_height > 0 else 0
                logger.info(f"  Vertical efficiency: Removed {vertical_savings}px ({savings_percent:.1f}%) from top/bottom")
        
        # SCHRITT 5: Optimize frames if requested
        if optimize and len(prepared_frames) > 1:
            # Remove duplicate frames
            unique_frames = []
            last_frame = None
            for frame in prepared_frames:
                if last_frame is None or not self._images_equal(frame, last_frame):
                    unique_frames.append(frame)
                last_frame = frame
            
            if len(unique_frames) < len(prepared_frames):
                logger.info(f"Optimized animation: {len(prepared_frames)} -> {len(unique_frames)} frames")
                prepared_frames = unique_frames
        
        # SCHRITT 6: Save detected envelope info for future use
        if has_any_content:
            # Save the envelope dimensions instead of individual frame size
            self.save_size_info(
                level,
                envelope_width,
                envelope_height
            )
            
            # Update config with optimized envelope info
            try:
                level_config = self.config.get("mech_sizes_by_level", {}).get(str(level), {})
                level_config["envelope_bounds"] = {
                    "width": envelope_width,
                    "height": envelope_height,
                    "crop_left": int(global_min_x),
                    "crop_top": int(global_min_y),
                    "crop_right": int(global_max_x),
                    "crop_bottom": int(global_max_y),
                    "efficiency_percent": savings_percent if 'savings_percent' in locals() else 0
                }
                logger.debug(f"Saved envelope info for level {level}")
            except Exception as e:
                logger.warning(f"Could not save envelope info: {e}")
        
        logger.info(f"Animation preparation complete: {len(prepared_frames)} frames ready")
        return prepared_frames
    
    def _images_equal(self, img1: Image.Image, img2: Image.Image) -> bool:
        """Check if two images are identical."""
        if img1.size != img2.size or img1.mode != img2.mode:
            return False
        
        # Convert to bytes for comparison
        buf1 = BytesIO()
        buf2 = BytesIO()
        img1.save(buf1, format='PNG')
        img2.save(buf2, format='PNG')
        return buf1.getvalue() == buf2.getvalue()
    
    def save_size_info(self, level: int, width: int, height: int) -> None:
        """Save detected size information for a mech level."""
        try:
            # Update config with detected sizes
            if str(level) in self.config.get("mech_sizes_by_level", {}):
                self.config["mech_sizes_by_level"][str(level)]["expected_width"] = width
                self.config["mech_sizes_by_level"][str(level)]["expected_height"] = height
                
                # Save updated config
                with self.config_path.open('w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                    
                logger.info(f"Saved size info for level {level}: {width}x{height}")
        except Exception as e:
            logger.error(f"Error saving size info: {e}")


# Global instance
_handler_instance = None

def get_dynamic_image_handler() -> DynamicImageHandler:
    """Get the singleton dynamic image handler instance."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = DynamicImageHandler()
    return _handler_instance