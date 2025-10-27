#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Mech Reset Script for Docker Container

Simple script to reset the Mech system to Level 1 for testing.
Just run: python3 scripts/reset_mech.py
"""

import sys
import os
sys.path.append('/app')

from services.mech.mech_reset_service import get_mech_reset_service

def main():
    print("🔄 Resetting Mech system to Level 1...")
    print("=" * 50)

    # Get service
    reset_service = get_mech_reset_service()

    # Get current status
    print("📊 Current Status:")
    status = reset_service.get_current_status()
    for key, value in status.items():
        print(f"  • {key}: {value}")

    print("\n🚀 Performing reset...")

    # Perform reset
    result = reset_service.full_reset()

    # Show results
    print("\n" + "=" * 50)
    print(result.message)

    if result.details and 'operations' in result.details:
        print("\nOperations performed:")
        for operation in result.details['operations']:
            print(f"  ✅ {operation}")

    if result.success:
        print("\n🎯 Mech system successfully reset to Level 1!")
        print("   • Current Level: 1")
        print("   • Total Donations: $0")
        print("   • Next Level Cost: $40")
    else:
        print(f"\n❌ Reset failed: {result.message}")

if __name__ == "__main__":
    main()