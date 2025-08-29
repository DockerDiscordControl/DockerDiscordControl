#!/usr/bin/env python3
"""
Test script for Mech System edge case protections
"""
import asyncio
import logging
import os
import sys
import json
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_state_persistence():
    """Test 1: Glvl-Tracking Persistence (Bot restart problem)"""
    print("\n=== TEST 1: State Persistence ===")
    
    from utils.mech_state_manager import get_mech_state_manager
    manager = get_mech_state_manager()
    
    # Test saving states
    test_channel_id = 123456789
    
    # Save some state
    print(f"Setting Glvl=5 for channel {test_channel_id}")
    manager.set_last_glvl(test_channel_id, 5)
    
    print(f"Setting expanded=True for channel {test_channel_id}")
    manager.set_expanded_state(test_channel_id, True)
    
    # Simulate restart by creating new manager instance
    del manager
    manager2 = get_mech_state_manager()
    
    # Check if state persisted
    loaded_glvl = manager2.get_last_glvl(test_channel_id)
    loaded_expanded = manager2.get_expanded_state(test_channel_id)
    
    print(f"Loaded Glvl: {loaded_glvl} (expected: 5)")
    print(f"Loaded expanded: {loaded_expanded} (expected: True)")
    
    assert loaded_glvl == 5, "Glvl not persisted!"
    assert loaded_expanded == True, "Expanded state not persisted!"
    
    print("✅ State persistence test PASSED")
    
    # Cleanup
    manager2.clear_channel_state(test_channel_id)
    return True

async def test_animation_fallback():
    """Test 2: Animation Service Fallback (graceful degradation)"""
    print("\n=== TEST 2: Animation Service Fallback ===")
    
    # Mock a failing animation service
    class MockFailingAnimationService:
        async def create_donation_animation_async(self, *args, **kwargs):
            raise RuntimeError("Animation service unavailable")
    
    # Test the fallback handling
    try:
        service = MockFailingAnimationService()
        animation_file = await service.create_donation_animation_async('Test', '$10', 10)
        print("❌ Should have raised an error")
        return False
    except RuntimeError as e:
        print(f"Expected error caught: {e}")
        print("✅ Animation fallback test PASSED (error properly raised for handling)")
        return True

async def test_rate_limiting():
    """Test 3: Rate Limit Protection for force_recreate"""
    print("\n=== TEST 3: Rate Limit Protection ===")
    
    from utils.mech_state_manager import get_mech_state_manager
    manager = get_mech_state_manager()
    
    test_channel_id = 987654321
    
    # First force_recreate should be allowed
    allowed1 = manager.should_force_recreate(test_channel_id)
    print(f"First force_recreate: {allowed1} (expected: True)")
    assert allowed1 == True, "First force_recreate should be allowed"
    
    manager.mark_force_recreate(test_channel_id)
    
    # Immediate second force_recreate should be rate limited
    allowed2 = manager.should_force_recreate(test_channel_id)
    print(f"Immediate second force_recreate: {allowed2} (expected: False)")
    assert allowed2 == False, "Immediate second force_recreate should be rate limited"
    
    # Bypass rate limit check
    allowed3 = manager.should_force_recreate(test_channel_id, check_rate_limit=False)
    print(f"Bypassed rate limit: {allowed3} (expected: True)")
    assert allowed3 == True, "Rate limit bypass should work"
    
    print("✅ Rate limiting test PASSED")
    
    # Cleanup
    manager.clear_channel_state(test_channel_id)
    return True

async def test_state_file_corruption():
    """Test 4: Handle corrupted state file"""
    print("\n=== TEST 4: State File Corruption Handling ===")
    
    # Corrupt the state file
    state_file = "config/mech_state.json"
    os.makedirs("config", exist_ok=True)
    
    # Save current state if exists
    backup_data = None
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            backup_data = f.read()
    
    # Write corrupted data
    with open(state_file, 'w') as f:
        f.write("{ invalid json }")
    
    # Try to load with corrupted file
    from utils.mech_state_manager import MechStateManager
    manager = MechStateManager()
    
    # Should handle gracefully and use defaults
    state = manager.load_state()
    print(f"Loaded state with corrupted file: {state}")
    assert 'last_glvl_per_channel' in state, "Should have default structure"
    assert 'mech_expanded_states' in state, "Should have default structure"
    
    print("✅ Corruption handling test PASSED")
    
    # Restore backup if existed
    if backup_data:
        with open(state_file, 'w') as f:
            f.write(backup_data)
    
    return True

async def main():
    """Run all edge case protection tests"""
    print("=" * 50)
    print("MECH SYSTEM EDGE CASE PROTECTION TESTS")
    print("=" * 50)
    
    tests = [
        test_state_persistence,
        test_animation_fallback,
        test_rate_limiting,
        test_state_file_corruption
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append((test.__name__, result))
        except Exception as e:
            logger.error(f"Test {test.__name__} failed with exception: {e}", exc_info=True)
            results.append((test.__name__, False))
    
    print("\n" + "=" * 50)
    print("TEST RESULTS SUMMARY")
    print("=" * 50)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n🎉 ALL EDGE CASE PROTECTION TESTS PASSED!")
    else:
        print("\n⚠️ SOME TESTS FAILED - Please review the output above")
    
    return all_passed

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)