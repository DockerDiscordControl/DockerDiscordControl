#!/usr/bin/env python3
"""Fix snapshot goal to use member-exact calculation instead of bin-based."""

import json
from pathlib import Path
from services.mech.progress_service import requirement_for_level_and_bin

# Read current snapshot
snapshot_file = Path("config/progress/snapshots/main.json")
snap = json.loads(snapshot_file.read_text())

print("=" * 80)
print("FIXING SNAPSHOT GOAL CALCULATION")
print("=" * 80)
print()

print(f"Current Snapshot State:")
print(f"  Level: {snap['level']}")
print(f"  Member Count: {snap['last_user_count_sample']}")
print(f"  Current Goal: ${snap['goal_requirement']/100:.2f} (OLD bin-based)")
print()

# Calculate new goal using member-exact formula
level = snap['level']
member_count = snap['last_user_count_sample']
bin_num = snap['difficulty_bin']

# Call with member_count for precise calculation
new_goal = requirement_for_level_and_bin(level, bin_num, member_count=member_count)

print(f"New Goal Calculation (Member-Exact):")
print(f"  Level: {level}")
print(f"  Member Count: {member_count}")
print(f"  New Goal: ${new_goal/100:.2f}")
print()

# Update snapshot
old_goal = snap['goal_requirement']
snap['goal_requirement'] = new_goal

# Save updated snapshot
with open(snapshot_file, 'w', encoding='utf-8') as f:
    json.dump(snap, f, indent=2)

print(f"✅ Snapshot Updated!")
print(f"   ${old_goal/100:.2f} → ${new_goal/100:.2f}")
print()

# Show impact on progress percentage
evo_acc = snap['evo_acc']
print(f"Progress Impact:")
print(f"  Before: ${evo_acc/100:.2f}/${old_goal/100:.2f} = {evo_acc/old_goal*100:.1f}%")
print(f"  After:  ${evo_acc/100:.2f}/${new_goal/100:.2f} = {evo_acc/new_goal*100:.1f}%")
print()
print("=" * 80)
