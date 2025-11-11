#!/usr/bin/env python3
"""Test member-exact cost calculation."""

import json
from pathlib import Path
from services.mech.progress_service import requirement_for_level_and_bin

# Ensure dynamic mode
mode_file = Path("config/evolution_mode.json")
with open(mode_file, 'w') as f:
    json.dump({
        "use_dynamic": True,
        "difficulty_multiplier": 1.0
    }, f, indent=2)

print("=" * 80)
print("MEMBER-EXACT COST CALCULATION TEST")
print("Formula: First 10 members FREE, then $0.10 per additional member")
print("=" * 80)
print()

# Test cases
test_cases = [
    (1, "1 member (within freebie)"),
    (5, "5 members (within freebie)"),
    (10, "10 members (last freebie)"),
    (11, "11 members (first paid)"),
    (25, "25 members"),
    (50, "50 members"),
    (100, "100 members"),
    (200, "200 members"),
    (1000, "1000 members"),
]

print("┌──────────┬──────────────────────────┬─────────┬─────────┬─────────┐")
print("│ Members  │ Description              │ Base    │ Dynamic │ Total   │")
print("├──────────┼──────────────────────────┼─────────┼─────────┼─────────┤")

for members, desc in test_cases:
    # Call with member_count parameter for exact calculation
    cost = requirement_for_level_and_bin(level=1, b=1, member_count=members)
    base = 1000  # $10
    dynamic = cost - base

    # Calculate expected
    if members <= 10:
        expected_dynamic = 0
    else:
        expected_dynamic = (members - 10) * 10  # $0.10 per member in cents

    status = "✅" if dynamic == expected_dynamic else "❌"

    print(f"│ {members:8d} │ {desc:24s} │ ${base/100:6.2f} │ ${dynamic/100:6.2f} │ ${cost/100:7.2f} │ {status}")

print("└──────────┴──────────────────────────┴─────────┴─────────┴─────────┘")
print()

print("=" * 80)
print("VALIDATION:")
print("=" * 80)
print()

# Validate key points
tests = [
    (1, 1000, "1 member should cost $10 (base only)"),
    (10, 1000, "10 members should cost $10 (base only)"),
    (11, 1010, "11 members should cost $10.10 (base + $0.10)"),
    (50, 1400, "50 members should cost $14.00 (base + $4.00)"),
    (200, 2900, "200 members should cost $29.00 (base + $19.00)"),
]

all_passed = True
for members, expected_cents, description in tests:
    actual = requirement_for_level_and_bin(level=1, b=1, member_count=members)
    if actual == expected_cents:
        print(f"✅ PASS: {description}")
    else:
        print(f"❌ FAIL: {description}")
        print(f"   Expected: ${expected_cents/100:.2f}, Got: ${actual/100:.2f}")
        all_passed = False

print()
if all_passed:
    print("🎉 ALL TESTS PASSED! Member-exact calculation working correctly!")
else:
    print("❌ SOME TESTS FAILED!")

print("=" * 80)
