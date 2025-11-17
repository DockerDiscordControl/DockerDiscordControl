#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Fix Mech 10 big alignment by shifting problematic frames."""

from PIL import Image
from pathlib import Path
import shutil

def fix_frame_alignment(frame_path, shift_up_px, backup=True):
    """
    Fix frame alignment by shifting content upward.

    Args:
        frame_path: Path to the PNG file
        shift_up_px: How many pixels to shift content upward
        backup: Whether to create a backup of the original
    """
    print(f"\n{'='*80}")
    print(f"Fixing: {frame_path.name}")
    print(f"Shift: {shift_up_px}px upward")
    print(f"{'='*80}")

    # Create backup if requested
    if backup:
        backup_path = frame_path.parent / f"{frame_path.stem}_original{frame_path.suffix}"
        if not backup_path.exists():
            shutil.copy2(frame_path, backup_path)
            print(f"✅ Backup created: {backup_path.name}")
        else:
            print(f"ℹ️  Backup already exists: {backup_path.name}")

    # Load original image
    with Image.open(frame_path) as img:
        # Ensure RGBA mode
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        else:
            img = img.copy()

        width, height = img.size
        print(f"Original size: {width}x{height}")

        # Get bounding box of non-transparent content
        bbox = img.getbbox()
        if not bbox:
            print(f"❌ No content found in image!")
            return False

        print(f"Original content bbox: {bbox}")
        print(f"Original content position: top={bbox[1]}px, height={bbox[3]-bbox[1]}px")

        # Extract the content
        content = img.crop(bbox)

        # Create new transparent image (same size as original)
        new_img = Image.new('RGBA', (width, height), (0, 0, 0, 0))

        # Calculate new position (shift content upward)
        new_top = bbox[1] - shift_up_px
        new_left = bbox[0]

        # Make sure we don't go negative
        if new_top < 0:
            print(f"⚠️  Warning: Shift would move content above image bounds ({new_top}px)")
            print(f"   Adjusting to top=0px")
            new_top = 0

        # Paste content at new position
        new_img.paste(content, (new_left, new_top))

        # Verify new position
        new_bbox = new_img.getbbox()
        print(f"New content bbox: {new_bbox}")
        print(f"New content position: top={new_bbox[1]}px, height={new_bbox[3]-new_bbox[1]}px")
        print(f"✅ Content shifted {bbox[1] - new_bbox[1]}px upward")

        # Save the corrected image
        new_img.save(frame_path)
        print(f"✅ Saved corrected image: {frame_path.name}")

        return True


def main():
    assets_dir = Path("/Volumes/appdata/dockerdiscordcontrol/assets/mech_evolutions")
    mech10_big = assets_dir / "Mech10" / "big"

    print(f"\n{'='*80}")
    print(f"Mech 10 Big - Alignment Correction")
    print(f"{'='*80}")
    print(f"\nTarget folder: {mech10_big}")
    print(f"\nFrames to fix:")
    print(f"  - Frame 1 (10_walk_0001.png): Shift 9px upward")
    print(f"  - Frame 3 (10_walk_0003.png): Shift 12px upward")
    print(f"\n")

    # Fix Frame 1
    frame1_path = mech10_big / "10_walk_0001.png"
    if frame1_path.exists():
        success1 = fix_frame_alignment(frame1_path, shift_up_px=9, backup=True)
    else:
        print(f"❌ Frame 1 not found: {frame1_path}")
        success1 = False

    # Fix Frame 3
    frame3_path = mech10_big / "10_walk_0003.png"
    if frame3_path.exists():
        success2 = fix_frame_alignment(frame3_path, shift_up_px=12, backup=True)
    else:
        print(f"❌ Frame 3 not found: {frame3_path}")
        success2 = False

    print(f"\n{'='*80}")
    if success1 and success2:
        print(f"✅ SUCCESS: Both frames corrected!")
        print(f"\nNext steps:")
        print(f"  1. Run alignment analysis again to verify")
        print(f"  2. Re-render Mech 10 big animations")
        print(f"  3. Clear cache and test in Discord")
    else:
        print(f"❌ Some frames could not be corrected")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
