#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Calculate dynamic costs with 10-member freebie + $0.10/member after that.

Formula:
- 0-10 Members: $0 dynamic cost
- 11+ Members: $0.10 × (Members - 10)
"""

import json

# Difficulty bins from config
bins = [0, 25, 50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 7500, 10000]

FREEBIE_MEMBERS = 10
COST_PER_MEMBER_CENTS = 10  # $0.10 = 10 cents

print("=" * 80)
print("MEMBER-BASED COSTS: 10 Members frei, dann +$0.10/Member")
print("=" * 80)
print()

# Calculate dynamic costs based on bin maximum (in cents)
dynamic_costs = {}

for i in range(len(bins) - 1):
    bin_num = i + 1
    min_members = bins[i]
    max_members = bins[i + 1]

    # Use maximum of bin range as reference
    if max_members <= FREEBIE_MEMBERS:
        # Within freebie range
        cost_cents = 0
    else:
        # Calculate cost for members beyond freebie
        billable_members = max_members - FREEBIE_MEMBERS
        cost_cents = billable_members * COST_PER_MEMBER_CENTS

    dynamic_costs[str(bin_num)] = cost_cents

    print(f"Bin {bin_num:2d}: {min_members:5d}-{max_members:5d} Members → ${cost_cents/100:7.2f} dynamic cost")

print()
print("=" * 80)
print("GENERATED CONFIG:")
print("=" * 80)
print()
print(json.dumps({"bin_to_dynamic_cost": dynamic_costs}, indent=2))
print()

# Show examples
print("=" * 80)
print("EXAMPLE COSTS (Level 1→2, Base = $10):")
print("=" * 80)
print()

examples = [
    (1, "0-25 Members"),
    (2, "25-50 Members"),
    (3, "50-100 Members"),
    (5, "150-200 Members"),
    (10, "750-1000 Members"),
    (15, "2500-3000 Members"),
    (20, "7500-10000 Members"),
]

print("┌─────┬──────────────────────────┬──────────┬──────────┬──────────┐")
print("│ Bin │ Community Size           │ Base     │ Dynamic  │ Total    │")
print("├─────┼──────────────────────────┼──────────┼──────────┼──────────┤")

for bin_num, desc in examples:
    base = 1000  # $10
    dynamic = dynamic_costs[str(bin_num)]
    total = base + dynamic
    print(f"│ {bin_num:2d}  │ {desc:24s} │ ${base/100:7.2f} │ ${dynamic/100:7.2f} │ ${total/100:8.2f} │")

print("└─────┴──────────────────────────┴──────────┴──────────┴──────────┘")
print()

print("=" * 80)
print("KEY FEATURES:")
print("=" * 80)
print(f"✅ First {FREEBIE_MEMBERS} members are FREE (no dynamic cost)")
print(f"✅ Each additional member costs ${COST_PER_MEMBER_CENTS/100:.2f}")
print("✅ Fair and progressive pricing")
print("✅ Small communities pay minimum ($10 base only)")
print("✅ Large communities pay reasonable amounts")
print()
print("Examples:")
print(f"  • 10 members:    $10 base + $0 dynamic = $10.00")
print(f"  • 50 members:    $10 base + $4 dynamic = $14.00  (40 × $0.10)")
print(f"  • 200 members:   $10 base + $19 dynamic = $29.00 (190 × $0.10)")
print(f"  • 1000 members:  $10 base + $99 dynamic = $109.00 (990 × $0.10)")
print(f"  • 10000 members: $10 base + $999 dynamic = $1009.00 (9990 × $0.10)")
print()
print("=" * 80)
