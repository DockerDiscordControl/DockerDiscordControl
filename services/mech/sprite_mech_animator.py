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
        self.width = 256   # Breite bleibt bei 256px
        self.height = 137  # Höhe: 256 * (2/3) * (4/5) = 137px (1/3 + 1/5 kleiner)
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
    
    # --- HELPER METHODS FOR CLEAN EFFECTS ---
    DEBUG_VIS = False  # Optional debug overlay
    
    
    # Frames mit Bodenkontakt pro Zykluslänge (0-basiert)
    FOOTFALL_MAP = {
        6: [1, 4],   # 2x3-Spritesheet
    }
    
    # ---------- CLEAN BEHIND-ONLY BACKGROUND ----------
    BG2 = {
        "gamma": 2.2,                 # dämpft Low-End kräftiger
        "rows_min": 6, "rows_max": 28,
        "dash_min": 6, "dash_max": 18,
        "opacity_min": 60, "opacity_max": 160,
        "px_per_frame_min": 0.6, "px_per_frame_max": 6.0,
        "tint_far": (205,210,235),    # kühles Grau (fern)
        "tint_near": (160,200,255),   # Cyan (nah)
        "top_margin": 0.12, "bot_margin": 0.88,  # Arbeitsbereich
        "deadzone_top": 0.28, "deadzone_bot": 0.72  # Mech-Sperrzone (fallback)
    }
    
    def _clamp01(self, x: float) -> float:
        return 0.0 if x < 0 else 1.0 if x > 1 else x
    
    def _ease_out(self, t: float) -> float:
        t = self._clamp01(t)
        return 1 - (1 - t) ** 3
    
    def _speed_norm(self, speed_level: int) -> float:
        return self._clamp01(speed_level / 100.0)
    
    def _ease_bg2(self, x: float) -> float:
        x = max(0.0, min(1.0, x)) ** self.BG2["gamma"]
        return 1 - (1 - x) ** 3
    
    def _smoothstep(self, x: float) -> float:
        """Smooth transition curve for better feel"""
        x = self._clamp01(x)
        return x * x * (3 - 2 * x)
    
    def _is_foot_down(self, frame_idx: int) -> bool:
        cycle = getattr(self, "frames", 6)
        falls = self.FOOTFALL_MAP.get(cycle)
        if not falls:  # Fallback: zwei Kontakte ungefähr halbiert
            falls = [cycle // 3, (2 * cycle) // 3]
        return (frame_idx % cycle) in falls
    
    def _spawn_ground_dust(self, img, base_x: int, base_y: int, speed_level: int, frame: int):
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        e = self._ease_out(self._speed_norm(speed_level))
        puffs = 2 + int(4 * e)
        life = 22
        for i in range(puffs):
            age = (frame + i * 7) % life
            t = age / life
            x = base_x - int((8 + 10 * e) * t)
            y = base_y - int(4 * t)
            r = 1 + int(3 * t)
            a = 100 - int(80 * t)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(125, 120, 110, max(10, a)))
    
    def _step_profile(self, speed_level: int) -> dict:
        """Simple step profiling for the new clean system"""
        if speed_level == 101:
            return {"mode": "TRANSCENDENT"}
        
        step = max(0, min(50, speed_level // 2))
        x = step / 50.0
        e = self._ease_out(x)
        
        return {
            "step": step, 
            "ease": e,
            "jitter_px": 0 if step < 15 else 1 + (step - 15) // 10,  # 0..3
            "chromatic_px": 0 if step < 6 else 1 + (step - 6) // 12
        }
    
    def _chromatic_on_sprite(self, img, sprite, pos, shift_px: int):
        """Masken-basierte Chromatic Aberration nur auf Sprite"""
        if not sprite or not pos or shift_px <= 0: 
            return
        from PIL import ImageChops, ImageFilter
        sx, sy = pos
        a = sprite.split()[-1]
        mask = a.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1))
        bbox = mask.getbbox()
        if not bbox: 
            return
        bx0, by0, bx1, by1 = bbox
        region = img.crop((sx+bx0, sy+by0, sx+bx1, sy+by1))
        r,g,b,a_reg = region.split()
        r = ImageChops.offset(r, -shift_px, 0)
        b = ImageChops.offset(b,  shift_px, 0)
        region_shifted = Image.merge("RGBA", (r,g,b,a_reg))
        img.paste(region_shifted, (sx+bx0, sy+by0), mask.crop((bx0,by0,bx1,by1)))
    
    def _render_bg_effects_v2(self, speed_level: int, frame: int, sprite=None, pos=None):
        from PIL import Image, ImageDraw
        W, H = self.width, self.height
        bg = Image.new("RGBA", (W, H), (0,0,0,0))
        draw = ImageDraw.Draw(bg)

        # Ease / Intensität
        e = self._ease_bg2(speed_level/100.0)

        # Arbeitsbereich
        top = int(H * self.BG2["top_margin"])
        bot = int(H * self.BG2["bot_margin"])

        # Deadzone um den Mech
        if sprite is not None and pos is not None:
            sx, sy = pos; sw, sh = sprite.size
            dz_top = sy + int(sh * 0.30)
            dz_bot = sy + int(sh * 0.70)
        else:
            dz_top = int(H * self.BG2["deadzone_top"])
            dz_bot = int(H * self.BG2["deadzone_bot"])

        # Zeilenanzahl / Dash-Länge / Deckkraft – alle quantisiert (verhindert Moiré)
        rows_total = int(round(self.BG2["rows_min"] + (self.BG2["rows_max"]-self.BG2["rows_min"]) * e))
        dash = int(round(self.BG2["dash_min"] + (self.BG2["dash_max"]-self.BG2["dash_min"]) * e))
        dash -= dash % 2                         # gerade Zahl -> weniger Artefakte
        gap = dash                               # 1:1
        period = dash + gap
        op = int(round(self.BG2["opacity_min"] + (self.BG2["opacity_max"]-self.BG2["opacity_min"]) * e))

        # Scroll-Speed (parallax, aber NUR horizontal)
        v_far  = self.BG2["px_per_frame_min"] + (self.BG2["px_per_frame_max"]-self.BG2["px_per_frame_min"]) * (e*0.6)
        v_near = self.BG2["px_per_frame_min"] + (self.BG2["px_per_frame_max"]-self.BG2["px_per_frame_min"]) * e

        # Symmetrische Zeilen: Hälfte oben, Hälfte unten (Deckkraft halbieren oben)
        rows_top  = rows_total // 2
        rows_bot  = rows_total - rows_top
        # gleichmässige Abstände, kein Jitter
        def make_rows(n, y0, y1):
            if n <= 0 or y1 <= y0: return []
            step = max(6, (y1 - y0) // (n + 1))
            return [y0 + step*(i+1) for i in range(n)]

        ys_top = make_rows(rows_top, top, dz_top)
        ys_bot = make_rows(rows_bot, dz_bot, bot)

        def draw_layer(ys, speed_px, tint, opacity, phase_shift):
            r,g,b = tint
            col = (r, g, b, opacity)
            for i, yy in enumerate(ys):
                offset = int((frame * speed_px + (i * phase_shift)) % period)
                x0 = -offset
                while x0 < W:
                    x1 = x0 + dash
                    sx = max(0, x0); ex = min(W, x1)
                    if ex > sx:
                        draw.line([sx, yy, ex, yy], fill=col, width=2)
                    x0 += period

        # FAR (oben etwas blasser), NEAR (unten etwas stärker)
        draw_layer(ys_top, v_far,  self.BG2["tint_far"],  max(40, op-40), 7)
        draw_layer(ys_bot, v_near, self.BG2["tint_near"], op,             11)

        return bg

    def speed_to_frame_duration_ms(self, speed: int) -> int:
        if speed <= 0:   
            return 400  # Halbiert von 800
        if speed >= 101: 
            return 25   # Bleibt bei 25 (schon sehr schnell)
        x = self._speed_norm(speed)
        eased = self._ease_out(x)
        return int(round(375 - 350 * eased))  # Halbiert: 375ms → 25ms
    
    
    def _fixed_scale_171px(self, sprite_h: int) -> float:
        """Feste Skalierung: Mech um 1/3 größer - 171px Höhe"""
        # Ziel: Mech hat 128px * 1.33 = ~171px Höhe
        target_h = int(128 * 1.33)  # 171px = 1/3 größer als 128px
        scale = target_h / max(1, sprite_h)
        return scale
        
    def load_default_spritesheet(self):
        """Load the default mech spritesheet as fallback"""
        try:
            # Try loading encoded version first
            from services.mech.mech_sprite_encoder import decode_sprite_from_file
            
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
            from services.mech.mech_sprite_encoder import decode_sprite_from_file
            
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
            
        # Calculate sprite dimensions for this specific spritesheet
        sheet_width, sheet_height = spritesheet.size
        sprite_width = sheet_width // 3  # 3 columns
        sprite_height = sheet_height // 2  # 2 rows
        
        # Calculate sprite position in 2x3 grid
        col = frame_index % 3
        row = frame_index // 3
        
        left = col * sprite_width
        top = row * sprite_height
        right = left + sprite_width
        bottom = top + sprite_height
        
        return spritesheet.crop((left, top, right, bottom))
    
    def create_donation_animation_sync(self, donor_name: str, amount: str, total_donations: float) -> bytes:
        """Create animated WebP synchronously for Web UI use"""
        try:
            # Same logic as async version but returns bytes directly
            from services.mech.mech_evolutions import get_evolution_level
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
            # Create quantized cache key for better hit rate
            speed_q = round(speed_level, 1)  
            Power_q = round(total_donations, 2)
            cache_key = f"Power_{Power_q:.2f}_evo_{evolution_level}_speed_{speed_q:.1f}"
            
            if cache_key in self.animation_cache:
                cached_data = self.animation_cache[cache_key]
                if cached_data and len(cached_data) > 0:
                    return cached_data
                else:
                    del self.animation_cache[cache_key]
            
            # Create frames (same logic as async version)
            frames = []
            
            for frame in range(self.frames):
                img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))  # Transparent background
                
                sprite = self.get_sprite_frame(frame, evolution_level)
                if sprite:
                    # Get actual sprite dimensions
                    actual_sprite_width, actual_sprite_height = sprite.size
                    
                    # Scale sprite 
                    base_scale = self._fixed_scale_171px(actual_sprite_height)
                    base_width = int(actual_sprite_width * base_scale)
                    base_height = int(actual_sprite_height * base_scale)
                    
                    # Dezenter Bump: max. +10 % bei Speed 100 (ease-out)
                    x = max(0.0, min(1.0, speed_level / 100.0))
                    e = 1 - (1 - x) ** 3
                    speed_scale_factor = 1.0 + 0.10 * e
                    new_width = int(base_width * speed_scale_factor)
                    new_height = int(base_height * speed_scale_factor)
                    
                    sprite = sprite.resize((new_width, new_height), Image.NEAREST)
                    
                    # Center sprite on canvas
                    x = (self.width - new_width) // 2
                    y = (self.height - new_height) // 2
                    
                    # Add screen shake using profile system
                    prof = self._step_profile(int(speed_level))
                    if prof["jitter_px"] > 0:
                        jitter = int(prof["jitter_px"])
                        x += (frame % (2*jitter+1)) - jitter
                        y += ((frame*2) % (2*jitter+1)) - jitter
                    
                    # Nur der Mech - alle Effekte deaktiviert
                    img.paste(sprite, (x, y), sprite)
                
                frames.append(img)
            
            # Create WebP animation
            buffer = BytesIO()
            
            duration = self.speed_to_frame_duration_ms(speed_level)
            
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
                from services.mech.mech_evolutions import get_evolution_level
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
            
            # EDGE CASE: Handle zero/negative Power BEFORE caching
            if total_donations <= 0:
                logger.info(f"Zero Power detected, creating dead mech animation")
                return await self.create_dead_mech_animation(donor_name)
            
            # PERFORMANCE: Create cache key with quantization for better cache hit rate
            speed_q = round(speed_level, 1)
            Power_q = round(total_donations, 2)
            cache_key = f"Power_{Power_q:.2f}_evo_{evolution_level}_speed_{speed_q:.1f}"
            
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
            
            logger.info(f"Creating new sprite mech animation for evolution: {evolution_level}, speed: {speed_level}, Power: {total_donations}")
            frames = []
            
            for frame in range(self.frames):
                # Create transparent background
                img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
                
                # Get sprite frame for current evolution level
                sprite = self.get_sprite_frame(frame, evolution_level)
                if sprite:
                    # Get actual sprite dimensions (not the cached default dimensions)
                    actual_sprite_width, actual_sprite_height = sprite.size
                    
                    # Scale sprite 
                    base_scale = self._fixed_scale_171px(actual_sprite_height)
                    base_width = int(actual_sprite_width * base_scale)
                    base_height = int(actual_sprite_height * base_scale)
                    
                    # Dezenter Bump: max. +10 % bei Speed 100 (ease-out)
                    x = max(0.0, min(1.0, speed_level / 100.0))
                    e = 1 - (1 - x) ** 3
                    speed_scale_factor = 1.0 + 0.10 * e
                    new_width = int(base_width * speed_scale_factor)
                    new_height = int(base_height * speed_scale_factor)
                    
                    sprite = sprite.resize((new_width, new_height), Image.NEAREST)  # Keep pixel art crisp
                    
                    # Center sprite on canvas
                    x = (self.width - new_width) // 2
                    y = (self.height - new_height) // 2
                    
                    # Add screen shake using profile system
                    prof = self._step_profile(int(speed_level))
                    if prof["jitter_px"] > 0:
                        jitter = int(prof["jitter_px"])
                        x += (frame % (2*jitter+1)) - jitter
                        y += ((frame*2) % (2*jitter+1)) - jitter
                    
                    # Nur der Mech - alle Effekte deaktiviert
                    img.paste(sprite, (x, y), sprite)
                    
                    # No text overlay on animation anymore
                
                frames.append(img)
            
            # Create WebP animation
            buffer = BytesIO()
            
            # Calculate duration using easing curve
            duration = self.speed_to_frame_duration_ms(speed_level)
            
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
        """Create static dead mech (no Power)"""
        try:
            # Use first frame of Level 1 (SCRAP MECH) - it's already broken!
            sprite = self.get_sprite_frame(0, evolution_level=1)  # Static pose of scrap mech
            if not sprite:
                return self.create_static_fallback(donor_name, "0€", 0)
            
            # Get actual sprite dimensions and scale
            actual_sprite_width, actual_sprite_height = sprite.size
            base_scale = 0.85
            base_width = int(actual_sprite_width * base_scale)
            base_height = int(actual_sprite_height * base_scale)
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
            
            # Add "NO POWER" text
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "NO POWER", fill=(80, 80, 80, 255))
            draw.text((10, self.height - 25), "$0", fill=(60, 60, 60, 255))
            
            # Create static WebP
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            logger.info("Created dead mech animation (no Power)")
            return discord.File(buffer, filename="dead_mech.webp")
            
        except Exception as e:
            logger.error(f"Error creating dead mech animation: {e}")
            return self.create_static_fallback(donor_name, "0€", 0)
    
    def _add_speed_effects(self, img, speed_level, frame: int, sprite=None, pos=None):
        """Super saubere Step-basierte Speed-Effekte mit präziser Mech-Sperrzone"""
        from PIL import ImageDraw
        import math, random
        
        # Ensure speed_level is integer to avoid float errors
        speed_level = int(speed_level)
        
        draw = ImageDraw.Draw(img)

        # --- 101: Portal/Transcendent (dein bestehender Look) ---
        if speed_level == 101:
            cx, cy = self.width // 2, self.height // 2
            for ring in range(5):
                r = 30 + ring * 15 + (frame * 3 + ring * 7) % 10
                hue = (frame * 12 + ring * 60) % 360
                # simple HSV ohne Abhängigkeiten:
                import colorsys
                col = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue/360.0, 0.85, 1.0)) + (220,)
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=2)
            for i in range(8):
                x = (i * 20 + (frame * 9)) % self.width
                draw.line([x, 0, x + 8, self.height], fill=(255, 0, 255, 140), width=1)
            if frame % 3 == 0:
                draw.text((6, 6), "TRANSCENDENT", fill=(255, 255, 255, 255))
            return

        # --- Step-Profil: jede 2. Stufe sichtbar anders ---
        step = max(0, min(50, speed_level // 2))
        x = self._speed_norm(speed_level)
        e = self._ease_out(x)
        variant = step % 6
        hue_boost = 180 if variant == 2 else (300 if variant == 3 else 0)
        tilt_deg  = -6 if variant == 1 else (6 if variant == 0 else 0)
        chroma_px = 0 if step < 6 else 1 + (step - 6) // 12  # 0..4

        # --- Speed-Lines (segmentiert, neutral, ohne Schlangen) ---
        # Sperrzone um den Mech, damit nichts quer drüberzeichnet
        if sprite is not None and pos is not None:
            sx, sy = pos; sw, sh = sprite.size
            excl_top = sy + int(sh * 0.30)
            excl_bot = sy + int(sh * 0.70)
        else:
            mid = self.height // 2
            excl_top, excl_bot = mid - 12, mid + 12

        step = max(0, min(50, int(speed_level//2)))
        x = max(0.0, min(1.0, speed_level/100.0))
        e = 1 - (1 - x) ** 3

        # Anzahl/Y-Verteilung
        lines   = 4 + step                # 4..54
        spacing = max(6, 12 - int(8*e))   # dichter bei hoher Speed
        ys = []
        top, bot = int(self.height*0.12), int(self.height*0.88)
        y = top
        while len(ys) < lines and y < bot:
            if not (excl_top <= y <= excl_bot):
                ys.append(y)
            y += spacing

        # Segmentierte Dashes
        dash    = 8 + step//2             # 8..33
        gap     = dash                    # 1:1
        period  = dash + gap
        offset_speed = 1 + step//8        # Bewegungsgeschwindigkeit

        # kühle Palette (kein Grün)
        if step >= 45:
            rgba = (255, 230, 200, 120 + int(120*e))   # warm-weiss/goldig
        elif step >= 30:
            rgba = (160, 120, 255, 110 + int(130*e))   # soft-violett
        elif step >= 15:
            rgba = (0, 220, 255, 100 + int(140*e))     # cyan
        else:
            rgba = (200, 210, 240, 90 + int(120*e))    # kühles Grau

        for i, yy in enumerate(ys):
            offset = (frame * offset_speed + i * 7) % period
            x0 = -offset
            while x0 < self.width:
                x1 = x0 + dash
                if x1 > 0:
                    # clamp auf Bild
                    sx = max(0, int(x0)); ex = min(self.width, int(x1))
                    if ex > sx:
                        draw.line([sx, yy, ex, yy], fill=rgba, width=2)
                x0 += period

        # --- Starfield (kühlt, Richtung wechselt periodisch) ---
        if step >= 3:
            reverse = -1 if variant == 5 else 1
            trails = int(6 + 2 * step)
            trail_len = int(6 + step)
            adv = int(2 + step // 2)
            for i in range(trails):
                y = (i * 37 + frame * 3) % self.height
                sx = (self.width + 20) - reverse * ((frame * adv + i * 13) % (self.width + 40))
                ex = sx - reverse * trail_len
                op = 40 + int(110 * e)
                draw.line([sx, y, ex, y], fill=(200, 210, 240, op), width=1)

        # --- Afterimages (echte Geisterbilder) ---
        if sprite is not None and pos is not None and step >= 7:
            count = int(max(0, (step - 6) // 2))   # wächst Schritt für Schritt
            off = int(2 + step // 8)
            sx, sy = pos
            for i in range(1, count + 1):
                ghost = sprite.copy()
                r, g, b, a = ghost.split()
                fade = max(18, int(120 * (1 - i / (count + 0.75))))
                a = a.point(lambda v, f=fade: int(v * (f / 255.0)))
                ghost.putalpha(a)
                img.paste(ghost, (sx - i * off, sy), ghost)

        # --- Sparks / Lightning / Shockwave ---
        if step >= 11:
            for i in range(int(step - 10)):
                yy = (self.height // 2 - 22) + ((i * 29 + frame * 5) % 44) - 22
                xx = self.width // 2 + 28 + (i % 2) * 6
                draw.line([xx, yy, xx + 3, yy + 2], fill=(255, 225, 120, 200), width=1)

        if step >= 21 and frame % 2 == 0:
            dens = int(step - 20)
            rnd = random.Random(int(9000 + step + frame * 31))
            for _ in range(1 + dens // 4):
                bx = self.width - 40 - rnd.randint(0, 12)
                by = 14 + rnd.randint(0, 24)
                draw.line([bx, by, bx + 10, by + 15], fill=(255, 255, 0, 255), width=3)
                draw.line([bx + 10, by + 15, bx + 5,  by + 25], fill=(255, 255, 0, 255), width=3)
                draw.line([bx + 5,  by + 25, bx + 15, by + 35], fill=(255, 255, 0, 255), width=3)

        # Shockwave-Kreis entfernt - sah komisch aus

        # --- Chromatic nur auf Sprite (kein Schleier) ---
        if chroma_px > 0 and sprite is not None and pos is not None:
            self._chromatic_on_sprite(img, sprite, pos, chroma_px)

        # --- Bodenstaub exakt bei Fusskontakt ---
        frame_in_cycle = frame % getattr(self, "frames", 6)
        if self._is_foot_down(frame_in_cycle):
            foot_x = (self.width // 2) - 6
            ground_y = int(self.height * 0.82)
            self._spawn_ground_dust(img, foot_x, ground_y, speed_level, frame)

        # --- optionales Debug-Overlay ---
        if self.DEBUG_VIS and sprite is not None and pos is not None:
            sx, sy = pos
            sw, sh = sprite.size
            draw.rectangle([sx, sy, sx + sw, sy + sh], outline=(0, 255, 0, 120), width=1)
    
    # --- CLEAN UTILITY METHODS ---

    def calculate_speed_level(self, total_donations: float) -> float:
        """
        Continuous speed 0..100 (101 = OMEGA) without reset on level-up.
        Each evolution level has its own speed range that connects seamlessly.
        """
        if total_donations <= 0:
            return 0.0

        from services.mech.mech_evolutions import get_evolution_level, EVOLUTION_THRESHOLDS

        lvl = max(1, min(11, get_evolution_level(total_donations)))

        # Speed range per level (seamless: max(L) == min(L+1))
        base_min = 6.0
        base_max = 100.0
        step = (base_max - base_min) / 10.0  # 10 levels -> 10 equal segments

        def range_for_level(L: int) -> tuple:
            if L >= 11:
                return (100.0, 101.0)  # OMEGA window
            lo = base_min + (L - 1) * step
            hi = base_min + L * step
            return (lo, hi)

        # Current level thresholds
        cur_th = EVOLUTION_THRESHOLDS[lvl]
        nxt_th = EVOLUTION_THRESHOLDS.get(lvl + 1, cur_th * 2)

        # Progress within level (0..1), smoothed
        span = max(1.0, float(nxt_th - cur_th))
        p = self._smoothstep((total_donations - cur_th) / span)

        lo, hi = range_for_level(lvl)

        # OMEGA: Full >= Level-11-Threshold -> 101
        if lvl == 11 and total_donations >= cur_th:
            return 101.0

        return lo + (hi - lo) * p

    def speed_to_frame_duration_ms(self, speed: float) -> int:
        """
        Map 0..100 (101) to 375..25 ms with ease-out curve (HALBIERT).
        Low speed feels 'heavy', high speed very responsive.
        """
        if speed <= 0:
            return 400  # Halbiert von 800
        if speed >= 101:
            return 25   # OMEGA (bleibt gleich)

        x = min(1.0, max(0.0, speed / 100.0))
        # Ease-out (cubic): small increments early very noticeable,
        # later dollars saturate smoothly
        eased = 1 - (1 - x) ** 3
        return int(round(375 - 350 * eased))  # Halbiert: 375ms → 25ms
    
    def _create_smaller_animation(self, frames, speed_level):
        """Create smaller animation if original is too large"""
        # Reduce quality and try again
        buffer = BytesIO()
        duration = self.speed_to_frame_duration_ms(speed_level)
        
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
        duration = self.speed_to_frame_duration_ms(speed_level)
        
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
        """Create static dead mech (no Power) - sync version"""
        try:
            sprite = self.get_sprite_frame(0, evolution_level=1)
            if not sprite:
                return self.create_static_fallback_sync(donor_name, "0€", 0)
            
            # Get actual sprite dimensions and scale
            actual_sprite_width, actual_sprite_height = sprite.size
            base_scale = 0.85
            base_width = int(actual_sprite_width * base_scale)
            base_height = int(actual_sprite_height * base_scale)
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
            
            # Add "NO POWER" text
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "NO POWER", fill=(80, 80, 80, 255))
            draw.text((10, self.height - 25), "$0", fill=(60, 60, 60, 255))
            
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            buffer.seek(0)
            
            logger.info("Created dead mech animation (no Power)")
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
                base_scale = 0.85
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
                base_scale = 0.85
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