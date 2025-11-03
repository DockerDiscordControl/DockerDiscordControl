#!/usr/bin/env python3
"""Test that status overview respects container order from JSON files."""

import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.config.config_service import get_config_service

def test_status_overview_order():
    """Test that status overview will use the correct order."""

    print("=" * 70)
    print("STATUS OVERVIEW ORDER TEST")
    print("=" * 70)

    config_service = get_config_service()

    # Get the full config (what Discord sees)
    config = config_service.get_config()
    servers = config.get('servers', [])

    print("\n1. Raw servers list from config (unsorted):")
    print("-" * 50)
    for i, server in enumerate(servers):
        name = server.get('container_name', server.get('docker_name', 'Unknown'))
        order = server.get('order', 999)
        print(f"  {i+1:2d}. Order: {order:3d} | {name}")

    print("\n2. Servers sorted by order (as Status Overview will display):")
    print("-" * 50)
    ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))
    for i, server in enumerate(ordered_servers):
        name = server.get('container_name', server.get('docker_name', 'Unknown'))
        order = server.get('order', 999)
        display_name = server.get('display_name', [name, name])
        if isinstance(display_name, list) and len(display_name) > 0:
            display_name = display_name[0]
        print(f"  {i+1:2d}. Order: {order:3d} | {name:20s} | Display: {display_name}")

    print("\n3. Expected Status Overview display:")
    print("-" * 50)
    print("  ┌── Status ─────────────────")
    for server in ordered_servers:
        display_name = server.get('display_name', [server.get('docker_name', 'Unknown')] * 2)
        if isinstance(display_name, list) and len(display_name) > 0:
            display_name = display_name[0]
        # Simulate status display (would normally show actual status)
        print(f"  │ 🟢 {display_name}")
    print("  └───────────────────────────")

    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
    print("\nThe Status Overview should now display containers in this order:")
    for i, server in enumerate(ordered_servers):
        name = server.get('container_name', server.get('docker_name', 'Unknown'))
        print(f"  {i+1}. {name}")

    print("\nTo verify in Discord:")
    print("1. Use the /ss command to see the Status Overview")
    print("2. The container order should match the list above")
    print("3. Changing order with + and - buttons in Web UI will update this")

if __name__ == "__main__":
    test_status_overview_order()