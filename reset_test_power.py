#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to reset power to match evolution (remove test system donations)

This script will:
1. Set power_acc to match evo_acc (removing all test system donations)
2. Keep evolution progress intact
3. Update cumulative to reflect only real donations
"""

import json
from pathlib import Path
import shutil
from datetime import datetime

def reset_power():
    snapshot_file = Path("config/progress/snapshots/main.json")

    # Create backup
    backup_file = snapshot_file.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    shutil.copy2(snapshot_file, backup_file)
    print(f"✅ Backup created: {backup_file}")

    # Load snapshot
    with open(snapshot_file, 'r') as f:
        snap = json.load(f)

    print(f"\n📊 Current State:")
    print(f"  Evolution: ${snap['evo_acc']/100:.2f}")
    print(f"  Power: ${snap['power_acc']/100:.2f}")
    print(f"  Total Donated: ${snap['cumulative_donations_cents']/100:.2f}")

    # Calculate system donations
    system_donations = snap['power_acc'] - snap['evo_acc']
    print(f"\n🔍 Test System Donations: ${system_donations/100:.2f}")

    # Reset power to match evolution (remove test system donations)
    old_power = snap['power_acc']
    snap['power_acc'] = snap['evo_acc']  # Power = Evolution (only real donations)

    # Update cumulative to reflect only real donations
    # Since both evolution and power should be equal for real donations only
    snap['cumulative_donations_cents'] = snap['evo_acc']

    # Increment version
    snap['version'] += 1

    # Save updated snapshot
    with open(snapshot_file, 'w') as f:
        json.dump(snap, f, indent=2)

    print(f"\n✅ Power reset complete!")
    print(f"  Evolution: ${snap['evo_acc']/100:.2f} (unchanged)")
    print(f"  Power: ${old_power/100:.2f} → ${snap['power_acc']/100:.2f}")
    print(f"  Total: ${snap['cumulative_donations_cents']/100:.2f}")

    print(f"\n📝 Note: Test system donation events remain in event log for audit.")
    print(f"        They won't affect the current state after this reset.")

if __name__ == "__main__":
    response = input("⚠️  This will reset power to match evolution ($10.00). Continue? (y/n): ")
    if response.lower() == 'y':
        reset_power()
        print("\n🎉 Done! Restart the bot to see the changes.")
    else:
        print("❌ Cancelled.")