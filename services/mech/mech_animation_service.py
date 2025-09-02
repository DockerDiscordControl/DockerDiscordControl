# -*- coding: utf-8 -*-
"""
Mech Animation Service - Centralized service for all mech animation functionality
"""

import sys
import os
import asyncio
import logging
from typing import Optional, Dict, Any
from flask import Response
from io import BytesIO

# Ensure proper imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from .sprite_mech_animator import get_sprite_animator
from .speed_levels import get_speed_info, get_speed_emoji
from utils.logging_utils import get_module_logger

logger = get_module_logger('mech_animation_service')

class MechAnimationService:
    """Centralized service for mech animation functionality"""
    
    def __init__(self):
        self.sprite_animator = get_sprite_animator()
        
    async def create_donation_animation_async(self, donor_name: str, amount: str, total_donations: float):
        """Create donation animation and return discord.File object for Discord use"""
        try:
            logger.info(f"Creating mech animation for {donor_name}, Power: {total_donations}")
            
            # Create the discord.File animation
            animation_file = await self.sprite_animator.create_donation_animation(
                donor_name, amount, total_donations
            )
            
            return animation_file
                
        except Exception as e:
            logger.error(f"Error creating mech animation: {e}")
            raise
    
    def create_donation_animation_sync(self, donor_name: str, amount: str, total_donations: float) -> bytes:
        """Synchronous wrapper for creating donation animations, returns raw bytes for Web use"""
        try:
            # Use asyncio.create_task for proper event loop handling in Flask
            import asyncio
            import threading
            from concurrent.futures import ThreadPoolExecutor
            
            def run_async_in_thread():
                # Create new event loop in separate thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(
                        self.sprite_animator.create_donation_animation(donor_name, amount, total_donations)
                    )
                finally:
                    new_loop.close()
            
            # Run in thread to avoid event loop conflicts
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_async_in_thread)
                animation_file = future.result(timeout=30)  # 30 second timeout
            
            # Extract raw bytes from discord.File
            if hasattr(animation_file, 'fp'):
                animation_file.fp.seek(0)
                if hasattr(animation_file.fp, 'getvalue'):
                    return animation_file.fp.getvalue()
                else:
                    return animation_file.fp.read()
            else:
                # Fallback if it's already bytes
                return animation_file if isinstance(animation_file, bytes) else b''
            
        except Exception as e:
            logger.error(f"Error in sync animation creation: {e}")
            raise
    
    def create_web_response(self, donor_name: str, amount: str, total_donations: float) -> Response:
        """Create a Flask Response with the mech animation"""
        try:
            file_data = self.create_donation_animation_sync(donor_name, amount, total_donations)
            
            return Response(
                file_data,
                mimetype='image/webp',
                headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
            )
            
        except Exception as e:
            logger.error(f"Error creating web response: {e}")
            # Return error response
            error_img = self._create_error_image()
            return Response(
                error_img,
                mimetype='image/webp',
                status=500
            )
    
    def _create_error_image(self) -> bytes:
        """Create a simple error image when animation fails"""
        try:
            from PIL import Image, ImageDraw
            
            img = Image.new('RGBA', (200, 100), (47, 49, 54, 255))
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), "ERROR", fill=(255, 0, 0, 255))
            draw.text((10, 40), "Failed to", fill=(255, 255, 255, 255))
            draw.text((10, 60), "load mech", fill=(255, 255, 255, 255))
            
            buffer = BytesIO()
            img.save(buffer, format='WebP', quality=90)
            return buffer.getvalue()
            
        except Exception:
            # Ultra fallback - empty 1x1 image
            return b'RIFF\x16\x00\x00\x00WEBPVP8 \n\x00\x00\x00\x10\x00\x00\x00\x00\x00\x01\x00\x01\x00'

# Singleton instance
_mech_service = None

def get_mech_animation_service() -> MechAnimationService:
    """Get or create the singleton mech animation service"""
    global _mech_service
    if _mech_service is None:
        _mech_service = MechAnimationService()
    return _mech_service