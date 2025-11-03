#!/usr/bin/env python3
"""Fix Web UI container ordering to use the order field from JSON files."""

import json
from pathlib import Path

def analyze_ordering_issue():
    """Analyze the current ordering issue in Web UI."""

    print("=" * 70)
    print("WEB UI CONTAINER ORDERING ANALYSIS")
    print("=" * 70)

    # Load container order from JSON files
    containers_dir = Path("config/containers")
    container_orders = {}

    for f in containers_dir.glob("*.json"):
        with open(f) as file:
            data = json.load(f)
            name = data.get('container_name', f.stem)
            order = data.get('order', 999)
            active = data.get('active', False)
            container_orders[name] = {
                'order': order,
                'active': active,
                'display_name': data.get('display_name', [name, name])
            }

    print("\nContainer order values from JSON files:")
    print("-" * 50)
    sorted_containers = sorted(container_orders.items(), key=lambda x: x[1]['order'])
    for name, info in sorted_containers:
        if info['active']:
            print(f"  Order {info['order']:2d} | {name:20s} | {info['display_name'][0]}")

    print("\n" + "=" * 70)
    print("PROBLEM IDENTIFIED:")
    print("=" * 70)
    print("✗ Web UI sorts containers alphabetically by name")
    print("✗ Should sort by 'order' field from JSON files")
    print()
    print("SOLUTION:")
    print("-" * 50)
    print("Need to modify configuration_page_service.py to:")
    print("1. Load order values from container JSON files")
    print("2. Sort live_containers by order before passing to template")
    print("3. Ensure JavaScript maintains order when rows are moved")

    print("\n" + "=" * 70)
    print("FILES TO MODIFY:")
    print("=" * 70)
    print("1. services/web/configuration_page_service.py")
    print("   - Add order loading in _process_docker_containers()")
    print("   - Sort containers by order")
    print()
    print("2. app/utils/web_helpers.py")
    print("   - Remove alphabetical sorting (line 312)")
    print("   - Let configuration_page_service handle sorting")

if __name__ == "__main__":
    analyze_ordering_issue()