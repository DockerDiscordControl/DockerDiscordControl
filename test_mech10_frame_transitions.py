#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Frame-by-frame transition analysis for Mech 10 big alignment."""

from PIL import Image
from pathlib import Path

def analyze_frame_transitions(assets_dir, evolution_level=10, resolution="big"):
    """Analyze frame-to-frame transitions to find problematic jumps."""

    folder = assets_dir / f"Mech{evolution_level}" / resolution

    # Crop values
    if resolution == "big":
        top_crop = 44
        bottom_crop = 83
    else:
        top_crop = 12
        bottom_crop = 21

    print(f"\n{'='*80}")
    print(f"Mech {evolution_level} - {resolution.upper()} Resolution Frame Transition Analysis")
    print(f"{'='*80}\n")

    # Find all walk frames
    walk_files = sorted(folder.glob(f"{evolution_level}_walk_*.png"))

    if not walk_files:
        print(f"❌ No walk files found in {folder}")
        return

    print(f"Found {len(walk_files)} frames")
    print(f"Crop values: top={top_crop}px, bottom={bottom_crop}px\n")

    # Analyze each frame
    frame_positions = []

    for png_path in walk_files:
        with Image.open(png_path) as img:
            width, height = img.size

            # Apply cropping
            cropped = img.crop((0, top_crop, width, height - bottom_crop))
            cropped_width, cropped_height = cropped.size

            # Get bounding box
            bbox = cropped.getbbox()

            if bbox:
                # Position of content top edge (how far from top of cropped image)
                content_top = bbox[1]
                # Position of content bottom edge (how far from bottom of cropped image)
                content_bottom = cropped_height - bbox[3]
                # Height of actual content
                content_height = bbox[3] - bbox[1]
            else:
                content_top = 0
                content_bottom = 0
                content_height = 0

            frame_positions.append({
                'frame': png_path.name,
                'frame_num': int(png_path.stem.split('_')[-1]),
                'content_top': content_top,
                'content_bottom': content_bottom,
                'content_height': content_height,
                'bbox': bbox
            })

    # Sort by frame number
    frame_positions.sort(key=lambda x: x['frame_num'])

    # Print header
    print(f"{'Frame':<20} {'Content Top':<14} {'Δ from prev':<14} {'Content Height':<16} {'Quality':<10}")
    print(f"{'-'*80}")

    # Calculate transitions
    prev_top = None
    max_jump = 0
    max_jump_transition = None
    total_variation = 0

    for i, data in enumerate(frame_positions):
        if prev_top is not None:
            delta = data['content_top'] - prev_top
            total_variation += abs(delta)

            # Track maximum jump
            if abs(delta) > max_jump:
                max_jump = abs(delta)
                max_jump_transition = (i-1, i, delta)

            # Quality indicator
            if abs(delta) <= 2:
                quality = "✅ Perfect"
            elif abs(delta) <= 5:
                quality = "✓ Good"
            elif abs(delta) <= 10:
                quality = "⚠ Fair"
            else:
                quality = "❌ Poor"

            delta_str = f"{delta:+d}px"
        else:
            delta_str = "—"
            quality = "—"

        print(f"{data['frame']:<20} {data['content_top']:<14} {delta_str:<14} "
              f"{data['content_height']:<16} {quality:<10}")

        prev_top = data['content_top']

    # Summary statistics
    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"{'-'*80}")

    content_tops = [d['content_top'] for d in frame_positions]
    min_top = min(content_tops)
    max_top = max(content_tops)
    avg_top = sum(content_tops) / len(content_tops)

    print(f"Content Top Range: {min_top}px - {max_top}px (variation: {max_top - min_top}px)")
    print(f"Average Content Top: {avg_top:.1f}px")
    print(f"Total Movement: {total_variation}px over {len(frame_positions)-1} transitions")
    print(f"Average Movement per Transition: {total_variation/(len(frame_positions)-1):.1f}px")

    if max_jump_transition:
        from_frame, to_frame, delta = max_jump_transition
        print(f"\n❌ LARGEST JUMP: {max_jump}px")
        print(f"   From: {frame_positions[from_frame]['frame']} (top={frame_positions[from_frame]['content_top']}px)")
        print(f"   To:   {frame_positions[to_frame]['frame']} (top={frame_positions[to_frame]['content_top']}px)")
        print(f"   Delta: {delta:+d}px")

    # Identify problematic frames
    print(f"\n{'='*80}")
    print(f"PROBLEMATIC TRANSITIONS (>5px jump):")
    print(f"{'-'*80}")

    prev_top = None
    found_problems = False
    for i, data in enumerate(frame_positions):
        if prev_top is not None:
            delta = data['content_top'] - prev_top
            if abs(delta) > 5:
                found_problems = True
                print(f"  {frame_positions[i-1]['frame']} → {data['frame']}: {delta:+d}px")
        prev_top = data['content_top']

    if not found_problems:
        print(f"  ✅ No problematic transitions found!")

    # Recommendation
    print(f"\n{'='*80}")
    print(f"RECOMMENDATION:")
    print(f"{'-'*80}")

    if max_top - min_top <= 5:
        print(f"✅ EXCELLENT alignment - ready to use!")
    elif max_top - min_top <= 10:
        print(f"✓ GOOD alignment - acceptable for most uses")
        print(f"  Consider adjusting crop to center: top={top_crop + int(avg_top)}px")
    else:
        print(f"⚠️  POOR alignment - animation will appear to 'bounce'")
        print(f"  Option 1: Adjust crop to minimize bounce (top={top_crop + int(avg_top)}px)")
        print(f"  Option 2: Request artist to align all frames to same vertical position")
        print(f"  Option 3: Manually align frames in image editor")


if __name__ == "__main__":
    assets_dir = Path("/Volumes/appdata/dockerdiscordcontrol/assets/mech_evolutions")

    # Analyze big resolution
    analyze_frame_transitions(assets_dir, evolution_level=10, resolution="big")

    # Also analyze small for comparison
    print("\n\n")
    analyze_frame_transitions(assets_dir, evolution_level=10, resolution="small")
