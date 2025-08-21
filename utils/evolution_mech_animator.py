# -*- coding: utf-8 -*-
"""
Evolution-based Mech Animator - Uses custom mech evolution images
"""

import os
import asyncio
import discord
from typing import Optional
from io import BytesIO
from PIL import Image
from utils.logging_utils import get_module_logger
from utils.mech_evolutions import get_evolution_level, get_evolution_info, get_mech_filename

logger = get_module_logger('evolution_mech_animator')

class EvolutionMechAnimator:
    def __init__(self):
        self.assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'mech_evolutions')
        self.sprite_size = (341, 512)  # Size of each frame
        self.grid_size = (2, 3)  # 2x3 grid = 6 frames
        self.max_file_size = 8 * 1024 * 1024  # 8MB limit for Discord
        
        logger.info(f"Evolution Mech Animator initialized, assets dir: {self.assets_dir}")
    
    def _load_evolution_spritesheet(self, evolution_level: int) -> Optional[Image.Image]:
        """Load the spritesheet for a specific evolution level."""
        filename = get_mech_filename(evolution_level)
        filepath = os.path.join(self.assets_dir, filename)
        
        try:
            if os.path.exists(filepath):
                image = Image.open(filepath)
                logger.info(f"Loaded evolution spritesheet: {filename} ({image.size})")
                return image
            else:
                logger.warning(f"Evolution spritesheet not found: {filepath}")
                return None
        except Exception as e:
            logger.error(f"Error loading evolution spritesheet {filename}: {e}")
            return None
    
    def _extract_frames(self, spritesheet: Image.Image) -> list:
        """Extract 6 frames from 2x3 grid spritesheet."""
        frames = []
        cols, rows = self.grid_size
        frame_width, frame_height = self.sprite_size
        
        for row in range(rows):
            for col in range(cols):
                x = col * frame_width
                y = row * frame_height
                
                # Extract frame
                frame = spritesheet.crop((x, y, x + frame_width, y + frame_height))
                frames.append(frame)
        
        logger.debug(f"Extracted {len(frames)} frames from spritesheet")
        return frames
    
    def _create_fallback_animation(self, evolution_level: int) -> discord.File:
        """Create a simple fallback animation when spritesheet is missing."""
        try:
            from PIL import ImageDraw, ImageFont
            
            # Create simple colored rectangle as fallback
            evolution_info = get_evolution_info(0)  # Get info for the level
            
            frames = []
            for i in range(6):
                img = Image.new('RGBA', self.sprite_size, (0, 0, 0, 0))  # Transparent
                draw = ImageDraw.Draw(img)
                
                # Draw simple rectangle with evolution color
                color = evolution_info['color']
                # Convert hex to RGB
                color_rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
                
                # Simple walking animation - just move the rectangle slightly
                offset = (i % 3) * 5  # Slight horizontal movement
                draw.rectangle([50 + offset, 100, 250 + offset, 400], 
                              fill=color_rgb + (255,), outline=(255, 255, 255, 255))
                
                # Add text
                try:
                    draw.text((70, 200), f"LVL {evolution_level}", fill=(255, 255, 255, 255))
                    draw.text((70, 230), "MISSING", fill=(255, 0, 0, 255))
                    draw.text((70, 250), "ARTWORK", fill=(255, 0, 0, 255))
                except:
                    pass  # If font fails, continue without text
                
                frames.append(img)
            
            # Create WebP animation
            buffer = BytesIO()
            frames[0].save(
                buffer,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=200,  # 200ms per frame
                loop=0,
                quality=85
            )
            
            buffer.seek(0)
            logger.info(f"Created fallback animation for evolution level {evolution_level}")
            return discord.File(buffer, filename=f"mech_evolution_{evolution_level}_fallback.webp")
            
        except Exception as e:
            logger.error(f"Error creating fallback animation: {e}")
            # Ultimate fallback - simple static image
            img = Image.new('RGBA', self.sprite_size, (100, 100, 100, 255))
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return discord.File(buffer, filename="mech_error.png")
    
    async def create_evolution_animation(self, donor_name: str, amount: str, total_donations: float) -> discord.File:
        """Create mech animation based on evolution level determined by donations."""
        try:
            # Determine evolution level
            evolution_level = get_evolution_level(total_donations)
            evolution_info = get_evolution_info(total_donations)
            
            logger.info(f"Creating evolution animation: Level {evolution_level} ({evolution_info['name']}) for {total_donations}$ donations")
            
            # Load spritesheet for this evolution
            spritesheet = self._load_evolution_spritesheet(evolution_level)
            
            if spritesheet is None:
                logger.warning(f"Using fallback animation for evolution level {evolution_level}")
                return self._create_fallback_animation(evolution_level)
            
            # Extract frames
            frames = self._extract_frames(spritesheet)
            
            if not frames:
                logger.error("No frames extracted from spritesheet")
                return self._create_fallback_animation(evolution_level)
            
            # Calculate animation speed based on current fuel (for speed effect)
            # Higher fuel = faster animation, but same evolution level
            speed_level = min(int(total_donations / 10), 101) if total_donations > 0 else 0
            
            if speed_level <= 0:
                duration = 600  # Very slow for dead mech
            else:
                # Map speed level 1-101 to duration 500ms-50ms
                duration = max(50, 500 - (speed_level * 4))
            
            # Create WebP animation
            buffer = BytesIO()
            frames[0].save(
                buffer,
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
                quality=85,
                method=6
            )
            
            buffer.seek(0)
            file_size = buffer.getbuffer().nbytes
            
            if file_size > self.max_file_size:
                logger.warning(f"Animation too large ({file_size} bytes), reducing quality")
                # Reduce quality and try again
                buffer = BytesIO()
                frames[0].save(
                    buffer,
                    format='WebP',
                    save_all=True,
                    append_images=frames[1:],
                    duration=duration,
                    loop=0,
                    quality=60,
                    method=4
                )
                buffer.seek(0)
                file_size = buffer.getbuffer().nbytes
            
            logger.info(f"Evolution animation created: Level {evolution_level}, {file_size} bytes, {duration}ms duration")
            buffer.seek(0)
            return discord.File(buffer, filename=f"mech_evolution_{evolution_level}.webp")
            
        except Exception as e:
            logger.error(f"Error creating evolution animation: {e}", exc_info=True)
            return self._create_fallback_animation(0)

# Singleton instance
_evolution_animator = None

def get_evolution_animator() -> EvolutionMechAnimator:
    """Get or create the singleton evolution animator."""
    global _evolution_animator
    if _evolution_animator is None:
        _evolution_animator = EvolutionMechAnimator()
    return _evolution_animator