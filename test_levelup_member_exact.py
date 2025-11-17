#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Test level-up with member-exact cost calculation."""

import json
from pathlib import Path
from services.donation.unified_donation_service import process_test_donation, reset_all_donations
from services.mech.progress_service import get_progress_service

print("=" * 80)
print("LEVEL-UP TEST WITH MEMBER-EXACT COST CALCULATION")
print("=" * 80)
print()

# Reset to clean state
print("Resetting to Level 1...")
reset_result = reset_all_donations(source='test')
print(f"✅ Reset complete")
print()

# Manually set member count to specific test values
progress_service = get_progress_service()

def test_levelup_with_member_count(member_count: int, expected_next_goal_cents: int):
    """Test that leveling up sets correct goal for next level based on member count."""

    print(f"TEST: Level-up with {member_count} members")
    print(f"Expected next goal: ${expected_next_goal_cents/100:.2f}")

    # Set member count
    progress_service.update_member_count(member_count)

    # Read current snapshot
    snap_file = Path("config/progress/snapshots/main.json")
    snap = json.loads(snap_file.read_text())

    current_level = snap['level']
    current_goal = snap['goal_requirement']

    print(f"  Current: Level {current_level}, Goal ${current_goal/100:.2f}")

    # Donate enough to level up (current goal + $0.01)
    donation_amount = int((current_goal / 100) + 1)
    result = process_test_donation(f"Tester{member_count}", donation_amount)

    if not result.success:
        print(f"  ❌ Donation failed: {result.error_message}")
        return False

    # Read new snapshot
    snap = json.loads(snap_file.read_text())
    new_level = snap['level']
    new_goal = snap['goal_requirement']
    new_member_count = snap['last_user_count_sample']

    print(f"  After donation: Level {new_level}, Goal ${new_goal/100:.2f}, Members {new_member_count}")

    # Verify level increased
    if new_level != current_level + 1:
        print(f"  ❌ Level did not increase! {current_level} → {new_level}")
        return False

    # Verify goal matches expected
    if new_goal != expected_next_goal_cents:
        print(f"  ❌ Goal WRONG! Expected ${expected_next_goal_cents/100:.2f}, Got ${new_goal/100:.2f}")
        return False

    # Verify member count stored correctly
    if new_member_count != member_count:
        print(f"  ❌ Member count not stored! Expected {member_count}, Got {new_member_count}")
        return False

    print(f"  ✅ PASS: Leveled up to {new_level}, goal set to ${new_goal/100:.2f}")
    print()
    return True

# Test cases with expected Level 2 goals
print("Running level-up tests with different member counts:")
print()

all_passed = True

# Level 2 base cost is $15.00 (increases $5 per level)
# Dynamic cost: (members - 10) × $0.10 if > 10, else $0

test_cases = [
    (1, 1500),      # 1 member: $15.00 base + $0.00 dynamic
    (10, 1500),     # 10 members: $15.00 base + $0.00 dynamic (last freebie)
    (11, 1510),     # 11 members: $15.00 base + $0.10 dynamic
    (25, 1650),     # 25 members: $15.00 base + $1.50 dynamic
    (50, 1900),     # 50 members: $15.00 base + $4.00 dynamic
]

for member_count, expected_goal in test_cases:
    # Reset before each test
    reset_all_donations(source='test')

    # Run test
    if not test_levelup_with_member_count(member_count, expected_goal):
        all_passed = False

print("=" * 80)
if all_passed:
    print("🎉 ALL LEVEL-UP TESTS PASSED!")
    print("Member-exact cost calculation working correctly during level-ups!")
else:
    print("❌ SOME TESTS FAILED!")
print("=" * 80)
