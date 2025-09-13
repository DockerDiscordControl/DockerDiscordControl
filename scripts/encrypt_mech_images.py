#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mech Image Encryption Tool
Encrypts new mech images and integrates them into the system.
"""

import os
import base64
import sys
from pathlib import Path
from PIL import Image
import json
import logging

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def encrypt_image_to_base64(image_path: Path) -> str:
    """Encrypt an image file to base64 string."""
    try:
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
            base64_data = base64.b64encode(img_data).decode('utf-8')
            return base64_data
    except Exception as e:
        logger.error(f"Error encrypting {image_path}: {e}")
        return ""

def analyze_image(image_path: Path) -> dict:
    """Analyze image properties."""
    try:
        with Image.open(image_path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "format": img.format,
                "has_transparency": img.mode in ('RGBA', 'LA') or 'transparency' in img.info
            }
    except Exception as e:
        logger.error(f"Error analyzing {image_path}: {e}")
        return {}

def process_mech_folder(mech_folder: Path, level: int, delete_originals: bool = True) -> dict:
    """Process a mech folder and return encrypted data."""
    logger.info(f"Processing mech level {level} from {mech_folder}")
    
    # Find all PNG files
    frame_files = sorted(mech_folder.glob("*.png"))
    if not frame_files:
        logger.warning(f"No PNG files found in {mech_folder}")
        return {}
    
    logger.info(f"Found {len(frame_files)} frames: {[f.name for f in frame_files]}")
    
    # Process each frame
    frames_data = {}
    total_size = 0
    files_to_delete = []
    
    for i, frame_file in enumerate(frame_files, 1):
        logger.info(f"Encrypting frame {i}: {frame_file.name}")
        
        # Analyze image
        analysis = analyze_image(frame_file)
        
        # Encrypt to base64
        base64_data = encrypt_image_to_base64(frame_file)
        
        if base64_data:
            frames_data[str(i)] = {
                "data": base64_data,
                "width": analysis.get("width", 0),
                "height": analysis.get("height", 0),
                "mode": analysis.get("mode", "RGBA"),
                "format": analysis.get("format", "PNG"),
                "has_transparency": analysis.get("has_transparency", True),
                "file_size": len(base64_data)
            }
            total_size += len(base64_data)
            logger.info(f"  → {analysis.get('width')}x{analysis.get('height')} pixels, {len(base64_data)/1024:.1f}KB encoded")
            
            # Mark file for deletion after successful encryption
            if delete_originals:
                files_to_delete.append(frame_file)
    
    # Delete original files after successful encryption
    if delete_originals and files_to_delete:
        logger.info(f"🔥 Deleting {len(files_to_delete)} original PNG files...")
        for file_to_delete in files_to_delete:
            try:
                file_to_delete.unlink()
                logger.info(f"  ❌ Deleted: {file_to_delete.name}")
            except Exception as e:
                logger.error(f"  ⚠️  Failed to delete {file_to_delete.name}: {e}")
    
    logger.info(f"Level {level} complete: {len(frames_data)} frames, total {total_size/1024:.1f}KB")
    
    return {
        "frames": frames_data,
        "frame_count": len(frames_data),
        "total_encoded_size": total_size,
        "level": level
    }

def update_mech_images_file(new_levels_data: dict):
    """Update or create the mech_images.py file with new levels."""
    mech_images_path = project_root / "services" / "mech" / "mech_images.py"
    
    logger.info(f"Updating mech images file: {mech_images_path}")
    
    # Create the file content
    file_content = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Encrypted Mech Evolution Images                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Encrypted Mech Evolution Images
Contains base64-encoded PNG sprites for each evolution level.
"""

import base64
import logging
from io import BytesIO
from PIL import Image
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Encrypted mech evolution images (base64 encoded)
MECH_EVOLUTION_IMAGES = {
'''
    
    # Add each level
    for level, level_data in sorted(new_levels_data.items()):
        file_content += f'    {level}: {{\n'
        file_content += f'        "frame_count": {level_data["frame_count"]},\n'
        file_content += f'        "frames": {{\n'
        
        # Add each frame
        for frame_num, frame_data in sorted(level_data["frames"].items()):
            file_content += f'            {frame_num}: {{\n'
            file_content += f'                "width": {frame_data["width"]},\n'
            file_content += f'                "height": {frame_data["height"]},\n'
            file_content += f'                "data": "{frame_data["data"]}"\n'
            file_content += f'            }},\n'
        
        file_content += f'        }}\n'
        file_content += f'    }},\n'
    
    # Add the rest of the file
    file_content += '''}

