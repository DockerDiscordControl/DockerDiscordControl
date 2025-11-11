#!/usr/bin/env python3
"""Calculate member-based dynamic costs: 1 member = +$1"""

import json

# Difficulty bins from config
bins = [0, 25, 50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 7500, 10000]

print("=" * 80)
print("MEMBER-BASED DYNAMIC COSTS: 1 Member = +$1")
print("=" * 80)
print()

# Calculate dynamic costs based on bin maximum (in cents)
dynamic_costs = {}

for i in range(len(bins) - 1):
    bin_num = i + 1
    min_members = bins[i]
    max_members = bins[i + 1]

    # Use maximum of bin range as reference
    # 1 member = 100 cents = $1
    cost_cents = max_members * 100

    dynamic_costs[str(bin_num)] = cost_cents

    print(f"Bin {bin_num:2d}: {min_members:5d}-{max_members:5d} Members → ${cost_cents/100:8.2f} dynamic cost")

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
    (21, "10000+ Members"),
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
