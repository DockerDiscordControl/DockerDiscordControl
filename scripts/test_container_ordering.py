#!/usr/bin/env python3
"""Test container ordering functionality."""

import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.config.config_service import get_config_service

def test_container_ordering():
    """Test that container ordering is preserved and respected."""

    config_service = get_config_service()
    containers_dir = Path("/Volumes/appdata/dockerdiscordcontrol/config/containers")

    print("=" * 60)
    print("Container Ordering Test")
    print("=" * 60)

    # Read all container files and check their order values
    print("\n1. Checking order values in container JSON files:")
    print("-" * 40)

    container_orders = []
    for container_file in containers_dir.glob("*.json"):
        with open(container_file, 'r') as f:
            data = json.load(f)

        name = data.get('container_name', container_file.stem)
        order = data.get('order', 999)
        active = data.get('active', False)

        container_orders.append({
            'name': name,
            'order': order,
            'active': active
        })

        status = "✓ ACTIVE" if active else "  inactive"
        print(f"  {status} | Order: {order:3d} | {name}")

    # Sort by order
    container_orders.sort(key=lambda x: x['order'])

    print("\n2. Sorted container list (by order value):")
    print("-" * 40)
    for i, container in enumerate(container_orders):
        status = "✓ ACTIVE" if container['active'] else "  inactive"
        print(f"  {i+1:2d}. {status} | Order: {container['order']:3d} | {container['name']}")

    # Check active containers from config service
    print("\n3. Active containers from config service (Discord display):")
    print("-" * 40)

    servers = config_service._load_all_containers_from_files()
    for i, server in enumerate(servers):
        name = server.get('container_name', 'Unknown')
        order = server.get('order', 999)
        print(f"  {i+1:2d}. Order: {order:3d} | {name}")

    # Verify order is sequential for active containers
    print("\n4. Order validation:")
    print("-" * 40)

    active_containers = [c for c in container_orders if c['active']]
    if active_containers:
        print(f"  Active containers: {len(active_containers)}")

        # Check if orders are reasonable (not all 999)
        unique_orders = set(c['order'] for c in active_containers)
        if len(unique_orders) == 1 and 999 in unique_orders:
            print("  ⚠️  WARNING: All active containers have default order (999)")
            print("     The + and - buttons may not have been used yet")
        else:
            print(f"  ✓ Containers have unique order values: {sorted(unique_orders)}")

        # Check for duplicate orders
        order_counts = {}
        for c in active_containers:
            order = c['order']
            if order not in order_counts:
                order_counts[order] = []
            order_counts[order].append(c['name'])

        duplicates = {k: v for k, v in order_counts.items() if len(v) > 1}
        if duplicates:
            print("  ⚠️  WARNING: Duplicate order values found:")
            for order, names in duplicates.items():
                print(f"     Order {order}: {', '.join(names)}")
        else:
            print("  ✓ No duplicate order values")
    else:
        print("  No active containers found")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

    # Test UI instructions
    print("\nTo test the Web UI ordering:")
    print("1. Open http://192.168.1.249:8374")
    print("2. Go to 'Container Selection & Bot Permissions'")
    print("3. Use + and - buttons to change order")
    print("4. Save configuration")
    print("5. Run this script again to verify order was saved")
    print("\nThe order should match what you see in Discord messages")

if __name__ == "__main__":
    test_container_ordering()
