#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Frame-by-frame transition analysis INCLUDING loop transition (7→0)."""

from PIL import Image
from pathlib import Path

def analyze_with_loop(assets_dir, evolution_level=10, resolution="big"):
    """Analyze frame-to-frame transitions INCLUDING the loop back to frame 0."""

    folder = assets_dir / f"Mech{evolution_level}" / resolution

    # Crop values
    if resolution == "big":
        top_crop = 44
        bottom_crop = 83
    else:
        top_crop = 12
        bottom_crop = 21

    print(f"\n{'='*80}")
    print(f"Mech {evolution_level} - {resolution.upper()} - Loop Transition Analysis (7→0)")
    print(f"{'='*80}\n")

    # Find all walk frames (exclude backups)
    all_files = folder.glob(f"{evolution_level}_walk_*.png")
    walk_files = sorted([f for f in all_files if '_original' not in f.name])

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
                content_top = bbox[1]
                content_bottom = cropped_height - bbox[3]
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
    print(f"{'Transition':<20} {'Content Top':<14} {'Δ':<10} {'Quality':<12} {'Notes':<20}")
    print(f"{'-'*80}")

    # Calculate transitions INCLUDING loop
    max_jump = 0
    max_jump_transition = None
    total_variation = 0
    transitions = []

    for i in range(len(frame_positions)):
        current = frame_positions[i]
        next_idx = (i + 1) % len(frame_positions)  # Loop back to 0
        next_frame = frame_positions[next_idx]

        delta = next_frame['content_top'] - current['content_top']
        total_variation += abs(delta)

        # Track maximum jump
        if abs(delta) > max_jump:
            max_jump = abs(delta)
            max_jump_transition = (i, next_idx, delta)

        # Quality indicator
        if abs(delta) <= 2:
            quality = "✅ Perfect"
        elif abs(delta) <= 5:
            quality = "✓ Good"
        elif abs(delta) <= 10:
            quality = "⚠️ Fair"
        else:
            quality = "❌ Poor"

        delta_str = f"{delta:+d}px"

        # Special note for loop transition
        is_loop = (next_idx == 0)
        notes = "🔄 LOOP" if is_loop else ""

        transition_name = f"{i}→{next_idx}"

        print(f"{transition_name:<20} {current['content_top']:>3}→{next_frame['content_top']:<3}px      "
              f"{delta_str:<10} {quality:<12} {notes:<20}")

        transitions.append({
            'from': i,
            'to': next_idx,
            'delta': delta,
            'is_loop': is_loop,
            'quality': quality
        })

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
    print(f"Total Movement: {total_variation}px over {len(transitions)} transitions")
    print(f"Average Movement per Transition: {total_variation/len(transitions):.1f}px")

    if max_jump_transition:
        from_frame, to_frame, delta = max_jump_transition
        is_loop_jump = (to_frame == 0 and from_frame == len(frame_positions) - 1)
        print(f"\n❌ LARGEST JUMP: {max_jump}px {'🔄 (LOOP TRANSITION!)' if is_loop_jump else ''}")
        print(f"   From: Frame {from_frame} (top={frame_positions[from_frame]['content_top']}px)")
        print(f"   To:   Frame {to_frame} (top={frame_positions[to_frame]['content_top']}px)")
        print(f"   Delta: {delta:+d}px")

    # Identify problematic transitions
    print(f"\n{'='*80}")
    print(f"ALL TRANSITIONS (sorted by jump size):")
    print(f"{'-'*80}")

    # Sort by absolute delta
    sorted_transitions = sorted(transitions, key=lambda x: abs(x['delta']), reverse=True)

    for trans in sorted_transitions:
        from_frame = trans['from']
        to_frame = trans['to']
        delta = trans['delta']
        loop_marker = "🔄 LOOP" if trans['is_loop'] else ""
        quality = trans['quality']

        print(f"  {from_frame}→{to_frame}: {delta:+3d}px  {quality:<12} {loop_marker}")


if __name__ == "__main__":
    assets_dir = Path("/Volumes/appdata/dockerdiscordcontrol/assets/mech_evolutions")

    # Analyze big resolution
    analyze_with_loop(assets_dir, evolution_level=10, resolution="big")

    # Also analyze small for comparison
    print("\n\n")
    analyze_with_loop(assets_dir, evolution_level=10, resolution="small")
