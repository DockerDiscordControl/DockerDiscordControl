#!/usr/bin/env python3
"""Reset container order values to be sequential."""

import json
from pathlib import Path

def reset_container_order():
    """Reset container order values to be sequential based on current order."""

    containers_dir = Path("config/containers")
    containers = []

    print("=" * 60)
    print("RESETTING CONTAINER ORDER")
    print("=" * 60)

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

    # Sort by current order, then by name
    containers.sort(key=lambda x: (x['order'], x['name']))

    print("\nCurrent order:")
    print("-" * 40)
    for c in containers:
        active_str = 'ACTIVE' if c['active'] else 'inactive'
        print(f"  Order: {c['order']:3d} | {active_str:8s} | {c['name']}")

    # Reassign sequential order values
    print("\n\nNew order:")
    print("-" * 40)

    for i, container in enumerate(containers):
        new_order = i
        container['data']['order'] = new_order

        # Save back to file
        with open(container['file'], 'w') as f:
            json.dump(container['data'], f, indent=2)

        active_str = 'ACTIVE' if container['active'] else 'inactive'
        print(f"  Order: {new_order:3d} | {active_str:8s} | {container['name']}")

    print("\n" + "=" * 60)
    print("✅ Container order has been reset to sequential values!")
    print("=" * 60)

    # Show expected Discord display order for active containers only
    active_containers = [c for c in containers if c['active']]
    print("\nExpected Discord display order (active containers only):")
    print("-" * 40)
    for i, c in enumerate(active_containers):
        print(f"  {i+1}. {c['name']}")

if __name__ == "__main__":
    reset_container_order()