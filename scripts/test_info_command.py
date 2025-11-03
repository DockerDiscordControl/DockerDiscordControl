#!/usr/bin/env python3
"""Test that the /info command can read container info correctly."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.infrastructure.container_info_service import get_container_info_service

def test_info_command():
    """Test that container info is loaded correctly."""

    print("=" * 70)
    print("CONTAINER INFO SERVICE TEST")
    print("=" * 70)

    info_service = get_container_info_service()

    # Test loading info for various containers
    test_containers = ["Icarus", "Icarus2", "Valheim", "ProjectZomboid", "Satisfactory", "V-Rising"]

    print("\nTesting container info loading:")
    print("-" * 50)

    for container_name in test_containers:
        result = info_service.get_container_info(container_name)

        if result.success and result.data:
            info = result.data
            print(f"\n{container_name}:")
            print(f"  Enabled:           {info.enabled}")
            print(f"  Show IP:           {info.show_ip}")
            print(f"  Custom IP:         {info.custom_ip or 'Not set'}")
            print(f"  Custom Port:       {info.custom_port or 'Not set'}")
            print(f"  Custom Text:       {info.custom_text or 'Not set'}")
            print(f"  Protected Enabled: {info.protected_enabled}")
            if info.protected_enabled:
                print(f"  Protected Content: {'Set' if info.protected_content else 'Not set'}")
                print(f"  Protected Pass:    {'Set' if info.protected_password else 'Not set'}")
        else:
            print(f"\n{container_name}: ERROR - {result.error}")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

    # Test specific Icarus container
    print("\nDetailed test for Icarus container:")
    print("-" * 50)

    result = info_service.get_container_info("Icarus")
    if result.success and result.data:
        info = result.data
        if info.enabled:
            print("✅ Icarus info is ENABLED")
            print(f"   IP: {info.custom_ip}:{info.custom_port}")
            print(f"   Text: {info.custom_text}")
            print("\n/info Icarus command should now work in Discord!")
        else:
            print("❌ Icarus info is DISABLED")
            print("   The /info command will show 'not enabled' error")
    else:
        print(f"❌ Failed to load Icarus info: {result.error}")

if __name__ == "__main__":
    test_info_command()