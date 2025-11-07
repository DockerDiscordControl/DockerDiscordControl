#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix Mech Level 1 Offline Cropping

This script regenerates the Level 1 offline (rest) animation cache file
with the correct 60px top cropping applied.

Usage:
    python3 scripts/fix_mech1_offline_cropping.py
"""

import sys
from pathlib import Path
from PIL import Image
import logging

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def _obfuscate_data(data: bytes) -> bytes:
    """XOR obfuscation with key (same as animation_cache_service)"""
    xor_key = b'MechAnimCache2024'
    key_len = len(xor_key)
    return bytes(data[i] ^ xor_key[i % key_len] for i in range(len(data)))

def _deobfuscate_data(data: bytes) -> bytes:
    """Reverse XOR obfuscation (XOR is symmetric)"""
    return _obfuscate_data(data)

def main():
    logger.info("🔧 Fixing Mech Level 1 Offline Cropping")
    logger.info("=" * 60)

    # Paths
    cache_file = project_root / "cached_animations" / "mech_1_rest_100speed.cache"
    backup_file = project_root / "cached_animations" / "mech_1_rest_100speed.cache.backup"

    if not cache_file.exists():
        logger.error(f"Cache file not found: {cache_file}")
        return 1

    try:
        # Step 1: Backup original file
        logger.info(f"📦 Backing up original file...")
        with open(cache_file, 'rb') as f:
            original_data = f.read()
        with open(backup_file, 'wb') as f:
            f.write(original_data)
        logger.info(f"   ✅ Backup saved: {backup_file}")

        # Step 2: Deobfuscate to get WebP data
        logger.info(f"🔓 Deobfuscating cache file...")
        webp_data = _deobfuscate_data(original_data)
        logger.info(f"   ✅ Deobfuscated {len(webp_data)} bytes")

        # Step 3: Load WebP animation
        logger.info(f"📂 Loading WebP animation...")
        from io import BytesIO
        webp_stream = BytesIO(webp_data)
        img = Image.open(webp_stream)

        # Get all frames
        frames = []
        frame_count = 0
        try:
            while True:
                img.seek(frame_count)
                frame = img.copy().convert('RGBA')

                # Get original frame size
                original_width, original_height = frame.size
                logger.info(f"   Frame {frame_count + 1}: {original_width}x{original_height}px")

                # Crop 60px from top
                cropped_frame = frame.crop((0, 60, original_width, original_height))
                new_width, new_height = cropped_frame.size
                logger.info(f"      → Cropped to {new_width}x{new_height}px (removed 60px from top)")

                frames.append(cropped_frame)
                frame_count += 1
        except EOFError:
            pass  # End of frames

        logger.info(f"   ✅ Loaded and cropped {len(frames)} frames")

        if not frames:
            logger.error("No frames found in animation!")
            return 1

        # Step 4: Save as new WebP animation
        logger.info(f"💾 Saving cropped WebP animation...")
        output_stream = BytesIO()

        # Save with same parameters as original
        frames[0].save(
            output_stream,
            format='WEBP',
            save_all=True,
            append_images=frames[1:],
            duration=125,  # 8 FPS (125ms per frame)
            loop=0,
            lossless=True,
            quality=100,
            method=6
        )

        new_webp_data = output_stream.getvalue()
        logger.info(f"   ✅ Generated {len(new_webp_data)} bytes (original: {len(webp_data)} bytes)")

        # Step 5: Obfuscate and save back to cache file
        logger.info(f"🔒 Obfuscating and saving to cache...")
        new_cache_data = _obfuscate_data(new_webp_data)

        with open(cache_file, 'wb') as f:
            f.write(new_cache_data)

        logger.info(f"   ✅ Saved {len(new_cache_data)} bytes to {cache_file}")

        # Summary
        logger.info("")
        logger.info("🎉 SUCCESS!")
        logger.info(f"   📁 Original backed up: {backup_file.name}")
        logger.info(f"   ✂️  Cropped {len(frames)} frames (removed 60px from top)")
        logger.info(f"   💾 New cache file: {cache_file.name}")
        logger.info(f"   📊 Size change: {len(original_data)} → {len(new_cache_data)} bytes ({len(new_cache_data) - len(original_data):+d} bytes)")
        logger.info("")
        logger.info("🚀 Level 1 offline mech will now display with correct cropping!")

        return 0

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

        # Restore backup on error
        if backup_file.exists():
            logger.info(f"⚠️  Restoring backup...")
            with open(backup_file, 'rb') as f:
                backup_data = f.read()
            with open(cache_file, 'wb') as f:
                f.write(backup_data)
            logger.info(f"   ✅ Backup restored")

        return 1

if __name__ == '__main__':
    exit(main())
