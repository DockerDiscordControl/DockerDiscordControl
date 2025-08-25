# -*- coding: utf-8 -*-
"""
Sprite-based Mech Animator - Uses real spritesheet for mech animations
"""

from PIL import Image, ImageDraw, ImageFont
import discord
from io import BytesIO
import logging
from pathlib import Path
from utils.logging_utils import get_module_logger

logger = get_module_logger('sprite_mech_animator')

class SpriteMechAnimator:
    """Creates animations using the actual mech spritesheet"""
    
    def __init__(self):
        self.width = 200  # Smaller canvas for smaller mech
        self.height = 100  # Proportional height  
        self.frames = 6   # Match spritesheet frames
        self.max_file_size = 500_000  # 500KB limit
        
        # Cache for loaded spritesheets by level
        self.spritesheet_cache = {}
        self.sprite_width = 0
        self.sprite_height = 0
        
        # PERFORMANCE: Global animation cache - shared between Web UI and Discord
        self.animation_cache = {}
        self.cache_max_size = 20  # Limit memory usage
        
        # Load default spritesheet
        self.load_default_spritesheet()
        
    def load_default_spritesheet(self):
        """Load the default mech spritesheet as fallback"""
        try:
            # Try loading encoded version first
            from utils.mech_sprite_encoder import decode_sprite_from_file
            
            encoded_path = Path("app/static/mechs/default.mech")
            if encoded_path.exists():
                spritesheet = decode_sprite_from_file(str(encoded_path))
                if spritesheet:
                    self.spritesheet_cache[0] = spritesheet.convert("RGBA")
                    logger.info("Loaded encoded default mech sprite")
            
            # Fallback to regular PNG
            if 0 not in self.spritesheet_cache:
                sprite_path = Path("app/static/animatedmech.png")
                if sprite_path.exists():
                    self.spritesheet_cache[0] = Image.open(sprite_path).convert("RGBA")
                    logger.info("Loaded default PNG mech sprite")
            
            # Set sprite dimensions from default
            if 0 in self.spritesheet_cache:
                sheet_width, sheet_height = self.spritesheet_cache[0].size
                self.sprite_width = sheet_width // 3  # 3 columns
                self.sprite_height = sheet_height // 2  # 2 rows
                logger.info(f"Sprite dimensions: {self.sprite_width}x{self.sprite_height}")
                
        except Exception as e:
            logger.error(f"Error loading default spritesheet: {e}")
    
    def load_spritesheet_for_level(self, evolution_level: int):
        """Load spritesheet for specific evolution level"""
        if evolution_level in self.spritesheet_cache:
            return self.spritesheet_cache[evolution_level]
        
        try:
            from utils.mech_sprite_encoder import decode_sprite_from_file
            
            # Try loading encoded version
            encoded_path = Path(f"app/static/mechs/lvl_{evolution_level}.mech")
            if encoded_path.exists():
                spritesheet = decode_sprite_from_file(str(encoded_path))
                if spritesheet:
                    self.spritesheet_cache[evolution_level] = spritesheet.convert("RGBA")
                    logger.info(f"Loaded encoded sprite for level {evolution_level}")
                    return self.spritesheet_cache[evolution_level]
            
            # Try regular PNG as fallback
            png_path = Path(f"app/static/mech_sprites/mech_level_{evolution_level}.png")
            if png_path.exists():
                self.spritesheet_cache[evolution_level] = Image.open(png_path).convert("RGBA")
                logger.info(f"Loaded PNG sprite for level {evolution_level}")
                return self.spritesheet_cache[evolution_level]
            
            # Use default if no specific sprite found
            logger.debug(f"No sprite for level {evolution_level}, using default")
            return self.spritesheet_cache.get(0)
            
        except Exception as e:
            logger.error(f"Error loading spritesheet for level {evolution_level}: {e}")
            return self.spritesheet_cache.get(0)  # Return default
    
    def get_sprite_frame(self, frame_index: int, evolution_level: int = 0):
        """Extract a specific frame from the spritesheet
        
        Args:
            frame_index: The frame number (0-5)
            evolution_level: The mech evolution level for sprite selection
        """
        # Get the appropriate spritesheet for this level
        spritesheet = self.load_spritesheet_for_level(evolution_level)
        if not spritesheet:
            spritesheet = self.spritesheet_cache.get(0)  # Fallback to default
            
        if not spritesheet:
            return None
            
        # Calculate sprite position in 2x3 grid
        col = frame_index % 3
        row = frame_index // 3
        
        left = col * self.sprite_width
        top = row * self.sprite_height
        right = left + self.sprite_width
        bottom = top + self.sprite_height
        
        return spritesheet.crop((left, top, right, bottom))
    
    def create_donation_animation_sync(self, donor_name: str, amount: str, total_donations: float) -> bytes:
        """Create animated WebP synchronously for Web UI use"""
        try:
            # Same logic as async version but returns bytes directly
            from utils.mech_evolutions import get_evolution_level
            evolution_level = get_evolution_level(total_donations)
            
            if evolution_level < 1:
                evolution_level = 1
            elif evolution_level > 11:
                evolution_level = 11
                
            speed_level = self.calculate_speed_level(total_donations)
            if speed_level < 0:
                speed_level = 0
            elif speed_level > 101:
                speed_level = 101
                
            if total_donations <= 0:
                return self.create_dead_mech_animation_sync(donor_name)
            
            # Same caching logic
            cache_key = f"fuel_{total_donations:.2f}_evo_{evolution_level}_speed_{speed_level}"
            
            if cache_key in self.animation_cache:
                cached_data = self.animation_cache[cache_key]
                if cached_data and len(cached_data) > 0:
                    return cached_data
                else:
                    del self.animation_cache[cache_key]
            
            # Create frames (same logic as async version)
            frames = []
            
            for frame in range(self.frames):
                img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
                
                sprite = self.get_sprite_frame(frame, evolution_level)
                if sprite:
                    # Same sprite processing logic
                    base_scale = 0.24
                    base_width = int(self.sprite_width * base_scale)
                    base_height = int(self.sprite_height * base_scale)
                    
                    speed_scale_factor = 1.0 + (speed_level * 0.03)
                    new_width = int(base_width * speed_scale_factor)
                    new_height = int(base_height * speed_scale_factor)
                    
                    sprite = sprite.resize((new_width, new_height), Image.NEAREST)
                    
                    x = (self.width - new_width) // 2
                    y = (self.height - new_height) // 2
                    
                    # Same glow effects
                    if speed_level >= 50:
                        glow_sprite = sprite.copy()
                        glow_sprite = glow_sprite.resize((new_width + 10, new_height + 10), Image.NEAREST)
                        glow_x = x - 5
                        glow_y = y - 5
                        
                        for offset in [(0,0), (1,0), (0,1), (1,1), (-1,0), (0,-1), (-1,-1), (1,-1), (-1,1)]:
                            glow_pos = (glow_x + offset[0], glow_y + offset[1])
                            if speed_level == 101:
                                import random
                                rainbow_colors = [
                                    (255, 0, 0, 100), (255, 127, 0, 100), (255, 255, 0, 100),
                                    (0, 255, 0, 100), (0, 0, 255, 100), (75, 0, 130, 100),
                                    (148, 0, 211, 100), (255, 0, 255, 100),
                                ]
                                color = rainbow_colors[frame % len(rainbow_colors)]
                                img.paste(color, glow_pos, glow_sprite)
                            elif speed_level >= 100:
                                img.paste((255, 255, 0, 80), glow_pos, glow_sprite)
                            elif speed_level >= 90:
                                img.paste((255, 215, 0, 60), glow_pos, glow_sprite)
                            elif speed_level >= 70:
                                img.paste((128, 0, 255, 40), glow_pos, glow_sprite)
                            else:
                                img.paste((0, 255, 255, 30), glow_pos, glow_sprite)
                    
                    img.paste(sprite, (x, y), sprite)
                    self._add_speed_effects(img, speed_level, frame)
                
                frames.append(img)
            
            # Create WebP animation
            buffer = BytesIO()
            
            if speed_level <= 0:
                duration = 800
            elif speed_level == 101:
                duration = 25
            else:
                duration = max(50, 600 - (speed_level * 5.5))
            
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
            
            if file_size > self.max_file_size:
                return self._create_smaller_animation_sync(frames, speed_level)
            
            animation_bytes = buffer.getvalue()
            
            # Cache management
            if len(self.animation_cache) >= self.cache_max_size:
                if self.animation_cache:
                    oldest_key = next(iter(self.animation_cache))
                    del self.animation_cache[oldest_key]
            
            self.animation_cache[cache_key] = animation_bytes
            logger.info(f"Cached animation: {cache_key} ({len(animation_bytes)} bytes)")
            
            return animation_bytes
            
        except Exception as e:
            logger.error(f"Error creating sync sprite animation: {e}")
            return self.create_static_fallback_sync(donor_name, amount, speed_level)

    async def create_donation_animation(self, donor_name: str, amount: str, total_donations: float) -> discord.File:
        """Create animated WebP using real mech sprites with global caching"""
        try:
            # EDGE CASE: Safely get evolution level with boundaries
            try:
                from utils.mech_evolutions import get_evolution_level
                evolution_level = get_evolution_level(total_donations)
                
                # Validate evolution level boundaries
                if evolution_level < 1:
                    evolution_level = 1
                elif evolution_level > 11:
                    evolution_level = 11
                    
            except Exception as evo_error:
                logger.error(f"Error getting evolution level: {evo_error}")
                evolution_level = 1  # Safe fallback
            
            # EDGE CASE: Safely calculate speed level
            try:
                speed_level = self.calculate_speed_level(total_donations)
                if speed_level < 0:
                    speed_level = 0
                elif speed_level > 101:
                    speed_level = 101
            except Exception as speed_error:
                logger.error(f"Error calculating speed level: {speed_error}")
                speed_level = 1  # Safe fallback
            
            # EDGE CASE: Handle zero/negative fuel BEFORE caching
            if total_donations <= 0:
                logger.info(f"Zero fuel detected, creating dead mech animation")
                return await self.create_dead_mech_animation(donor_name)
            
            # PERFORMANCE: Create cache key based on fuel and evolution (not donor name)
            # This allows sharing between Web UI and Discord
            cache_key = f"fuel_{total_donations:.2f}_evo_{evolution_level}_speed_{speed_level}"
            
            # Check if we already have this animation cached
            if cache_key in self.animation_cache:
                cached_data = self.animation_cache[cache_key]
                logger.debug(f"Using cached animation for {cache_key}")
                
                # EDGE CASE: Safely create Discord.File from cached bytes
                try:
                    if cached_data and len(cached_data) > 0:
                        return discord.File(
                            BytesIO(cached_data), 
                            filename=f"mech_animation_{total_donations:.0f}.webp"
                        )
                    else:
                        logger.warning(f"Invalid cached data for {cache_key}, removing from cache")
                        del self.animation_cache[cache_key]
                        # Fall through to create new animation
                except Exception as cache_error:
                    logger.error(f"Error using cached animation: {cache_error}")
                    # Remove corrupted cache entry
                    if cache_key in self.animation_cache:
                        del self.animation_cache[cache_key]
                    # Fall through to create new animation
            
            logger.info(f"Creating new sprite mech animation for evolution: {evolution_level}, speed: {speed_level}, fuel: {total_donations}")
            frames = []
            
            for frame in range(self.frames):
                # Create background
                img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
                
                # Get sprite frame for current evolution level
                sprite = self.get_sprite_frame(frame, evolution_level)
                if sprite:
                    # Scale sprite to show full mech (50% bigger than 0.16)
                    base_scale = 0.24  # Scale down to ~82x123 pixels for full mech visibility
                    base_width = int(self.sprite_width * base_scale)
                    base_height = int(self.sprite_height * base_scale)
                    
                    # Then apply speed-based scaling (very subtle)
                    speed_scale_factor = 1.0 + (speed_level * 0.03)  # 1.0 to 1.18x max
                    new_width = int(base_width * speed_scale_factor)
                    new_height = int(base_height * speed_scale_factor)
                    
                    sprite = sprite.resize((new_width, new_height), Image.NEAREST)  # Keep pixel art crisp
                    
                    # Center sprite on canvas
                    x = (self.width - new_width) // 2
                    y = (self.height - new_height) // 2
                    
                    # Add glow effect for high speed levels
                    if speed_level >= 50:  # Start glow at level 50
                        glow_sprite = sprite.copy()
                        glow_sprite = glow_sprite.resize((new_width + 10, new_height + 10), Image.NEAREST)
                        glow_x = x - 5
                        glow_y = y - 5
                        
                        # Create glow by pasting multiple times with offset
                        for offset in [(0,0), (1,0), (0,1), (1,1), (-1,0), (0,-1), (-1,-1), (1,-1), (-1,1)]:
                            glow_pos = (glow_x + offset[0], glow_y + offset[1])
                            if speed_level == 101:
                                # TRANSCENDENT MODE - Rainbow reality-warping glow!
                                import random
                                rainbow_colors = [
                                    (255, 0, 0, 100),    # Red
                                    (255, 127, 0, 100),  # Orange
                                    (255, 255, 0, 100),  # Yellow
                                    (0, 255, 0, 100),    # Green
                                    (0, 0, 255, 100),    # Blue
                                    (75, 0, 130, 100),   # Indigo
                                    (148, 0, 211, 100),  # Violet
                                    (255, 0, 255, 100),  # Magenta
                                ]
                                color = rainbow_colors[frame % len(rainbow_colors)]
                                img.paste(color, glow_pos, glow_sprite)
                            elif speed_level >= 100:
                                # Divine gold glow for Godspeed
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
                    
                    # Paste main sprite
                    img.paste(sprite, (x, y), sprite)
                    
                    # Add speed effects
                    self._add_speed_effects(img, speed_level, frame)
                    
                    # No text overlay on animation anymore
                
                frames.append(img)
            
            # Create WebP animation
            buffer = BytesIO()
            
            # Calculate duration based on speed level (faster = shorter duration)
            # Scale for 100 levels: very slow at level 1, super fast at level 100
            if speed_level <= 0:
                duration = 800  # Very slow for offline/no fuel
            elif speed_level == 101:
                duration = 25  # TRANSCENDENT - Reality itself cannot keep up!
            else:
                # Map level 1-100 to duration 600ms-50ms
                duration = max(50, 600 - (speed_level * 5.5))
            
            frames[0].save(
                buffer, 
                format='WebP',
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
                quality=85,  # Higher quality for pixel art
                method=6,    # Best compression
                lossless=False
            )
            
            buffer.seek(0)
            file_size = buffer.getbuffer().nbytes
            
            if file_size > self.max_file_size:
                logger.warning(f"Animation too large ({file_size} bytes), reducing quality")
                return self._create_smaller_animation(frames, speed_level)
            
            logger.info(f"Sprite WebP animation created: {file_size} bytes")
            
            # PERFORMANCE: Cache the animation bytes for reuse
            buffer.seek(0)
            animation_bytes = buffer.getvalue()
            
            # EDGE CASE: Validate animation bytes before caching
            if not animation_bytes or len(animation_bytes) < 100:  # Minimum viable WebP size
                logger.error(f"Invalid animation created, size: {len(animation_bytes) if animation_bytes else 0}")
                return self.create_static_fallback(donor_name, amount, speed_level)
            
            # EDGE CASE: Manage cache size safely (LRU-like)
            if len(self.animation_cache) >= self.cache_max_size:
                try:
                    # Remove oldest entry safely
                    if self.animation_cache:  # Additional safety check
                        oldest_key = next(iter(self.animation_cache))
                        del self.animation_cache[oldest_key]
                        logger.debug(f"Removed old cache entry: {oldest_key}")
                except (StopIteration, KeyError) as e:
                    logger.warning(f"Cache management error: {e}, clearing cache")
                    self.animation_cache.clear()
            
            # EDGE CASE: Safely cache the animation
            try:
                self.animation_cache[cache_key] = animation_bytes
                logger.info(f"Cached animation: {cache_key} ({len(animation_bytes)} bytes)")
            except MemoryError:
                logger.error("Memory error caching animation, clearing cache")
                self.animation_cache.clear()
            except Exception as cache_err:
                logger.error(f"Error caching animation: {cache_err}")
            
            buffer.seek(0)
            return discord.File(buffer, filename="sprite_mech_donation.webp")
            
        except Exception as e:
            logger.error(f"Error creating sprite animation: {e}")
            return self.create_static_fallback(donor_name, amount, speed_level)
    
    async def create_dead_mech_animation(self, donor_name: str) -> discord.File:
        """Create static dead mech (no fuel)"""
        try:
            # Use first frame of Level 1 (SCRAP MECH) - it's already broken!
            sprite = self.get_sprite_frame(0, evolution_level=1)  # Static pose of scrap mech
            if not sprite:
                return self.create_static_fallback(donor_name, "0€", 0)
            
            # Scale sprite (50% bigger)
            base_scale = 0.24
            base_width = int(self.sprite_width * base_scale)
            base_height = int(self.sprite_height * base_scale)
            sprite = sprite.resize((base_width, base_height), Image.NEAREST)
            
            # Create dark image for "dead" mech
            img = Image.new('RGBA', (self.width, self.height), (20, 20, 25, 255))  # Darker background
            
            # Darken the sprite to make it look "off"
            dead_sprite = Image.new('RGBA', sprite.size)
            
            # Convert sprite to grayscale and darken
            sprite_data = sprite.load()
            dead_sprite_data = dead_sprite.load()
            
            for y in range(sprite.size[1]):
                for x in range(sprite.size[0]):
                    r, g, b, a = sprite_data[x, y]
                    
                    # Convert to grayscale and darken
                    gray = int((r + g + b) / 3 * 0.3)  # Very dark
                    
                    # Special handling for the bright eyes - turn them off
                    if (r + g + b > 400 and b > 150):  # Bright blue/white pixels (the eyes)
                        dead_sprite_data[x, y] = (30, 30, 35, a)  # Dark gray
                    else:
                        dead_sprite_data[x, y] = (gray, gray, gray, a)
            
            # Center the dead sprite
            x = (self.width - base_width) // 2
            y = (self.height - base_height) // 2
            img.paste(dead_sprite, (x, y), dead_sprite)
            
            # Add "NO FUEL" text
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "NO FUEL", fill=(80, 80, 80, 255))
            draw.text((10, self.height - 25), "$0", fill=(60, 60, 60, 255))
            
            # Create static WebP
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            logger.info("Created dead mech animation (no fuel)")
            return discord.File(buffer, filename="dead_mech.webp")
            
        except Exception as e:
            logger.error(f"Error creating dead mech animation: {e}")
            return self.create_static_fallback(donor_name, "0€", 0)
    
    def _add_speed_effects(self, img: Image, speed_level: int, frame: int):
        """Add visual effects based on speed level"""
        draw = ImageDraw.Draw(img)
        
        # TRANSCENDENT MODE - REALITY ITSELF BENDS!
        if speed_level == 101:
            # Reality-warping portal effects
            import math
            center_x = self.width // 2
            center_y = self.height // 2
            
            # Draw multiple rotating portals
            for ring in range(5):
                radius = 30 + ring * 15
                for angle_offset in range(0, 360, 30):
                    angle = (angle_offset + frame * 10 * (ring + 1)) % 360
                    rad = math.radians(angle)
                    x = center_x + int(radius * math.cos(rad))
                    y = center_y + int(radius * math.sin(rad))
                    
                    # Rainbow portal particles
                    rainbow_colors = [
                        (255, 0, 0), (255, 127, 0), (255, 255, 0),
                        (0, 255, 0), (0, 0, 255), (148, 0, 211)
                    ]
                    color = rainbow_colors[(frame + ring) % len(rainbow_colors)]
                    draw.ellipse([x-3, y-3, x+3, y+3], fill=color + (255,))
            
            # Reality tears - diagonal lines across the screen
            for i in range(10):
                tear_offset = (frame * 5) % self.width
                x_start = (i * 20 + tear_offset) % self.width
                draw.line([x_start, 0, x_start + 10, self.height], 
                         fill=(255, 0, 255, 150), width=1)
            
            # "TRANSCENDENT" text flickering
            if frame % 3 == 0:
                draw.text((5, 5), "TRANSCENDENT", fill=(255, 255, 255, 255))
            
            return  # Skip normal effects for transcendent mode
        
        # Speed lines behind mech (start at level 30)
        if speed_level >= 30:
            center_y = self.height // 2
            num_lines = min(max(1, (speed_level - 30) // 5), 15)  # 1-15 lines based on speed
            
            for i in range(num_lines):
                line_x = 20 + i * 10
                line_length = 10 + (speed_level // 5)  # Longer lines at higher speeds
                opacity = max(50, min(255, 100 + speed_level))
                
                # Animated offset based on frame
                offset = (frame * (1 + speed_level // 20)) % 15
                
                start_x = line_x - offset
                end_x = start_x + line_length
                
                # Color based on speed level
                if speed_level >= 100:
                    color = (255, 255, 255, opacity)  # Pure white for Godspeed
                elif speed_level >= 90:
                    color = (255, 215, 0, opacity)   # Gold for near-lightspeed
                elif speed_level >= 70:
                    color = (128, 0, 255, opacity)   # Purple for running
                elif speed_level >= 50:
                    color = (0, 255, 255, opacity)   # Cyan for fast walking
                else:
                    color = (0, 255, 0, opacity)     # Green for moderate speed
                
                draw.line([start_x, center_y - 2, end_x, center_y - 2], fill=color, width=2)
                draw.line([start_x, center_y + 2, end_x, center_y + 2], fill=color, width=2)
        
        # Lightning effects for extreme speeds
        if speed_level >= 90 and frame % 2 == 0:
            # Add lightning bolts
            bolt_x = self.width - 40
            bolt_y = 20
            
            draw.line([bolt_x, bolt_y, bolt_x + 10, bolt_y + 15], fill=(255, 255, 0, 255), width=3)
            draw.line([bolt_x + 10, bolt_y + 15, bolt_x + 5, bolt_y + 25], fill=(255, 255, 0, 255), width=3)
            draw.line([bolt_x + 5, bolt_y + 25, bolt_x + 15, bolt_y + 35], fill=(255, 255, 0, 255), width=3)
    
    
    def calculate_speed_level(self, total_donations: float) -> int:
        """Calculate speed level based on donation amount and mech evolution level (1-100 scale, 101 for OMEGA perfection)"""
        if total_donations <= 0:
            return 0
        
        # Import here to avoid circular imports
        from utils.mech_evolutions import get_evolution_level, EVOLUTION_THRESHOLDS
        
        # Get current mech evolution level
        mech_level = get_evolution_level(total_donations)
        
        # SPECIAL CASE: Level 11 (OMEGA MECH) at exactly max fuel = Glvl 101!
        if mech_level == 11:
            # Level 11 has no next level, so we calculate based on a theoretical max
            # Let's say Level 11 "max" is $20000 (double the requirement)
            theoretical_max = 20000
            current_threshold = EVOLUTION_THRESHOLDS[11]  # 10000
            fuel_in_level = total_donations - current_threshold
            max_fuel_for_level = theoretical_max - current_threshold  # 10000
            
            if fuel_in_level >= max_fuel_for_level:
                # TRANSCENDENT MODE ACTIVATED!
                return 101
            elif fuel_in_level == 0:
                return 1
            else:
                glvl = int((fuel_in_level / max_fuel_for_level) * 100)
                return min(max(1, glvl), 100)
        
        # For levels 1-4: Direct 1:1 mapping (1$ = 1 Glvl)
        if mech_level <= 4:
            # Cap at 100 for these levels
            return min(int(total_donations), 100)
        
        # For levels 5-10: Dynamic distribution across 100 levels
        # Calculate the fuel range for current level
        current_threshold = EVOLUTION_THRESHOLDS[mech_level]
        next_threshold = EVOLUTION_THRESHOLDS.get(mech_level + 1, current_threshold * 2)
        
        # Calculate fuel within current level range
        fuel_in_level = total_donations - current_threshold
        max_fuel_for_level = next_threshold - current_threshold
        
        # Calculate Glvl as percentage of max fuel for this level
        if max_fuel_for_level > 0:
            # If at exact threshold, start at 1
            if fuel_in_level == 0:
                return 1
            glvl = int((fuel_in_level / max_fuel_for_level) * 100)
            return min(max(1, glvl), 100)  # Ensure between 1-100
        
        return 100  # Max level reached
    
    def _create_smaller_animation(self, frames, speed_level):
        """Create smaller animation if original is too large"""
        # Reduce quality and try again
        buffer = BytesIO()
        duration = max(100, 250 - (speed_level * 30))
        
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
        return discord.File(buffer, filename="sprite_mech_small.webp")
    
    def _create_smaller_animation_sync(self, frames, speed_level) -> bytes:
        """Create smaller animation if original is too large (sync version)"""
        buffer = BytesIO()
        duration = max(100, 250 - (speed_level * 30))
        
        frames[0].save(
            buffer, 
            format='WebP',
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            quality=60,
            method=4,
            lossless=False
        )
        
        buffer.seek(0)
        return buffer.getvalue()
    
    def create_dead_mech_animation_sync(self, donor_name: str) -> bytes:
        """Create static dead mech (no fuel) - sync version"""
        try:
            sprite = self.get_sprite_frame(0, evolution_level=1)
            if not sprite:
                return self.create_static_fallback_sync(donor_name, "0€", 0)
            
            base_scale = 0.24
            base_width = int(self.sprite_width * base_scale)
            base_height = int(self.sprite_height * base_scale)
            sprite = sprite.resize((base_width, base_height), Image.NEAREST)
            
            img = Image.new('RGBA', (self.width, self.height), (20, 20, 25, 255))
            
            # Darken the sprite
            dead_sprite = Image.new('RGBA', sprite.size)
            sprite_data = sprite.load()
            dead_sprite_data = dead_sprite.load()
            
            for y in range(sprite.size[1]):
                for x in range(sprite.size[0]):
                    r, g, b, a = sprite_data[x, y]
                    gray = int((r + g + b) / 3 * 0.3)
                    
                    if (r + g + b > 400 and b > 150):
                        dead_sprite_data[x, y] = (30, 30, 35, a)
                    else:
                        dead_sprite_data[x, y] = (gray, gray, gray, a)
            
            x = (self.width - base_width) // 2
            y = (self.height - base_height) // 2
            img.paste(dead_sprite, (x, y), dead_sprite)
            
            # Add "NO FUEL" text
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "NO FUEL", fill=(80, 80, 80, 255))
            draw.text((10, self.height - 25), "$0", fill=(60, 60, 60, 255))
            
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            logger.info("Created dead mech animation (no fuel)")
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Error creating dead mech animation: {e}")
            return self.create_static_fallback_sync(donor_name, "0€", 0)
    
    def create_static_fallback_sync(self, donor_name: str, amount: str, speed_level: int) -> bytes:
        """Create static image fallback (sync version)"""
        try:
            img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
            
            sprite = self.get_sprite_frame(0, evolution_level=0)
            if sprite:
                base_scale = 0.24
                base_width = int(self.sprite_width * base_scale)
                base_height = int(self.sprite_height * base_scale)
                sprite = sprite.resize((base_width, base_height), Image.NEAREST)
                
                x = (self.width - base_width) // 2
                y = (self.height - base_height) // 2
                img.paste(sprite, (x, y), sprite)
            
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Error creating static fallback: {e}")
            # Ultra fallback
            buffer = BytesIO()
            fallback_img = Image.new('RGBA', (100, 50), (47, 49, 54, 255))
            fallback_img.save(buffer, format='WebP')
            buffer.seek(0)
            return buffer.getvalue()
    
    def create_static_fallback(self, donor_name: str, amount: str, speed_level: int):
        """Create static image fallback"""
        try:
            img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
            
            # Get first sprite frame of default mech
            sprite = self.get_sprite_frame(0, evolution_level=0)
            if sprite:
                # Scale sprite (50% bigger)
                base_scale = 0.24
                base_width = int(self.sprite_width * base_scale)
                base_height = int(self.sprite_height * base_scale)
                sprite = sprite.resize((base_width, base_height), Image.NEAREST)
                
                # Center sprite
                x = (self.width - base_width) // 2
                y = (self.height - base_height) // 2
                img.paste(sprite, (x, y), sprite)
                
                # No text overlay on animation anymore
            
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            return discord.File(buffer, filename="sprite_mech_static.webp")
            
        except Exception as e:
            logger.error(f"Error creating static fallback: {e}")
            # Ultra fallback
            buffer = BytesIO()
            fallback_img = Image.new('RGBA', (100, 50), (47, 49, 54, 255))
            fallback_img.save(buffer, format='WebP')
            buffer.seek(0)
            return discord.File(buffer, filename="mech_error.webp")

# Singleton instance
_sprite_animator = None

def get_sprite_animator() -> SpriteMechAnimator:
    """Get or create the singleton sprite animator instance"""
    global _sprite_animator
    if _sprite_animator is None:
        _sprite_animator = SpriteMechAnimator()
    return _sprite_animator