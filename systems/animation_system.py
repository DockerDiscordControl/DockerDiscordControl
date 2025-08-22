# -*- coding: utf-8 -*-
"""
Animation System - Creates visual representations of mech state

The animation system combines all mech systems to create animated visuals:
- Loads appropriate sprites based on evolution level
- Applies visual effects based on speed level (Glvl)
- Creates animated WebP files for Discord
- Handles special cases (TRANSCENDENT mode, offline state)
- Manages encrypted sprite loading and caching

Visual Effects by Speed Level:
- Glvl 0: Dead/offline mech (darkened, no effects)
- Glvl 1-29: Basic animation
- Glvl 30+: Speed lines
- Glvl 50+: Glow effects
- Glvl 90+: Lightning effects  
- Glvl 101: TRANSCENDENT (rainbow portals, reality tears)
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
from PIL import Image, ImageDraw
import discord
from io import BytesIO
import math
import logging
from utils.logging_utils import get_module_logger

logger = get_module_logger('animation_system')


class AnimationSystem:
    """
    Core animation system for mech visuals
    
    Responsibilities:
    - Load and cache sprites for different evolution levels
    - Create animated WebP files based on mech state
    - Apply visual effects based on speed level
    - Handle TRANSCENDENT mode special effects
    - Manage file size and optimization
    """
    
    def __init__(self):
        """Initialize the animation system"""
        self.width = 200          # Canvas width
        self.height = 100         # Canvas height
        self.frames = 6           # Number of animation frames
        self.max_file_size = 500_000  # 500KB limit
        
        # Cache for loaded spritesheets by evolution level
        self.sprite_cache = {}
        self.sprite_width = 0
        self.sprite_height = 0
        
        # Load default sprite and set dimensions
        self._load_default_sprite()
        
        logger.info(f"Animation system initialized: {self.width}x{self.height}, {self.frames} frames")
    
    # ========================================
    # SPRITE LOADING AND CACHING
    # ========================================
    
    def _load_default_sprite(self):
        """Load default sprite and set sprite dimensions"""
        try:
            # Try loading encoded default sprite
            default_sprite = self._load_encoded_sprite("default")
            
            # Fallback to regular PNG
            if not default_sprite:
                sprite_path = Path("app/static/animatedmech.png")
                if sprite_path.exists():
                    default_sprite = Image.open(sprite_path).convert("RGBA")
                    logger.info("Loaded default PNG sprite")
            
            if default_sprite:
                self.sprite_cache[0] = default_sprite
                
                # Set sprite dimensions (assuming 2x3 grid)
                sheet_width, sheet_height = default_sprite.size
                self.sprite_width = sheet_width // 3   # 3 columns
                self.sprite_height = sheet_height // 2  # 2 rows
                
                logger.info(f"Sprite dimensions: {self.sprite_width}x{self.sprite_height}")
            else:
                logger.error("Could not load any default sprite")
                
        except Exception as e:
            logger.error(f"Error loading default sprite: {e}")
    
    def _load_encoded_sprite(self, sprite_name: str) -> Optional[Image.Image]:
        """Load an encoded .mech sprite file"""
        try:
            from utils.mech_sprite_encoder import decode_sprite_from_file
            
            encoded_path = Path(f"app/static/mechs/{sprite_name}.mech")
            if encoded_path.exists():
                sprite = decode_sprite_from_file(str(encoded_path))
                if sprite:
                    logger.debug(f"Loaded encoded sprite: {sprite_name}")
                    return sprite.convert("RGBA")
            
            return None
            
        except Exception as e:
            logger.error(f"Error loading encoded sprite {sprite_name}: {e}")
            return None
    
    def get_sprite_for_evolution(self, evolution_level: int) -> Optional[Image.Image]:
        """
        Get sprite for specific evolution level with caching
        
        Args:
            evolution_level: Evolution level (1-11)
            
        Returns:
            PIL Image object or None if not found
        """
        # Check cache first
        if evolution_level in self.sprite_cache:
            return self.sprite_cache[evolution_level]
        
        try:
            # Try loading encoded sprite for this level
            sprite = self._load_encoded_sprite(f"lvl_{evolution_level}")
            
            # Fallback to PNG file
            if not sprite:
                png_path = Path(f"app/static/mech_sprites/mech_level_{evolution_level}.png")
                if png_path.exists():
                    sprite = Image.open(png_path).convert("RGBA")
                    logger.debug(f"Loaded PNG sprite for level {evolution_level}")
            
            # Cache the sprite (or None if not found)
            if sprite:
                self.sprite_cache[evolution_level] = sprite
                return sprite
            else:
                # Use default sprite as fallback
                logger.debug(f"No sprite for level {evolution_level}, using default")
                return self.sprite_cache.get(0)
                
        except Exception as e:
            logger.error(f"Error loading sprite for level {evolution_level}: {e}")
            return self.sprite_cache.get(0)  # Return default
    
    def extract_sprite_frame(self, evolution_level: int, frame_index: int) -> Optional[Image.Image]:
        """
        Extract specific frame from evolution level sprite
        
        Args:
            evolution_level: Evolution level (1-11, 0 for default)
            frame_index: Frame number (0-5)
            
        Returns:
            PIL Image of the frame or None
        """
        sprite_sheet = self.get_sprite_for_evolution(evolution_level)
        if not sprite_sheet:
            return None
        
        # Calculate frame position in 2x3 grid
        col = frame_index % 3
        row = frame_index // 3
        
        left = col * self.sprite_width
        top = row * self.sprite_height
        right = left + self.sprite_width
        bottom = top + self.sprite_height
        
        return sprite_sheet.crop((left, top, right, bottom))
    
    # ========================================
    # MAIN ANIMATION CREATION
    # ========================================
    
    async def create_mech_animation(self, 
                                   evolution_level: int, 
                                   speed_level: int,
                                   donor_name: str = "",
                                   amount: str = "") -> discord.File:
        """
        Create complete mech animation based on evolution and speed
        
        Args:
            evolution_level: Current mech evolution level (1-11)
            speed_level: Current speed level (Glvl 0-101)
            donor_name: Name of donor (for logging)
            amount: Donation amount (for logging)
            
        Returns:
            Discord file with animated WebP
        """
        try:
            logger.info(f"Creating mech animation: Evolution {evolution_level}, "
                       f"Glvl {speed_level}, Donor: {donor_name}")
            
            # Handle offline state
            if speed_level <= 0:
                return await self._create_offline_animation(evolution_level)
            
            # Create animation frames
            frames = []
            for frame_index in range(self.frames):
                frame_image = self._create_animation_frame(
                    evolution_level, speed_level, frame_index
                )
                if frame_image:
                    frames.append(frame_image)
            
            if not frames:
                return self._create_fallback_animation(donor_name, amount)
            
            # Create WebP animation
            return self._create_webp_animation(frames, speed_level)
            
        except Exception as e:
            logger.error(f"Error creating mech animation: {e}")
            return self._create_fallback_animation(donor_name, amount)
    
    def _create_animation_frame(self, evolution_level: int, speed_level: int, frame_index: int) -> Optional[Image.Image]:
        """Create a single animation frame"""
        # Create background
        img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
        
        # Get sprite frame for this evolution level
        sprite = self.extract_sprite_frame(evolution_level, frame_index)
        if not sprite:
            return None
        
        # Scale sprite based on speed (subtle effect)
        base_scale = 0.24  # Base scale for visibility
        speed_scale_factor = 1.0 + (speed_level * 0.0003)  # Very subtle scaling
        
        new_width = int(self.sprite_width * base_scale * speed_scale_factor)
        new_height = int(self.sprite_height * base_scale * speed_scale_factor)
        sprite = sprite.resize((new_width, new_height), Image.NEAREST)
        
        # Center sprite on canvas
        x = (self.width - new_width) // 2
        y = (self.height - new_height) // 2
        
        # Apply visual effects based on speed level
        self._apply_visual_effects(img, sprite, x, y, speed_level, frame_index)
        
        # Paste main sprite
        img.paste(sprite, (x, y), sprite)
        
        return img
    
    # ========================================
    # VISUAL EFFECTS BY SPEED LEVEL
    # ========================================
    
    def _apply_visual_effects(self, img: Image.Image, sprite: Image.Image, 
                             sprite_x: int, sprite_y: int, speed_level: int, frame_index: int):
        """Apply visual effects based on speed level"""
        
        # TRANSCENDENT MODE (Glvl 101) - Reality bends!
        if speed_level == 101:
            self._apply_transcendent_effects(img, frame_index)
            return
        
        # Glow effects for high speeds
        if speed_level >= 50:
            self._apply_glow_effects(img, sprite, sprite_x, sprite_y, speed_level, frame_index)
        
        # Speed lines for medium-high speeds
        if speed_level >= 30:
            self._apply_speed_lines(img, speed_level, frame_index)
        
        # Lightning effects for extreme speeds
        if speed_level >= 90:
            self._apply_lightning_effects(img, speed_level, frame_index)
    
    def _apply_transcendent_effects(self, img: Image.Image, frame_index: int):
        """Apply TRANSCENDENT mode effects (Glvl 101)"""
        draw = ImageDraw.Draw(img)
        center_x = self.width // 2
        center_y = self.height // 2
        
        # Rotating portal particles
        for ring in range(5):
            radius = 30 + ring * 15
            for angle_offset in range(0, 360, 30):
                angle = (angle_offset + frame_index * 10 * (ring + 1)) % 360
                rad = math.radians(angle)
                x = center_x + int(radius * math.cos(rad))
                y = center_y + int(radius * math.sin(rad))
                
                # Rainbow portal particles
                rainbow_colors = [
                    (255, 0, 0), (255, 127, 0), (255, 255, 0),
                    (0, 255, 0), (0, 0, 255), (148, 0, 211)
                ]
                color = rainbow_colors[(frame_index + ring) % len(rainbow_colors)]
                draw.ellipse([x-3, y-3, x+3, y+3], fill=color + (255,))
        
        # Reality tears - diagonal lines across screen
        for i in range(10):
            tear_offset = (frame_index * 5) % self.width
            x_start = (i * 20 + tear_offset) % self.width
            draw.line([x_start, 0, x_start + 10, self.height], 
                     fill=(255, 0, 255, 150), width=1)
        
        # Flickering "TRANSCENDENT" text
        if frame_index % 3 == 0:
            draw.text((5, 5), "TRANSCENDENT", fill=(255, 255, 255, 255))
    
    def _apply_glow_effects(self, img: Image.Image, sprite: Image.Image, 
                           sprite_x: int, sprite_y: int, speed_level: int, frame_index: int):
        """Apply glow effects for high speed levels"""
        # Create glow sprite (slightly larger)
        glow_sprite = sprite.copy()
        glow_width = sprite.width + 10
        glow_height = sprite.height + 10
        glow_sprite = glow_sprite.resize((glow_width, glow_height), Image.NEAREST)
        
        glow_x = sprite_x - 5
        glow_y = sprite_y - 5
        
        # Apply glow with different colors based on speed
        for offset in [(0,0), (1,0), (0,1), (1,1), (-1,0), (0,-1), (-1,-1), (1,-1), (-1,1)]:
            glow_pos = (glow_x + offset[0], glow_y + offset[1])
            
            if speed_level >= 100:
                # Divine gold glow
                img.paste((255, 255, 0, 80), glow_pos, glow_sprite)
            elif speed_level >= 90:
                # Gold glow for near-lightspeed
                img.paste((255, 215, 0, 60), glow_pos, glow_sprite)
            elif speed_level >= 70:
                # Purple glow for running speeds
                img.paste((128, 0, 255, 40), glow_pos, glow_sprite)
            else:
                # Cyan glow for fast walking
                img.paste((0, 255, 255, 30), glow_pos, glow_sprite)
    
    def _apply_speed_lines(self, img: Image.Image, speed_level: int, frame_index: int):
        """Apply speed lines behind mech"""
        draw = ImageDraw.Draw(img)
        center_y = self.height // 2
        
        num_lines = min(max(1, (speed_level - 30) // 5), 15)  # 1-15 lines
        
        for i in range(num_lines):
            line_x = 20 + i * 10
            line_length = 10 + (speed_level // 5)
            opacity = max(50, min(255, 100 + speed_level))
            
            # Animated offset
            offset = (frame_index * (1 + speed_level // 20)) % 15
            start_x = line_x - offset
            end_x = start_x + line_length
            
            # Color based on speed level
            if speed_level >= 100:
                color = (255, 255, 255, opacity)  # White
            elif speed_level >= 90:
                color = (255, 215, 0, opacity)   # Gold
            elif speed_level >= 70:
                color = (128, 0, 255, opacity)   # Purple
            elif speed_level >= 50:
                color = (0, 255, 255, opacity)   # Cyan
            else:
                color = (0, 255, 0, opacity)     # Green
            
            draw.line([start_x, center_y - 2, end_x, center_y - 2], fill=color, width=2)
            draw.line([start_x, center_y + 2, end_x, center_y + 2], fill=color, width=2)
    
    def _apply_lightning_effects(self, img: Image.Image, speed_level: int, frame_index: int):
        """Apply lightning effects for extreme speeds"""
        if frame_index % 2 == 0:  # Flickering effect
            draw = ImageDraw.Draw(img)
            bolt_x = self.width - 40
            bolt_y = 20
            
            # Draw lightning bolt
            draw.line([bolt_x, bolt_y, bolt_x + 10, bolt_y + 15], 
                     fill=(255, 255, 0, 255), width=3)
            draw.line([bolt_x + 10, bolt_y + 15, bolt_x + 5, bolt_y + 25], 
                     fill=(255, 255, 0, 255), width=3)
            draw.line([bolt_x + 5, bolt_y + 25, bolt_x + 15, bolt_y + 35], 
                     fill=(255, 255, 0, 255), width=3)
    
    # ========================================
    # SPECIAL ANIMATION STATES
    # ========================================
    
    async def _create_offline_animation(self, evolution_level: int) -> discord.File:
        """Create static offline/dead mech animation"""
        try:
            # Use Level 1 (SCRAP MECH) sprite for offline state
            sprite = self.extract_sprite_frame(max(1, evolution_level), 0)
            if not sprite:
                return self._create_fallback_animation("", "0€")
            
            # Create dark background
            img = Image.new('RGBA', (self.width, self.height), (20, 20, 25, 255))
            
            # Scale and darken sprite
            base_scale = 0.24
            base_width = int(self.sprite_width * base_scale)
            base_height = int(self.sprite_height * base_scale)
            sprite = sprite.resize((base_width, base_height), Image.NEAREST)
            
            # Darken the sprite
            dead_sprite = Image.new('RGBA', sprite.size)
            sprite_data = sprite.load()
            dead_sprite_data = dead_sprite.load()
            
            for y in range(sprite.size[1]):
                for x in range(sprite.size[0]):
                    r, g, b, a = sprite_data[x, y]
                    gray = int((r + g + b) / 3 * 0.3)  # Very dark
                    dead_sprite_data[x, y] = (gray, gray, gray, a)
            
            # Center the sprite
            x = (self.width - base_width) // 2
            y = (self.height - base_height) // 2
            img.paste(dead_sprite, (x, y), dead_sprite)
            
            # Add "NO FUEL" text
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "NO FUEL", fill=(80, 80, 80, 255))
            draw.text((10, self.height - 25), "$0", fill=(60, 60, 60, 255))
            
            # Create static WebP
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            logger.info("Created offline mech animation")
            return discord.File(buffer, filename="offline_mech.webp")
            
        except Exception as e:
            logger.error(f"Error creating offline animation: {e}")
            return self._create_fallback_animation("", "0€")
    
    # ========================================
    # WEBP CREATION AND OPTIMIZATION
    # ========================================
    
    def _create_webp_animation(self, frames: List[Image.Image], speed_level: int) -> discord.File:
        """Create optimized WebP animation from frames"""
        buffer = BytesIO()
        
        # Calculate animation duration based on speed level
        from systems.speed_system import SpeedSystem
        speed_sys = SpeedSystem()
        duration = speed_sys.get_animation_duration(speed_level)
        
        # Create WebP animation
        frames[0].save(
            buffer,
            format='WebP',
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            quality=85,
            method=6,
            lossless=False
        )
        
        buffer.seek(0)
        file_size = buffer.getbuffer().nbytes
        
        # Check file size and optimize if needed
        if file_size > self.max_file_size:
            logger.warning(f"Animation too large ({file_size} bytes), optimizing")
            return self._create_optimized_animation(frames, speed_level)
        
        logger.info(f"WebP animation created: {file_size} bytes, {duration}ms duration")
        buffer.seek(0)
        return discord.File(buffer, filename="mech_animation.webp")
    
    def _create_optimized_animation(self, frames: List[Image.Image], speed_level: int) -> discord.File:
        """Create smaller optimized animation"""
        buffer = BytesIO()
        
        from systems.speed_system import SpeedSystem
        speed_sys = SpeedSystem()
        duration = speed_sys.get_animation_duration(speed_level)
        
        frames[0].save(
            buffer,
            format='WebP',
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            quality=60,  # Lower quality
            method=4,
            lossless=False
        )
        
        buffer.seek(0)
        logger.info("Created optimized animation")
        return discord.File(buffer, filename="mech_animation_small.webp")
    
    def _create_fallback_animation(self, donor_name: str, amount: str) -> discord.File:
        """Create simple fallback animation when sprite loading fails"""
        try:
            img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
            draw = ImageDraw.Draw(img)
            
            # Draw simple mech shape
            center_x = self.width // 2
            center_y = self.height // 2
            
            # Body
            draw.rectangle([center_x-20, center_y-15, center_x+20, center_y+25], 
                          fill=(100, 100, 100, 255), outline=(255, 255, 255, 255))
            
            # Head
            draw.ellipse([center_x-12, center_y-25, center_x+12, center_y-5], 
                        fill=(100, 100, 100, 255), outline=(255, 255, 255, 255))
            
            # Eyes
            draw.ellipse([center_x-8, center_y-20, center_x-4, center_y-16], fill=(0, 255, 255, 255))
            draw.ellipse([center_x+4, center_y-20, center_x+8, center_y-16], fill=(0, 255, 255, 255))
            
            # Error text
            draw.text((5, 5), "FALLBACK", fill=(255, 100, 100, 255))
            
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            logger.info("Created fallback animation")
            return discord.File(buffer, filename="fallback_mech.webp")
            
        except Exception as e:
            logger.error(f"Error creating fallback animation: {e}")
            # Ultra-basic fallback
            buffer = BytesIO()
            basic_img = Image.new('RGBA', (100, 50), (47, 49, 54, 255))
            basic_img.save(buffer, format='WebP')
            buffer.seek(0)
            return discord.File(buffer, filename="basic_fallback.webp")