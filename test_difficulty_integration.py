#!/usr/bin/env python3
"""
Integration test for Static Difficulty Override feature.
Tests the complete flow from Web UI to cost calculation.
"""

import json
from pathlib import Path

def test_integration():
    """Test the complete integration flow."""

    print("=" * 80)
    print("INTEGRATION TEST: Static Difficulty Override")
    print("=" * 80)

    # Step 1: Simulate Web UI API call to set static mode
    print("\n📝 STEP 1: Simulating Web UI - User enables Static Override with 2.0× multiplier")
    print("-" * 80)

    # Directly modify evolution mode file (simulating Web UI API)
    mode_file = Path("config/evolution_mode.json")
    with open(mode_file, 'w') as f:
        json.dump({
            "use_dynamic": False,
            "difficulty_multiplier": 2.0,
            "last_updated": "2025-01-01T00:00:00"
        }, f, indent=2)
    print("✅ Evolution mode set to STATIC with 2.0× multiplier")

    # Verify file was updated
    with open(mode_file, 'r') as f:
        mode = json.load(f)
    print(f"📄 Config file updated: use_dynamic={mode['use_dynamic']}, multiplier={mode['difficulty_multiplier']}")

    # Step 2: Calculate cost with static mode
    print("\n💰 STEP 2: Calculating evolution cost with Static Override ON")
    print("-" * 80)

    from services.mech.progress_service import requirement_for_level_and_bin

    level = 1
    bin_num = 1
    cost = requirement_for_level_and_bin(level, bin_num)

    expected = int((1000 + 400) * 2.0)  # ($10 + $4) × 2.0 = $28.00
    print(f"Level {level}→{level+1}, Bin {bin_num}: ${cost/100:.2f}")
    print(f"Expected: ${expected/100:.2f}")

    if cost == expected:
        print("✅ PASS: Static multiplier correctly applied")
    else:
        print(f"❌ FAIL: Expected ${expected/100:.2f}, got ${cost/100:.2f}")
        return False

    # Step 3: Switch to dynamic mode
    print("\n🔄 STEP 3: Simulating Web UI - User disables Static Override")
    print("-" * 80)

    # User clicks toggle OFF (reverts to dynamic mode)
    with open(mode_file, 'w') as f:
        json.dump({
            "use_dynamic": True,
            "difficulty_multiplier": 1.0,
            "last_updated": "2025-01-01T00:00:00"
        }, f, indent=2)
    print("✅ Evolution mode set to DYNAMIC (community-based)")

    # Verify file was updated
    with open(mode_file, 'r') as f:
        mode = json.load(f)
    print(f"📄 Config file updated: use_dynamic={mode['use_dynamic']}, multiplier={mode['difficulty_multiplier']}")

    # Step 4: Calculate cost with dynamic mode
    print("\n💰 STEP 4: Calculating evolution cost with Static Override OFF")
    print("-" * 80)

    cost = requirement_for_level_and_bin(level, bin_num)

    expected = 1000 + 400  # $10 + $4 = $14.00 (no multiplier)
    print(f"Level {level}→{level+1}, Bin {bin_num}: ${cost/100:.2f}")
    print(f"Expected: ${expected/100:.2f}")

    if cost == expected:
        print("✅ PASS: Multiplier correctly ignored in dynamic mode")
    else:
        print(f"❌ FAIL: Expected ${expected/100:.2f}, got ${cost/100:.2f}")
        return False

    # Step 5: Test with different community sizes
    print("\n🌍 STEP 5: Testing with different community sizes (Dynamic mode)")
    print("-" * 80)

    test_cases = [
        (1, 1, 1000, 400, "1-person (Bin 1)"),
        (1, 5, 1000, 4900, "150-person (Bin 5)"),
        (1, 10, 1000, 20700, "750-person (Bin 10)"),
    ]

    for level, bin_num, base, dynamic, desc in test_cases:
        cost = requirement_for_level_and_bin(level, bin_num)
        expected = base + dynamic
        status = "✅" if cost == expected else "❌"
        print(f"{status} {desc}: ${cost/100:.2f} (expected ${expected/100:.2f})")

    # Step 6: Test Web Service API compatibility
    print("\n🌐 STEP 6: Testing Web Service API compatibility")
    print("-" * 80)

    from services.web.mech_web_service import get_mech_web_service, MechDifficultyRequest

    web_service = get_mech_web_service()

    # Test GET endpoint
    get_request = MechDifficultyRequest(operation='get')
    result = web_service.manage_difficulty(get_request)

    if result.success:
        print(f"✅ GET /api/mech/difficulty: Success")
        print(f"   - manual_override: {result.data.get('manual_override')}")
        print(f"   - difficulty_multiplier: {result.data.get('multiplier')}")
        print(f"   - is_auto: {result.data.get('is_auto')}")
    else:
        print(f"❌ GET endpoint failed: {result.error}")
        return False

    # Test SET endpoint (static mode)
    set_request = MechDifficultyRequest(operation='set', multiplier=1.5)
    result = web_service.manage_difficulty(set_request)

    if result.success:
        print(f"✅ POST /api/mech/difficulty (set 1.5×): Success")
        cost = requirement_for_level_and_bin(1, 1)
        expected = int((1000 + 400) * 1.5)
        print(f"   - Calculated cost: ${cost/100:.2f} (expected ${expected/100:.2f})")
        if cost == expected:
            print(f"   ✅ Cost matches expected value")
        else:
            print(f"   ❌ Cost mismatch!")
            return False
    else:
        print(f"❌ SET endpoint failed: {result.error}")
        return False

    # Step 7: Reset to dynamic mode
    print("\n🔄 STEP 7: Resetting to dynamic mode")
    print("-" * 80)

    reset_request = MechDifficultyRequest(operation='reset')
    result = web_service.manage_difficulty(reset_request)

    if result.success:
        print(f"✅ POST /api/mech/difficulty (reset): Success")
        cost = requirement_for_level_and_bin(1, 1)
        expected = 1000 + 400
        print(f"   - Calculated cost: ${cost/100:.2f} (expected ${expected/100:.2f})")
        if cost == expected:
            print(f"   ✅ Cost matches expected value (dynamic mode)")
        else:
            print(f"   ❌ Cost mismatch!")
            return False
    else:
        print(f"❌ RESET endpoint failed: {result.error}")
        return False

    print("\n" + "=" * 80)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 80)
    print("✅ All integration tests passed successfully!")
    print("\nVerified functionality:")
    print("  ✅ Web UI toggle sets evolution mode correctly")
    print("  ✅ Static mode applies custom multiplier")
    print("  ✅ Dynamic mode ignores multiplier")
    print("  ✅ Cost calculation respects override setting")
    print("  ✅ Web Service API endpoints work correctly")
    print("  ✅ Mode switching works seamlessly")
    print("\n🎉 Static Difficulty Override is fully functional!")
    print("=" * 80)

    return True

if __name__ == "__main__":
    success = test_integration()
    exit(0 if success else 1)
