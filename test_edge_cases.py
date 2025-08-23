#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Edge Case Testing for Mech System Integration
"""

import sys
import logging
import time
import json
from pathlib import Path
from threading import Thread
import copy

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.WARNING)  # Reduce noise

def test_edge_cases():
    """Comprehensive edge case testing"""
    print("🔍 COMPREHENSIVE EDGE CASE TESTING")
    print("=" * 50)
    
    try:
        from systems.mech_master import get_mech_master
        from utils.donation_manager import get_donation_manager
        
        mech = get_mech_master()
        donation_manager = get_donation_manager()
        
        # Store initial state
        initial_status = donation_manager.get_status()
        initial_fuel = initial_status.get('total_amount', 0)
        initial_total = initial_status.get('total_donations_received', 0)
        
        print(f"📊 Initial State: ${initial_fuel:.6f} fuel, ${initial_total:.2f} total")
        
        test_results = []
        
        # EDGE CASE 1: Zero and negative donations
        print("\n🧪 Test 1: Zero and Negative Donations")
        try:
            result = mech.add_donation(0.0, "Zero Test")
            assert not result['success'], "Zero donation should fail"
            print("✅ Zero donation correctly rejected")
            
            result = mech.add_donation(-5.0, "Negative Test")
            assert not result['success'], "Negative donation should fail"
            print("✅ Negative donation correctly rejected")
            test_results.append("Zero/Negative: PASS")
        except Exception as e:
            print(f"❌ Zero/Negative test failed: {e}")
            test_results.append("Zero/Negative: FAIL")
        
        # EDGE CASE 2: Very small donations (floating point precision)
        print("\n🧪 Test 2: Floating Point Precision")
        try:
            tiny_amount = 0.000001  # 1 millicent
            result = mech.add_donation(tiny_amount, "Tiny Test")
            assert result['success'], "Tiny donation should succeed"
            
            # Verify persistence
            updated_status = donation_manager.get_status()
            fuel_diff = updated_status.get('total_amount', 0) - initial_fuel
            assert abs(fuel_diff - tiny_amount) < 1e-10, f"Fuel difference mismatch: {fuel_diff} vs {tiny_amount}"
            print(f"✅ Tiny donation processed: ${tiny_amount:.6f}")
            test_results.append("Floating Point: PASS")
        except Exception as e:
            print(f"❌ Floating point test failed: {e}")
            test_results.append("Floating Point: FAIL")
        
        # EDGE CASE 3: Very large donations
        print("\n🧪 Test 3: Large Donations")
        try:
            large_amount = 999999.99
            before_fuel = donation_manager.get_status().get('total_amount', 0)
            result = mech.add_donation(large_amount, "Large Test")
            assert result['success'], "Large donation should succeed"
            
            after_fuel = donation_manager.get_status().get('total_amount', 0)
            expected = before_fuel + large_amount
            assert abs(after_fuel - expected) < 0.01, f"Large donation calculation error"
            print(f"✅ Large donation processed: ${large_amount:.2f}")
            test_results.append("Large Donations: PASS")
        except Exception as e:
            print(f"❌ Large donation test failed: {e}")
            test_results.append("Large Donations: FAIL")
        
        # EDGE CASE 4: Special characters in donor names
        print("\n🧪 Test 4: Special Characters in Names")
        try:
            special_names = [
                "Test User 😀",
                "Spëçïäl Chãracters",
                "Unicode: 中文 العربية",
                "Symbols: @#$%^&*()",
                "",  # Empty name
                " " * 50,  # Long spaces
                "A" * 200  # Very long name
            ]
            
            for name in special_names:
                result = mech.add_donation(0.01, name)
                assert result['success'], f"Special name failed: {name}"
            print(f"✅ All {len(special_names)} special names processed")
            test_results.append("Special Names: PASS")
        except Exception as e:
            print(f"❌ Special names test failed: {e}")
            test_results.append("Special Names: FAIL")
        
        # EDGE CASE 5: Fuel consumption edge cases
        print("\n🧪 Test 5: Fuel Consumption Edge Cases")
        try:
            current_fuel = mech.fuel_system.current_fuel
            
            # Try to consume more than available
            overconsume_result = mech.fuel_system.consume_fuel(current_fuel + 1000, "Overconsume Test")
            assert not overconsume_result, "Overconsumption should fail"
            
            # Consume exact amount
            exact_result = mech.fuel_system.consume_fuel(current_fuel, "Exact Test")
            assert exact_result, "Exact consumption should succeed"
            assert mech.fuel_system.current_fuel == 0, "Fuel should be zero after exact consumption"
            
            # Try to consume when fuel is zero
            zero_result = mech.fuel_system.consume_fuel(0.01, "Zero Fuel Test")
            assert not zero_result, "Consumption with zero fuel should fail"
            
            print("✅ Fuel consumption edge cases handled correctly")
            test_results.append("Fuel Consumption: PASS")
        except Exception as e:
            print(f"❌ Fuel consumption test failed: {e}")
            test_results.append("Fuel Consumption: FAIL")
        
        # EDGE CASE 6: Concurrent access simulation
        print("\n🧪 Test 6: Concurrent Access Simulation")
        try:
            # Add some fuel back first
            mech.add_donation(10.0, "Concurrency Setup")
            
            errors = []
            
            def worker(worker_id):
                try:
                    for i in range(5):
                        # Random donations and consumptions
                        if i % 2 == 0:
                            mech.add_donation(0.1, f"Worker{worker_id}-{i}")
                        else:
                            mech.fuel_system.consume_fuel(0.05, f"Worker{worker_id}-{i}")
                        time.sleep(0.01)  # Small delay
                except Exception as e:
                    errors.append(f"Worker{worker_id}: {e}")
            
            # Start multiple threads
            threads = []
            for i in range(3):
                thread = Thread(target=worker, args=(i,))
                threads.append(thread)
                thread.start()
            
            # Wait for all threads
            for thread in threads:
                thread.join()
            
            if errors:
                print(f"❌ Concurrency errors: {errors}")
                test_results.append("Concurrency: FAIL")
            else:
                print("✅ Concurrent access handled without errors")
                test_results.append("Concurrency: PASS")
        except Exception as e:
            print(f"❌ Concurrency test failed: {e}")
            test_results.append("Concurrency: FAIL")
        
        # EDGE CASE 7: File system stress test
        print("\n🧪 Test 7: File System Stress Test")
        try:
            # Rapid succession of donations to stress file I/O
            start_time = time.time()
            for i in range(20):
                mech.add_donation(0.01, f"Stress{i}")
            end_time = time.time()
            
            duration = end_time - start_time
            print(f"✅ 20 rapid donations processed in {duration:.3f}s")
            test_results.append("File System Stress: PASS")
        except Exception as e:
            print(f"❌ File system stress test failed: {e}")
            test_results.append("File System Stress: FAIL")
        
        # EDGE CASE 8: Data corruption recovery
        print("\n🧪 Test 8: Data Corruption Recovery")
        try:
            # Backup current data
            data_backup = donation_manager.load_data()
            
            # Simulate corruption by writing invalid JSON
            with open(donation_manager.config_file, 'w') as f:
                f.write("{ invalid json }")
            
            # Try to access - should recover
            recovered_data = donation_manager.load_data()
            assert 'fuel_data' in recovered_data, "Data recovery failed"
            
            # Restore original data
            donation_manager.save_data(data_backup)
            print("✅ Data corruption recovery works")
            test_results.append("Data Corruption Recovery: PASS")
        except Exception as e:
            print(f"❌ Data corruption test failed: {e}")
            test_results.append("Data Corruption Recovery: FAIL")
        
        # EDGE CASE 9: Missing donation_manager
        print("\n🧪 Test 9: Missing donation_manager Fallback")
        try:
            # Create a new fuel system without connection
            from systems.fuel_system import FuelSystem
            standalone_fuel = FuelSystem()
            # Don't call connect_to_donation_manager()
            
            result = standalone_fuel.add_donation(1.0, "Standalone Test")
            assert result['success'], "Standalone fuel system should work"
            assert standalone_fuel.current_fuel == 1.0, "Standalone fuel tracking failed"
            print("✅ Standalone mode works without donation_manager")
            test_results.append("Standalone Mode: PASS")
        except Exception as e:
            print(f"❌ Standalone mode test failed: {e}")
            test_results.append("Standalone Mode: FAIL")
        
        # EDGE CASE 10: Evolution level boundaries
        print("\n🧪 Test 10: Evolution Level Boundaries")
        try:
            # Test evolution at boundaries
            from utils.speed_levels import get_combined_mech_status
            
            boundary_tests = [0, 0.01, 19.99, 20, 20.01, 99.99, 100, 7499.99, 7500, 10000]
            
            for amount in boundary_tests:
                status = get_combined_mech_status(amount, amount)
                assert 'evolution' in status, f"Evolution status missing for ${amount}"
                assert 'speed' in status, f"Speed status missing for ${amount}"
                
            print(f"✅ All {len(boundary_tests)} evolution boundaries tested")
            test_results.append("Evolution Boundaries: PASS")
        except Exception as e:
            print(f"❌ Evolution boundaries test failed: {e}")
            test_results.append("Evolution Boundaries: FAIL")
        
        # SUMMARY
        print("\n" + "=" * 50)
        print("📋 TEST SUMMARY")
        print("=" * 50)
        
        passed = sum(1 for result in test_results if "PASS" in result)
        total = len(test_results)
        
        for result in test_results:
            status_icon = "✅" if "PASS" in result else "❌"
            print(f"{status_icon} {result}")
        
        print(f"\n🎯 OVERALL: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        
        if passed == total:
            print("🎉 ALL EDGE CASES PASSED - SYSTEM IS ROBUST!")
        else:
            print("⚠️ Some edge cases failed - review needed")
        
        # Final state check
        final_status = donation_manager.get_status()
        final_fuel = final_status.get('total_amount', 0)
        final_total = final_status.get('total_donations_received', 0)
        print(f"\n📊 Final State: ${final_fuel:.6f} fuel, ${final_total:.2f} total")
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR in edge case testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_edge_cases()