def get_mech_image(level: int, frame: int) -> Optional[Image.Image]:
    """
    Get a specific mech image frame.
    
    Args:
        level: Evolution level (1-10 + secret level 11)
        frame: Frame number (1-6)
        
    Returns:
        PIL Image object or None if not found
    """
    try:
        if level not in MECH_EVOLUTION_IMAGES:
            logger.warning(f"Mech level {level} not found")
            return None
            
        level_data = MECH_EVOLUTION_IMAGES[level]
        if frame not in level_data["frames"]:
            logger.warning(f"Frame {frame} not found for level {level}")
            return None
            
        frame_data = level_data["frames"][frame]
        
        # Decode base64 to bytes
        img_data = base64.b64decode(frame_data["data"])
        
        # Create PIL Image
        img = Image.open(BytesIO(img_data))
        
        # Ensure RGBA mode for transparency
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
            
        return img
        
    except Exception as e:
        logger.error(f"Error loading mech image L{level}F{frame}: {e}")
        return None

def get_mech_frames(level: int) -> List[Image.Image]:
    """
    Get all frames for a specific mech level.
    
    Args:
        level: Evolution level (1-10 + secret level 11)
        
    Returns:
        List of PIL Image objects
    """
    frames = []
    
    if level not in MECH_EVOLUTION_IMAGES:
        logger.warning(f"Mech level {level} not found")
        return frames
        
    level_data = MECH_EVOLUTION_IMAGES[level]
    frame_count = level_data["frame_count"]
    
    for frame_num in range(1, frame_count + 1):
        frame_img = get_mech_image(level, frame_num)
        if frame_img:
            frames.append(frame_img)
    
    logger.info(f"Loaded {len(frames)} frames for mech level {level}")
    return frames

def get_available_levels() -> List[int]:
    """Get list of available mech evolution levels."""
    return sorted(MECH_EVOLUTION_IMAGES.keys())

def get_level_info(level: int) -> Dict:
    """Get information about a specific level."""
    if level not in MECH_EVOLUTION_IMAGES:
        return {}
    
    level_data = MECH_EVOLUTION_IMAGES[level]
    first_frame = level_data["frames"].get(1, {})
    
    return {
        "level": level,
        "frame_count": level_data["frame_count"],
        "width": first_frame.get("width", 0),
        "height": first_frame.get("height", 0),
        "available": True
    }
'''
    
    # Write the file
    with open(mech_images_path, 'w', encoding='utf-8') as f:
        f.write(file_content)
    
    logger.info(f"Mech images file updated successfully!")

def main():
    """Main function to encrypt mech images."""
    logger.info("🤖 Mech Image Encryption Tool Starting...")
    
    # Find mech evolution folders
    assets_path = project_root / "assets" / "mech_evolutions"
    
    if not assets_path.exists():
        logger.error(f"Assets path not found: {assets_path}")
        return
    
    # Process each mech folder
    processed_levels = {}
    
    for mech_folder in assets_path.iterdir():
        if mech_folder.is_dir() and (mech_folder.name.startswith("mech") or mech_folder.name == "secret"):
            # Extract level number from folder name
            try:
                if mech_folder.name == "secret":
                    level = 11  # Secret evolution is level 11
                    logger.info(f"Processing {mech_folder.name} → Level {level} (Secret Evolution)")
                else:
                    level_str = mech_folder.name.replace("mech", "")
                    level = int(level_str)
                    logger.info(f"Processing {mech_folder.name} → Level {level}")
                
                level_data = process_mech_folder(mech_folder, level, delete_originals=True)
                
                if level_data:
                    processed_levels[level] = level_data
                    
            except ValueError:
                logger.warning(f"Could not parse level from folder name: {mech_folder.name}")
    
    if not processed_levels:
        logger.error("No mech levels processed!")
        return
    
    # Update the mech_images.py file
    logger.info(f"Processed levels: {sorted(processed_levels.keys())}")
    update_mech_images_file(processed_levels)
    
    # Summary
    total_frames = sum(data["frame_count"] for data in processed_levels.values())
    total_size = sum(data["total_encoded_size"] for data in processed_levels.values())
    
    logger.info("🎉 Encryption complete!")
    logger.info(f"  📁 Levels processed: {len(processed_levels)}")
    logger.info(f"  🖼️  Total frames: {total_frames}")
    logger.info(f"  💾 Total encoded size: {total_size/1024:.1f}KB")
    logger.info(f"  📝 Updated: services/mech/mech_images.py")

if __name__ == "__main__":
    main()