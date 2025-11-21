#!/usr/bin/env python3
"""Test changing container order programmatically."""

import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.config.config_service import get_config_service

def swap_container_order(container1_name, container2_name):
    """Swap the order of two containers."""

    containers_dir = Path("/Volumes/appdata/dockerdiscordcontrol/config/containers")

    # Read both container files
    container1_file = containers_dir / f"{container1_name}.json"
    container2_file = containers_dir / f"{container2_name}.json"

    if not container1_file.exists() or not container2_file.exists():
        print(f"Error: One or both container files not found")
        return False

    # Load container data
    with open(container1_file, 'r') as f:
        container1_data = json.load(f)
    with open(container2_file, 'r') as f:
        container2_data = json.load(f)

    # Get current orders
    order1 = container1_data.get('order', 999)
    order2 = container2_data.get('order', 999)

    print(f"Before swap:")
    print(f"  {container1_name}: order {order1}")
    print(f"  {container2_name}: order {order2}")

    # Swap orders
    container1_data['order'] = order2
    container2_data['order'] = order1

    # Save back to files
    with open(container1_file, 'w') as f:
        json.dump(container1_data, f, indent=2)
    with open(container2_file, 'w') as f:
        json.dump(container2_data, f, indent=2)

    print(f"\nAfter swap:")
    print(f"  {container1_name}: order {container2_data['order']}")
    print(f"  {container2_name}: order {container1_data['order']}")

    return True

def show_current_order():
    """Show the current order of active containers."""

    config_service = get_config_service()
    servers = config_service._load_all_containers_from_files()

    print("\nCurrent Active Container Order:")
    print("-" * 40)
    for i, server in enumerate(servers):
        name = server.get('container_name', 'Unknown')
        order = server.get('order', 999)
        display_name = server.get('display_name', [name, name])[0]
        print(f"  {i+1:2d}. Order: {order:3d} | {name:20s} ({display_name})")

if __name__ == "__main__":
    print("=" * 60)
    print("Container Order Change Test")
    print("=" * 60)

    # Show current order
    show_current_order()

    # Test swapping the first two active containers
    print("\n" + "=" * 60)
    print("Testing order swap: Icarus <-> Icarus2")
    print("=" * 60)

    if swap_container_order("Icarus", "Icarus2"):
        print("\n✓ Swap completed successfully!")

        # Show new order
        show_current_order()

        print("\n" + "=" * 60)
        print("Swapping back to original order...")
        print("=" * 60)

        # Swap back
        if swap_container_order("Icarus", "Icarus2"):
            print("\n✓ Restored original order!")
            show_current_order()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)
    print("\nThe order changes have been saved to the container JSON files.")
    print("This simulates what happens when using the + and - buttons in the Web UI.")
    print("\nTo verify in Discord:")
    print("1. Use the !status command to see the container overview")
    print("2. Check the control channel for individual container messages")
    print("3. The order should match what's shown above")
