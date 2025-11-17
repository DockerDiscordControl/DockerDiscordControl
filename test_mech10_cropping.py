#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Test Mech 10 big cropping values to verify alignment."""

from PIL import Image
from pathlib import Path

def analyze_cropping(assets_dir, evolution_level=10, resolution="big"):
    """Analyze cropping values for Mech 10."""

    folder = assets_dir / f"Mech{evolution_level}" / resolution

    # Proposed crop values for 412x412 big frames
    if resolution == "big":
        top_crop = 44
        bottom_crop = 83
    else:
        top_crop = 12
        bottom_crop = 21

    print(f"\n{'='*60}")
    print(f"Mech {evolution_level} - {resolution.upper()} Resolution Cropping Analysis")
    print(f"{'='*60}\n")

    # Find all walk frames
    walk_files = sorted(folder.glob(f"{evolution_level}_walk_*.png"))

    if not walk_files:
        print(f"❌ No walk files found in {folder}")
        return

    print(f"Found {len(walk_files)} frames\n")
    print(f"Proposed crop values: top={top_crop}px, bottom={bottom_crop}px\n")

    # Analyze each frame
    frame_data = []
    for png_path in walk_files:
        with Image.open(png_path) as img:
            width, height = img.size

            # Apply proposed cropping
            cropped = img.crop((0, top_crop, width, height - bottom_crop))
            cropped_width, cropped_height = cropped.size

            # Get bounding box to measure content position
            bbox = cropped.getbbox()

            frame_data.append({
                'name': png_path.name,
                'original': f"{width}x{height}",
                'cropped': f"{cropped_width}x{cropped_height}",
                'bbox': bbox,
                'content_top': bbox[1] if bbox else 0,
                'content_bottom': cropped_height - bbox[3] if bbox else 0
            })

    # Print results
    print(f"{'Frame':<20} {'Original':<12} {'Cropped':<12} {'Content Top':<14} {'Content Bottom':<14}")
    print(f"{'-'*75}")

    content_tops = []
    content_bottoms = []

    for data in frame_data:
        print(f"{data['name']:<20} {data['original']:<12} {data['cropped']:<12} "
              f"{data['content_top']:<14} {data['content_bottom']:<14}")
        content_tops.append(data['content_top'])
        content_bottoms.append(data['content_bottom'])

    # Calculate variation (alignment quality)
    if content_tops:
        top_variation = max(content_tops) - min(content_tops)
        bottom_variation = max(content_bottoms) - min(content_bottoms)

        print(f"\n{'='*75}")
        print(f"Alignment Quality:")
        print(f"  Top variation: {top_variation}px (lower is better)")
        print(f"  Bottom variation: {bottom_variation}px (lower is better)")

        if top_variation <= 5 and bottom_variation <= 5:
            print(f"  ✅ EXCELLENT alignment (< 5px variation)")
        elif top_variation <= 10 and bottom_variation <= 10:
            print(f"  ⚠️  GOOD alignment (< 10px variation)")
        else:
            print(f"  ❌ POOR alignment (> 10px variation)")

        print(f"\nRecommendation:")
        if top_variation <= 10 and bottom_variation <= 10:
            print(f"  ✅ Use crop values: top={top_crop}px, bottom={bottom_crop}px")
            print(f"  Ready to render animations!")
        else:
            print(f"  ⚠️  May need to adjust crop values")
            print(f"  Consider: top={top_crop - int(min(content_tops))}px, bottom={bottom_crop + int(min(content_bottoms))}px")


if __name__ == "__main__":
    assets_dir = Path("/Volumes/appdata/dockerdiscordcontrol/assets/mech_evolutions")

    # Analyze big resolution
    analyze_cropping(assets_dir, evolution_level=10, resolution="big")

    # Also analyze small for comparison
    print("\n\n")
    analyze_cropping(assets_dir, evolution_level=10, resolution="small")
