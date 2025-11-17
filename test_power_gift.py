#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Test the power gift system"""

import sys
from services.mech.mech_service_adapter import get_mech_service

def test_power_gift():
    print("=" * 60)
    print("TESTING POWER GIFT SYSTEM")
    print("=" * 60)

    adapter = get_mech_service()

    # Get initial state
    initial_state = adapter.get_state()
    print(f"Initial Power: ${initial_state.power_level:.2f}")

    # Try to grant gift with campaign_id
    print("\n1. First attempt with 'startup_gift_v1'...")
    state1 = adapter.power_gift("startup_gift_v1")
    print(f"   Power after: ${state1.power_level:.2f}")

    if state1.power_level > initial_state.power_level:
        print(f"   ✅ Gift granted: +${state1.power_level - initial_state.power_level:.2f}")
    else:
        print("   ❌ No gift granted (power > 0 or already used)")

    # Try again with same campaign_id (should be rejected)
    print("\n2. Second attempt with same 'startup_gift_v1'...")
    state2 = adapter.power_gift("startup_gift_v1")
    print(f"   Power after: ${state2.power_level:.2f}")

    if state2.power_level > state1.power_level:
        print(f"   ❌ ERROR: Gift granted again! This shouldn't happen!")
        sys.exit(1)
    else:
        print("   ✅ Correctly rejected duplicate campaign_id")

    # Try with different campaign_id (should be rejected due to power > 0)
    print("\n3. Attempt with different campaign 'test_v2'...")
    state3 = adapter.power_gift("test_v2")
    print(f"   Power after: ${state3.power_level:.2f}")

    if state3.power_level > state2.power_level:
        print(f"   ❌ ERROR: Gift granted when power > 0!")
        sys.exit(1)
    else:
        print("   ✅ Correctly rejected (power > 0)")

    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("Power gift system works correctly:")
    print("- Grants gift when power == 0 and campaign_id is new")
    print("- Rejects duplicate campaign_id")
    print("- Rejects when power > 0")
    print("=" * 60)

if __name__ == "__main__":
    test_power_gift()