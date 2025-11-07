#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix Mech Big Offline Cropping

This script regenerates big offline (rest) animation cache files
with the correct 116px top cropping applied.

Usage:
    python3 scripts/fix_mech_big_offline_cropping.py [level]

    If no level is specified, processes all levels 1-10.
    If level is specified, processes only that level.
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

def fix_mech_level_big(level: int) -> bool:
    """Fix big offline cropping for a specific mech level."""
    logger.info(f"🔧 Fixing Mech Level {level} BIG Offline Cropping")
    logger.info("=" * 60)

    # Paths
    cache_file = project_root / "cached_animations" / f"mech_{level}_rest_100speed_big.cache"
    backup_file = project_root / "cached_animations" / f"mech_{level}_rest_100speed_big.cache.backup"

    if not cache_file.exists():
        logger.error(f"Cache file not found: {cache_file}")
        return False

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

                # Crop 116px from top (big mechs use 116px uniform)
                cropped_frame = frame.crop((0, 116, original_width, original_height))
                new_width, new_height = cropped_frame.size
                logger.info(f"      → Cropped to {new_width}x{new_height}px (removed 116px from top)")

                frames.append(cropped_frame)
                frame_count += 1
        except EOFError:
            pass  # End of frames

        logger.info(f"   ✅ Loaded and cropped {len(frames)} frames")

        if not frames:
            logger.error("No frames found in animation!")
            return False

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
        logger.info(f"   ✂️  Cropped {len(frames)} frames (removed 116px from top)")
        logger.info(f"   💾 New cache file: {cache_file.name}")
        logger.info(f"   📊 Size change: {len(original_data)} → {len(new_cache_data)} bytes ({len(new_cache_data) - len(original_data):+d} bytes)")
        logger.info("")

        return True

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

        return False

def main():
    """Main function - process one or all levels."""
    # Check for level argument
    if len(sys.argv) > 1:
        try:
            level = int(sys.argv[1])
            if level < 1 or level > 10:
                logger.error(f"Invalid level: {level}. Must be between 1 and 10.")
                return 1

            # Process single level
            success = fix_mech_level_big(level)
            if success:
                logger.info(f"🚀 Level {level} BIG offline mech will now display with correct cropping!")
                return 0
            else:
                return 1

        except ValueError:
            logger.error(f"Invalid level argument: {sys.argv[1]}. Must be a number between 1 and 10.")
            return 1
    else:
        # Process all levels 1-10
        logger.info("🔧 Fixing ALL Mech BIG Offline Cropping (Levels 1-10)")
        logger.info("=" * 60)
        logger.info("")

        results = {}
        for level in range(1, 11):
            success = fix_mech_level_big(level)
            results[level] = success
            logger.info("")

        # Summary
        logger.info("=" * 60)
        logger.info("📊 SUMMARY")
        logger.info("=" * 60)

        successful = [l for l, s in results.items() if s]
        failed = [l for l, s in results.items() if not s]

        logger.info(f"✅ Successful: {len(successful)} levels")
        if successful:
            logger.info(f"   Levels: {', '.join(map(str, successful))}")

        if failed:
            logger.info(f"❌ Failed: {len(failed)} levels")
            logger.info(f"   Levels: {', '.join(map(str, failed))}")
            logger.info("")
            return 1

        logger.info("")
        logger.info("🚀 All BIG offline mechs will now display with correct cropping!")
        return 0

if __name__ == '__main__':
    exit(main())
