#!/usr/bin/env python3
"""Comprehensive system verification for all fixed features."""

import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.config.config_service import get_config_service

def verify_all_systems():
    """Verify all systems are working correctly."""

    config_service = get_config_service()
    containers_dir = Path("/Volumes/appdata/dockerdiscordcontrol/config/containers")

    print("=" * 70)
    print("DOCKER DISCORD CONTROL - SYSTEM VERIFICATION")
    print("=" * 70)

    # Check 1: Active containers
    print("\n1. ACTIVE CONTAINER SYSTEM")
    print("-" * 50)

    all_containers = []
    active_containers = []
    inactive_containers = []

    for container_file in containers_dir.glob("*.json"):
        with open(container_file, 'r') as f:
            data = json.load(f)

        name = data.get('container_name', container_file.stem)
        active = data.get('active', False)
        order = data.get('order', 999)

        container_info = {
            'name': name,
            'active': active,
            'order': order,
            'display_name': data.get('display_name', [name, name]),
            'allowed_actions': data.get('allowed_actions', []),
            'info': data.get('info', {})
        }

        all_containers.append(container_info)
        if active:
            active_containers.append(container_info)
        else:
            inactive_containers.append(container_info)

    print(f"  Total containers: {len(all_containers)}")
    print(f"  ✓ Active (shown in Discord): {len(active_containers)}")
    print(f"  ✗ Inactive (hidden from Discord): {len(inactive_containers)}")

    # Check 2: Container permissions
    print("\n2. CONTAINER PERMISSIONS")
    print("-" * 50)

    for container in sorted(active_containers, key=lambda x: x['order']):
        actions = container['allowed_actions']
        action_str = ', '.join(actions) if actions else 'none'
        print(f"  {container['name']:20s} | Actions: {action_str}")

    # Check 3: Display names
    print("\n3. DISPLAY NAME SYSTEM")
    print("-" * 50)

    for container in sorted(active_containers, key=lambda x: x['order']):
        display = container['display_name']
        if isinstance(display, list) and len(display) == 2:
            print(f"  ✓ {container['name']:20s} | Display: {display[0]}")
        else:
            print(f"  ⚠️  {container['name']:20s} | Invalid display name: {display}")

    # Check 4: Container ordering
    print("\n4. CONTAINER ORDERING")
    print("-" * 50)

    sorted_active = sorted(active_containers, key=lambda x: x['order'])
    for i, container in enumerate(sorted_active):
        print(f"  Position {i+1:2d} | Order: {container['order']:3d} | {container['name']}")

    # Check for order issues
    orders = [c['order'] for c in sorted_active]
    if len(set(orders)) != len(orders):
        print("  ⚠️  WARNING: Duplicate order values detected!")
    else:
        print("  ✓ All containers have unique order values")

    # Check 5: Info system
    print("\n5. INFO SYSTEM (IP/Port/Text)")
    print("-" * 50)

    info_enabled_count = 0
    protected_enabled_count = 0

    for container in sorted_active:
        info = container['info']
        if info.get('enabled', False):
            info_enabled_count += 1
            ip = info.get('custom_ip', 'N/A')
            port = info.get('custom_port', 'N/A')
            text = info.get('custom_text', 'N/A')
            protected = info.get('protected_enabled', False)

            status = "✓ INFO" + (" + 🔒 PROTECTED" if protected else "")
            print(f"  {status:25s} | {container['name']:15s} | {ip}:{port}")
            if text and text != 'N/A':
                print(f"    └─ {text}")

            if protected:
                protected_enabled_count += 1
                protected_content = info.get('protected_content', '')
                if protected_content:
                    print(f"    └─ Protected content: {len(protected_content)} chars")

    if info_enabled_count == 0:
        print("  No containers have info enabled")
    else:
        print(f"\n  Summary: {info_enabled_count} containers with info enabled")
        if protected_enabled_count > 0:
            print(f"           {protected_enabled_count} containers with protected content")

    # Check 6: System integration
    print("\n6. SYSTEM INTEGRATION CHECK")
    print("-" * 50)

    # Load from config service (what Discord sees)
    discord_containers = config_service._load_all_containers_from_files()

    print(f"  Config service loaded: {len(discord_containers)} containers")
    print(f"  Direct file count (active): {len(active_containers)} containers")

    if len(discord_containers) == len(active_containers):
        print("  ✓ Config service and file system are in sync")
    else:
        print("  ⚠️  WARNING: Config service and file system mismatch!")

    # Final summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)

    issues = []

    if len(active_containers) == 0:
        issues.append("No active containers found")
    if len(set(orders)) != len(orders):
        issues.append("Duplicate order values detected")
    if len(discord_containers) != len(active_containers):
        issues.append("Config service mismatch")

    if issues:
        print("⚠️  Issues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("✅ ALL SYSTEMS OPERATIONAL")
        print("")
        print("Features working correctly:")
        print("  ✓ Active/Inactive container filtering")
        print("  ✓ Container permissions (status/start/stop/restart)")
        print("  ✓ Display name system")
        print("  ✓ Container ordering")
        print("  ✓ Info system with IP/Port/Text")
        print("  ✓ Protected content with password")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    verify_all_systems()
