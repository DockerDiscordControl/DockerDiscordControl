#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAFE Mech Reset Script - Uses unified_donation_service instead of direct file writes

This script prevents race conditions by using the same service layer as Discord.
No more JSON corruption from concurrent writes!
"""

import sys
import os
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def safe_mech_reset():
    """Reset mech using the same service layer as Discord (no race conditions)."""
    print("🔄 SAFE Mech Reset - Using Service Layer")
    print("=" * 50)

    try:
        # Step 1: Get current status via MechDataStore
        print("📊 Current Status:")
        from services.mech.mech_data_store import get_mech_data_store, MechDataRequest
        data_store = get_mech_data_store()
        request = MechDataRequest(include_decimals=True)
        current_state = data_store.get_comprehensive_data(request)

        print(f"  • Level: {current_state.current_level} - {current_state.level_name}")
        print(f"  • Power: ${current_state.current_power:.2f}")
        print(f"  • Total Donated: ${current_state.total_donated:.2f}")
        print(f"  • Donations count: {len(current_state.total_donated) if hasattr(current_state, 'donations') else 'Unknown'}")

        # Step 2: SAFE reset via unified_donation_service
        print(f"\n🚀 Performing SAFE reset...")
        from services.donation.unified_donation_service import reset_all_donations

        # This uses the same service layer as Discord - NO RACE CONDITIONS!
        reset_result = reset_all_donations(source='admin_script')

        if reset_result.success:
            print("  ✅ Reset completed successfully via unified service")
            print(f"  ✅ Old Level: {reset_result.old_level} → New Level: {reset_result.new_level}")
            print(f"  ✅ Old Power: ${reset_result.old_power:.2f} → New Power: ${reset_result.new_power:.2f}")
            print("  ✅ Event emitted - Discord will auto-update")
            print("  ✅ MechDataStore cache cleared automatically")
        else:
            print(f"  ❌ Reset failed: {reset_result.error_message}")
            return False

        # Step 3: Verify the reset
        print(f"\n📊 Verification:")
        data_store.clear_cache()  # Ensure fresh data
        new_state = data_store.get_comprehensive_data(request)

        print(f"  • New Level: {new_state.current_level} - {new_state.level_name}")
        print(f"  • New Power: ${new_state.current_power:.2f}")
        print(f"  • New Total: ${new_state.total_donated:.2f}")

        if new_state.current_level == 1 and new_state.total_donated == 0:
            print(f"\n🎯 SUCCESS: Mech safely reset to Level 1!")
            print(f"   • Architecture: Single Point of Truth")
            print(f"   • Method: Unified Donation Service")
            print(f"   • Race Conditions: PREVENTED ✅")
            print(f"   • Discord Updates: AUTOMATIC ✅")
            return True
        else:
            print(f"\n⚠️  Reset may not have completed fully")
            return False

    except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
        print(f"\n❌ Error during safe reset: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🛡️  SAFE MECH RESET - Race Condition Protected")
    print("Uses unified_donation_service instead of direct file writes")
    print("This prevents JSON corruption from concurrent Discord operations")
    print()

    success = safe_mech_reset()

    if success:
        print(f"\n✅ Safe reset completed successfully!")
        print(f"💡 TIP: Always use this script instead of reset_mech.sh")
        print(f"📧 Discord will automatically update within seconds")
        sys.exit(0)
    else:
        print(f"\n❌ Safe reset failed - check logs above")
        sys.exit(1)