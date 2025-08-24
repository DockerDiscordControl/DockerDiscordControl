#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug script to identify the mech evolution text issue in German translation
"""

import sys
import os

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_donation_service_get_status():
    """Test the donation service get_status method"""
    print("=" * 60)
    print("🔍 TESTING donation_service.get_status() DATA FLOW")
    print("=" * 60)
    
    try:
        from services.donation_service import get_donation_service
        donation_service = get_donation_service()
        
        # Get the status data exactly like the /ss command does
        status_data = donation_service.get_status()
        
        print("📊 Raw status_data from donation_service.get_status():")
        for key, value in status_data.items():
            print(f"  {key}: {value}")
        
        # Extract the specific values used in /ss command
        current_fuel = status_data.get('total_amount', 0)
        total_donations_received = status_data.get('total_donations_received', 0)
        
        print(f"\n🎯 Key Values Used in /ss Command:")
        print(f"  current_fuel (total_amount): {current_fuel}")
        print(f"  total_donations_received: {total_donations_received}")
        
        # Test the combined mech status function
        from utils.speed_levels import get_combined_mech_status
        combined_status = get_combined_mech_status(current_fuel, total_donations_received)
        
        evolution = combined_status['evolution']
        speed = combined_status['speed']
        
        print(f"\n🤖 Evolution Status:")
        print(f"  Level: {evolution['level']}")
        print(f"  Name: {evolution['name']}")
        print(f"  Color: {evolution['color']}")
        print(f"  Description: {evolution['description']}")
        
        print(f"\n⚡ Speed Status:")
        print(f"  Level: {speed['level']}")
        print(f"  Description: {speed['description']}")
        print(f"  Emoji: {speed['emoji']}")
        
        # Check if the issue is with evolution level being 1 despite donations
        if total_donations_received > 0:
            print(f"\n✅ GOOD: total_donations_received = ${total_donations_received:.2f} > 0")
            if evolution['level'] == 1:
                print(f"⚠️  WARNING: Evolution is still Level 1 despite ${total_donations_received:.2f} donations!")
                print(f"   Expected evolution level should be higher based on thresholds.")
            else:
                print(f"✅ GOOD: Evolution level {evolution['level']} matches donation amount")
        else:
            print(f"❌ ISSUE FOUND: total_donations_received = {total_donations_received}")
            print(f"   This would cause evolution to always be Level 1 - SCRAP MECH")
        
        # Check thresholds
        from utils.mech_evolutions import EVOLUTION_THRESHOLDS
        print(f"\n🎯 Evolution Threshold Analysis:")
        for level in sorted(EVOLUTION_THRESHOLDS.keys()):
            threshold = EVOLUTION_THRESHOLDS[level]
            if total_donations_received >= threshold:
                print(f"  Level {level}: ${threshold} ✅ (meets threshold)")
            else:
                print(f"  Level {level}: ${threshold} ❌ (needs ${threshold - total_donations_received:.2f} more)")
        
        return status_data, evolution, speed
        
    except Exception as e:
        print(f"❌ ERROR in donation service test: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def test_raw_donation_manager():
    """Test the raw donation manager to compare data"""
    print("\n" + "=" * 60)
    print("🔍 TESTING Raw donation_manager.get_status()")
    print("=" * 60)
    
    try:
        from utils.donation_manager import get_donation_manager
        donation_manager = get_donation_manager()
        
        # Get raw data from donation manager
        raw_status = donation_manager.get_status()
        
        print("📊 Raw donation_manager.get_status():")
        for key, value in raw_status.items():
            print(f"  {key}: {value}")
        
        return raw_status
        
    except Exception as e:
        print(f"❌ ERROR in donation manager test: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("🚀 MECH EVOLUTION DEBUG SCRIPT")
    print("Investigating why German translation shows missing evolution text\n")
    
    # Test 1: Check donation service data
    service_data, evolution, speed = test_donation_service_get_status()
    
    # Test 2: Check raw donation manager data  
    raw_data = test_raw_donation_manager()
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 ANALYSIS SUMMARY")
    print("=" * 60)
    
    if service_data and raw_data:
        service_total = service_data.get('total_donations_received', 0)
        raw_total = raw_data.get('total_donations_received', 0)
        
        print(f"Service total_donations_received: {service_total}")
        print(f"Raw manager total_donations_received: {raw_total}")
        
        if service_total == raw_total and raw_total > 0:
            if evolution and evolution['level'] == 1:
                print("\n🎯 ROOT CAUSE IDENTIFIED:")
                print("   Data flow is correct, but evolution calculation may be wrong")
                print("   OR there's an issue in the German translation rendering")
            else:
                print("\n✅ Data appears correct - check translation rendering")
        elif service_total == 0 or raw_total == 0:
            print("\n🎯 ROOT CAUSE IDENTIFIED:")
            print("   total_donations_received is 0, causing evolution to default to Level 1")
            print("   This would result in 'SCRAP MECH' with no name showing")
        else:
            print(f"\n⚠️  Data mismatch between service ({service_total}) and raw ({raw_total})")
    else:
        print("❌ Could not complete analysis due to errors")