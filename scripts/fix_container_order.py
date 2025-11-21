#!/usr/bin/env python3
"""Fix container order values to be sequential and unique."""

import json
from pathlib import Path

def fix_container_order():
    """Reset container order values to be sequential."""

    containers_dir = Path("config/containers")
    containers = []

    print("=" * 70)
    print("FIXING CONTAINER ORDER")
    print("=" * 70)

    # Load all containers
    for f in containers_dir.glob("*.json"):
        with open(f) as file:
            data = json.load(file)
            containers.append({
                'file': f,
                'data': data,
                'name': data.get('container_name', f.stem),
                'order': data.get('order', 999),
                'active': data.get('active', False)
            })

    # Sort by current order, then by name for consistency
    containers.sort(key=lambda x: (x['order'], x['name']))

    print("\nCurrent order (broken):")
    print("-" * 50)
    for c in containers:
        active_str = 'ACTIVE' if c['active'] else 'inactive'
        print(f"  Order: {c['order']:3d} | {active_str:8s} | {c['name']}")

    # Separate active and inactive containers
    active_containers = [c for c in containers if c['active']]
    inactive_containers = [c for c in containers if not c['active']]

    # Sort active containers by their current order, then name
    active_containers.sort(key=lambda x: (x['order'], x['name']))

    # Sort inactive containers by name (order doesn't matter for them)
    inactive_containers.sort(key=lambda x: x['name'])

    print("\n\nNew order (fixed):")
    print("-" * 50)

    # Assign sequential order to active containers starting from 0
    for i, container in enumerate(active_containers):
        new_order = i
        container['data']['order'] = new_order
        print(f"  Order: {new_order:3d} | ACTIVE   | {container['name']}")

    # Assign order to inactive containers starting after active ones
    start_order = len(active_containers)
    for i, container in enumerate(inactive_containers):
        new_order = start_order + i
        container['data']['order'] = new_order
        print(f"  Order: {new_order:3d} | inactive | {container['name']}")

    # Save all containers back to files
    print("\nSaving fixed order to JSON files...")
    for container in containers:
        with open(container['file'], 'w') as f:
            json.dump(container['data'], f, indent=2)
        print(f"  ✓ Saved {container['file'].name}")

    print("\n" + "=" * 70)
    print("✅ Container order has been fixed!")
    print("=" * 70)

    # Show expected Discord display order
    print("\nExpected Discord display order (active containers only):")
    print("-" * 50)
    for i, c in enumerate(active_containers):
        print(f"  {i+1}. {c['name']}")

    print("\nThis order should now be consistent across:")
    print("  ✓ Web UI")
    print("  ✓ Status Overview (/ss)")
    print("  ✓ Control Channel messages")

if __name__ == "__main__":
    fix_container_order()
