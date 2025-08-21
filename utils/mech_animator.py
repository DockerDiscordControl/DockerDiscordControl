# -*- coding: utf-8 -*-
"""
Mech Animator - Creates animated GIFs for donation broadcasts
"""

from PIL import Image, ImageDraw, ImageFont
import discord
from io import BytesIO
import math
import logging
from pathlib import Path
from utils.logging_utils import get_module_logger

logger = get_module_logger('mech_animator')

class MechDonationAnimator:
    """Creates optimized animations for donation broadcasts"""
    
    def __init__(self):
        # Keep dimensions small for file size
        self.width = 220
        self.height = 80
        self.frames = 10  # Balance between smoothness and size
        self.max_file_size = 500_000  # 500KB limit
        
    async def create_donation_animation(self, donor_name: str, amount: str, total_donations: float) -> discord.File:
        """
        Creates a small, optimized GIF animation for a donation
        
        Args:
            donor_name: Name of the donor
            amount: Donation amount string (e.g., "10€")
            total_donations: Total donation count for speed calculation
            
        Returns:
            Discord.File containing the animation or static image
        """
        try:
            # Calculate speed level based on total donations
            speed_level = self.calculate_speed_level(total_donations)
            frames = []
            
            logger.info(f"Creating mech animation for {donor_name}, speed level: {speed_level}")
            
            for frame in range(self.frames):
                img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
                draw = ImageDraw.Draw(img)
                
                # Calculate mech position (runs across screen)
                progress = frame / self.frames
                mech_x = int(-30 + (self.width + 60) * progress)
                
                # Draw speed effects based on level
                self._draw_speed_effects(draw, mech_x, speed_level, frame)
                
                # Draw the mech
                self._draw_mech(draw, mech_x, speed_level)
                
                # Add text on first and last frames
                if frame == 0 or frame == self.frames - 1:
                    self._draw_text(draw, donor_name, speed_level)
                
                frames.append(img)
            
            # Create optimized GIF
            buffer = BytesIO()
            
            # Calculate duration based on speed level
            duration = max(30, 100 - (speed_level * 10))  # Faster at higher levels
            
            frames[0].save(
                buffer, 
                format='GIF',
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,
                optimize=True,  # Important for file size
                colors=64  # Reduced color palette
            )
            
            # Check file size
            buffer.seek(0)
            file_size = buffer.getbuffer().nbytes
            
            if file_size > self.max_file_size:
                logger.warning(f"Animation too large ({file_size} bytes), falling back to static image")
                return self.create_static_mech(donor_name, amount, speed_level)
            
            logger.info(f"Animation created successfully ({file_size} bytes)")
            buffer.seek(0)
            return discord.File(buffer, filename="mech_donation.gif")
            
        except Exception as e:
            logger.error(f"Error creating animation: {e}")
            return self.create_static_mech(donor_name, amount, 1)
    
    def _draw_speed_effects(self, draw: ImageDraw, mech_x: int, speed_level: int, frame: int):
        """Draw speed lines and effects based on donation level"""
        
        # Speed lines for levels 3+
        if speed_level >= 3:
            for i in range(min(speed_level, 5)):
                line_x = mech_x - 15 - (i * 12)
                line_length = 8 + (speed_level * 2)
                opacity = int(180 - i * 30)
                
                # Blue speed lines
                draw.line([line_x, 40, line_x + line_length, 40], 
                         fill=(114, 137, 218, opacity), width=2)
                
                # Additional white streaks for high speed
                if speed_level >= 5:
                    draw.line([line_x - 5, 38, line_x + line_length - 5, 38],
                             fill=(255, 255, 255, opacity // 2), width=1)
        
        # Lightning effect for max speed (level 6)
        if speed_level >= 6:
            # Golden glow around mech
            for radius in range(20, 5, -3):
                opacity = int(40 * (radius / 20))
                draw.ellipse([mech_x - radius + 10, 40 - radius/2, 
                             mech_x + 30 + radius, 40 + radius/2],
                            fill=(255, 215, 0, opacity))
            
            # Lightning bolts
            if frame % 2 == 0:  # Flashing effect
                draw.line([mech_x + 25, 35, mech_x + 35, 30], 
                         fill=(255, 255, 0, 255), width=2)
                draw.line([mech_x + 35, 30, mech_x + 32, 40], 
                         fill=(255, 255, 0, 255), width=2)
                draw.line([mech_x + 32, 40, mech_x + 40, 38], 
                         fill=(255, 255, 0, 255), width=2)
    
    def _draw_mech(self, draw: ImageDraw, x: int, speed_level: int):
        """Draw the mech robot"""
        
        # Main body color changes with speed
        if speed_level >= 6:
            body_color = (255, 215, 0, 255)  # Gold at light speed
        elif speed_level >= 4:
            body_color = (150, 170, 230, 255)  # Light blue when fast
        else:
            body_color = (114, 137, 218, 255)  # Discord blurple
        
        # Mech body (main rectangle)
        draw.rectangle([x, 30, x + 25, 50], fill=body_color)
        
        # Head
        draw.rectangle([x + 5, 25, x + 20, 30], fill=body_color)
        
        # Eyes (glowing based on speed)
        eye_color = (255, 0, 0, 255) if speed_level >= 6 else (255, 255, 255, 255)
        draw.rectangle([x + 7, 27, x + 10, 29], fill=eye_color)
        draw.rectangle([x + 15, 27, x + 18, 29], fill=eye_color)
        
        # Legs (animated walking)
        leg_offset = 5 if x % 20 < 10 else -5
        draw.rectangle([x + 5, 50, x + 10, 55 + leg_offset], fill=body_color)
        draw.rectangle([x + 15, 50, x + 20, 55 - leg_offset], fill=body_color)
        
        # Arms
        draw.rectangle([x - 3, 35, x + 2, 40], fill=body_color)
        draw.rectangle([x + 23, 35, x + 28, 40], fill=body_color)
    
    def _draw_text(self, draw: ImageDraw, donor_name: str, speed_level: int):
        """Add text labels to the animation"""
        
        # Donor name (truncated if too long)
        name_display = donor_name[:12] + "..." if len(donor_name) > 12 else donor_name
        draw.text((5, 5), name_display, fill=(255, 255, 255, 200))
        
        # Speed indicator
        speed_text = self._get_speed_text(speed_level)
        text_color = (255, 215, 0, 255) if speed_level >= 6 else (114, 137, 218, 255)
        draw.text((5, 65), speed_text, fill=text_color)
    
    def _get_speed_text(self, level: int) -> str:
        """Get speed description text"""
        speed_texts = {
            1: "Walking 🚶",
            2: "Jogging 🏃",
            3: "Running 🏃💨",
            4: "Sprinting ⚡",
            5: "Hyperspeed 🚀",
            6: "LIGHTSPEED! ⚡💫"
        }
        return speed_texts.get(level, "Walking 🚶")
    
    def calculate_speed_level(self, total_donations: int) -> int:
        """
        Calculate mech speed level (1-6) based on total donations
        
        Args:
            total_donations: Total number of donations received
            
        Returns:
            Speed level from 1 to 6
        """
        # Using donation count instead of amount for now
        # Can be adjusted to use monetary value
        if total_donations >= 100:
            return 6  # Lightspeed!
        elif total_donations >= 50:
            return 5
        elif total_donations >= 25:
            return 4
        elif total_donations >= 10:
            return 3
        elif total_donations >= 5:
            return 2
        return 1
    
    def create_static_mech(self, donor_name: str, amount: str, speed_level: int) -> discord.File:
        """
        Fallback: Create static image if GIF is too large
        
        Args:
            donor_name: Name of the donor
            amount: Donation amount
            speed_level: Calculated speed level
            
        Returns:
            Discord.File containing static PNG image
        """
        try:
            img = Image.new('RGBA', (self.width, self.height), (47, 49, 54, 255))
            draw = ImageDraw.Draw(img)
            
            # Draw static mech in center
            mech_x = self.width // 2 - 12
            self._draw_mech(draw, mech_x, speed_level)
            self._draw_speed_effects(draw, mech_x, speed_level, 0)
            
            # Add text
            name_display = donor_name[:15] + "..." if len(donor_name) > 15 else donor_name
            draw.text((10, 5), f"💝 {name_display}", fill=(255, 255, 255, 255))
            
            # Speed indicator with emoji
            speed_text = self._get_speed_text(speed_level)
            draw.text((10, 60), speed_text, fill=(114, 137, 218, 255))
            
            # Amount if provided
            if amount:
                draw.text((self.width - 60, 5), amount, fill=(255, 215, 0, 255))
            
            buffer = BytesIO()
            img.save(buffer, format='PNG', optimize=True)
            buffer.seek(0)
            
            logger.info("Created static mech image as fallback")
            return discord.File(buffer, filename="mech_donation.png")
            
        except Exception as e:
            logger.error(f"Error creating static image: {e}")
            # Ultra fallback - empty image
            img = Image.new('RGBA', (100, 50), (47, 49, 54, 255))
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return discord.File(buffer, filename="mech_error.png")

# Singleton instance
_mech_animator = None

def get_mech_animator() -> MechDonationAnimator:
    """Get or create the singleton mech animator instance"""
    global _mech_animator
    if _mech_animator is None:
        _mech_animator = MechDonationAnimator()
    return _mech_animator