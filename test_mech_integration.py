#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify Mech System integration with donation_manager
"""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO)

def test_mech_integration():
    """Test the Mech System integration with persistent storage"""
    print("🔧 Testing Mech System Integration...")
    
    try:
        # Test 1: Import systems
        print("\n1️⃣ Testing imports...")
        from systems.mech_master import get_mech_master
        from utils.donation_manager import get_donation_manager
        print("✅ Imports successful")
        
        # Test 2: Get instances
        print("\n2️⃣ Getting instances...")
        mech = get_mech_master()
        donation_manager = get_donation_manager()
        print("✅ Instances created")
        
        # Test 3: Check current state
        print("\n3️⃣ Checking current state...")
        status = donation_manager.get_status()
        current_fuel = status.get('total_amount', 0)
        total_donations = status.get('total_donations_received', 0)
        print(f"📊 Current donation_manager state:")
        print(f"   Current Fuel: ${current_fuel:.2f}")
        print(f"   Total Donations: ${total_donations:.2f}")
        
        fuel_status = mech.fuel_system.get_fuel_status()
        print(f"🛢️ Current fuel_system state:")
        print(f"   Current Fuel: ${fuel_status['current_fuel']:.2f}")
        print(f"   Total Donations: ${fuel_status['total_donations']:.2f}")
        
        # Test 4: Test synchronization
        print("\n4️⃣ Testing synchronization...")
        if mech.fuel_system._donation_manager:
            print("✅ FuelSystem is connected to donation_manager")
        else:
            print("❌ FuelSystem is NOT connected to donation_manager")
            
        # Test 5: Test small donation
        print("\n5️⃣ Testing small donation...")
        result = mech.add_donation(0.01, "Integration Test")
        if result['success']:
            print(f"✅ Donation processed: ${result['amount']:.2f}")
            print(f"   Fuel before: ${result['fuel_before']:.2f}")
            print(f"   Fuel after: ${result['fuel_after']:.2f}")
            
            # Check if it's in persistent storage
            updated_status = donation_manager.get_status()
            updated_fuel = updated_status.get('total_amount', 0)
            print(f"💾 Persistent storage updated to: ${updated_fuel:.2f}")
        else:
            print(f"❌ Donation failed: {result.get('error', 'Unknown error')}")
        
        print("\n🎉 Integration test completed!")
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_mech_integration()