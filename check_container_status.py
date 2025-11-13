#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to check the status of all containers (active/inactive).
Shows which containers are active and which are not.
"""

import json
from pathlib import Path

def check_container_status():
    """Check and display the active status of all containers."""
    containers_dir = Path('config/containers')

    if not containers_dir.exists():
        print(f"❌ Error: {containers_dir} does not exist!")
        return

    print("📋 Container Status Report\n")
    print("=" * 80)

    active_containers = []
    inactive_containers = []

    for container_file in sorted(containers_dir.glob('*.json')):
        try:
            with open(container_file, 'r') as f:
                container_config = json.load(f)

            container_name = container_config.get('container_name', container_file.stem)
            is_active = container_config.get('active', False)
            display_name = container_config.get('display_name', container_name)
            allowed_actions = container_config.get('allowed_actions', [])

            container_info = {
                'name': container_name,
                'display_name': display_name,
                'actions': allowed_actions,
                'active': is_active
            }

            if is_active:
                active_containers.append(container_info)
            else:
                inactive_containers.append(container_info)

        except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            print(f"❌ Error reading {container_file.name}: {e}")

    # Display active containers
    print(f"\n✅ ACTIVE CONTAINERS ({len(active_containers)}):")
    print("-" * 80)
    if active_containers:
        for c in active_containers:
            actions_str = ', '.join(c['actions']) if c['actions'] else 'none'
            print(f"  • {c['name']:<25} Display: {c['display_name']:<25}")
            print(f"    Actions: {actions_str}")
    else:
        print("  (No active containers)")

    # Display inactive containers
    print(f"\n❌ INACTIVE CONTAINERS ({len(inactive_containers)}):")
    print("-" * 80)
    if inactive_containers:
        for c in inactive_containers:
            actions_str = ', '.join(c['actions']) if c['actions'] else 'none'
            print(f"  • {c['name']:<25} Display: {c['display_name']:<25}")
            print(f"    Actions: {actions_str}")
            print(f"    ⚠️  Configuration exists but container is NOT shown in Discord")
    else:
        print("  (All containers are active)")

    # Summary
    print("\n" + "=" * 80)
    print(f"📊 SUMMARY:")
    print(f"   Total containers: {len(active_containers) + len(inactive_containers)}")
    print(f"   Active (shown in Discord): {len(active_containers)}")
    print(f"   Inactive (hidden from Discord): {len(inactive_containers)}")

    if inactive_containers:
        print(f"\n💡 TIP:")
        print(f"   To reactivate inactive containers:")
        print(f"   1. Run: python3 reactivate_containers.py")
        print(f"   2. Or manually edit the container JSON files and set 'active': true")
        print(f"   3. Or use the Web UI: Check the 'Active' checkbox and save")
        print(f"   4. Then restart: docker restart dockerdiscordcontrol")

    print("")

if __name__ == '__main__':
    check_container_status()
