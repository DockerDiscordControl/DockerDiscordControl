#!/usr/bin/env python3
"""Update order values for remaining containers."""

import json
from pathlib import Path

# Define the correct order for all containers
correct_orders = {
    # Active containers (0-5)
    "Icarus": 0,
    "Icarus2": 1,
    "ProjectZomboid": 2,
    "Satisfactory": 3,
    "V-Rising": 4,
    "Valheim": 5,
    # Inactive containers (6-11)
    "AdGuard-Home": 6,
    "NginxProxyManager": 7,
    "dockerdiscordcontrol": 8,
    "duckdns": 9,
    "plex": 10,
    "transmission": 11
}

containers_dir = Path("config/containers")

print("Updating container order values...")
print("-" * 50)

for container_name, new_order in correct_orders.items():
    json_file = containers_dir / f"{container_name}.json"

    if not json_file.exists():
        print(f"  ⚠️  {container_name}.json not found")
        continue

    try:
        # Read current data
        with open(json_file, 'r') as f:
            data = json.load(f)

        # Update order
        old_order = data.get('order', 999)
        data['order'] = new_order

        # Skip Icarus2 if it's protected
        if container_name == "Icarus2":
            print(f"  ⏭️  {container_name}: Order already updated (protected file)")
            continue

        # Save back
        try:
            with open(json_file, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"  ✓ {container_name}: {old_order} → {new_order}")
        except PermissionError:
            print(f"  ⚠️  {container_name}: Permission denied (order should be {new_order})")
    except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
        print(f"  ❌ {container_name}: Error - {e}")

print("\n" + "=" * 50)
print("Order update complete!")
print("=" * 50)