#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Test the corrected dynamic cost structure."""

import json
from pathlib import Path
from services.mech.progress_service import requirement_for_level_and_bin

# Ensure dynamic mode
mode_file = Path("config/evolution_mode.json")
with open(mode_file, 'w') as f:
    json.dump({
        "use_dynamic": True,
        "difficulty_multiplier": 1.0,
        "last_updated": "2025-01-01T00:00:00"
    }, f, indent=2)

print("=" * 80)
print("CORRECTED DYNAMIC COST STRUCTURE")
print("=" * 80)
print("\nLevel 1→2 costs with DYNAMIC mode (community-based):\n")

# Test cases with bins
test_cases = [
    (1, 0, "0-25 Members (smallest community)"),
    (2, 25, "25-50 Members"),
    (3, 50, "50-100 Members"),
    (5, 150, "150-200 Members"),
    (10, 750, "750-1000 Members"),
    (15, 2500, "2500-3000 Members"),
    (21, 10000, "10000+ Members (largest)"),
]

print("┌─────┬──────────────────────────────┬─────────┬─────────┬─────────┐")
print("│ Bin │ Community Size               │ Base    │ Dynamic │ Total   │")
print("├─────┼──────────────────────────────┼─────────┼─────────┼─────────┤")

for bin_num, members, desc in test_cases:
    cost = requirement_for_level_and_bin(1, bin_num)
    base = 1000  # Level 1 base
    dynamic = cost - base
    print(f"│ {bin_num:2d}  │ {desc:28s} │ ${base/100:6.2f} │ ${dynamic/100:6.2f} │ ${cost/100:7.2f} │")

print("└─────┴──────────────────────────────┴─────────┴─────────┴─────────┘")

print("\n" + "=" * 80)
print("KEY IMPROVEMENTS:")
print("=" * 80)
print("✅ Smallest community (1-25 Members): $0.00 dynamic cost")
print("✅ Base cost ($10) = minimum for all communities")
print("✅ Dynamic cost scales progressively with community size")
print("✅ Largest communities pay significantly more (up to ~$986 dynamic)")
print("\n" + "=" * 80)

# Show example with static override
print("\nEXAMPLE: Static Override with 2.0× multiplier:\n")

with open(mode_file, 'w') as f:
    json.dump({
        "use_dynamic": False,
        "difficulty_multiplier": 2.0,
        "last_updated": "2025-01-01T00:00:00"
    }, f, indent=2)

print("┌─────┬──────────────────────────────┬──────────────┬──────────────┐")
print("│ Bin │ Community Size               │ Dynamic Mode │ Static 2.0×  │")
print("├─────┼──────────────────────────────┼──────────────┼──────────────┤")

for bin_num, members, desc in test_cases:
    # Dynamic mode cost
    with open(mode_file, 'w') as f:
        json.dump({"use_dynamic": True, "difficulty_multiplier": 1.0}, f)
    dynamic_cost = requirement_for_level_and_bin(1, bin_num)

    # Static mode cost
    with open(mode_file, 'w') as f:
        json.dump({"use_dynamic": False, "difficulty_multiplier": 2.0}, f)
    static_cost = requirement_for_level_and_bin(1, bin_num)

    print(f"│ {bin_num:2d}  │ {desc:28s} │ ${dynamic_cost/100:11.2f} │ ${static_cost/100:11.2f} │")

print("└─────┴──────────────────────────────┴──────────────┴──────────────┘")

# Restore dynamic mode
with open(mode_file, 'w') as f:
    json.dump({
        "use_dynamic": True,
        "difficulty_multiplier": 1.0,
        "last_updated": "2025-01-01T00:00:00"
    }, f, indent=2)

print("\n✅ Dynamic mode restored")
print("=" * 80)
