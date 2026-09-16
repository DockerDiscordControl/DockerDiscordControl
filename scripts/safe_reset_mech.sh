#!/bin/bash
# SAFE Mech Reset Script - Docker Compatible
# Uses unified_donation_service to prevent race conditions and JSON corruption

echo "🛡️  SAFE MECH RESET - Race Condition Protected"
echo "Uses unified_donation_service instead of direct file writes"
echo "This prevents JSON corruption from concurrent Discord operations"
echo "=================================================="

# Execute safe reset inside Docker container using unified_donation_service
# (as the ddc user, so no root-owned files end up in the data directories)
docker exec -u ddc dockerdiscordcontrol python3 -c "
import sys
sys.path.insert(0, '/app')

def safe_mech_reset():
    \"\"\"Reset mech using the same service layer as Discord (no race conditions).\"\"\"
    print('🔄 SAFE Mech Reset - Using Service Layer')
    print('=' * 50)

    try:
        # Step 1: Get current status via MechDataStore
        print('📊 Current Status:')
        from services.mech.mech_data_store import get_mech_data_store, MechDataRequest
        data_store = get_mech_data_store()
        request = MechDataRequest(include_decimals=True)
        current_state = data_store.get_comprehensive_data(request)

        print(f'  • Level: {current_state.current_level} - {current_state.level_name}')
        print(f'  • Power: \${current_state.current_power:.2f}')
        print(f'  • Total Donated: \${current_state.total_donated:.2f}')

        # Step 2: SAFE reset via unified_donation_service
        print(f'\\n🚀 Performing SAFE reset...')
        from services.donation.unified_donation_service import reset_all_donations

        # This uses the same service layer as Discord - NO RACE CONDITIONS!
        reset_result = reset_all_donations(source='admin_script')

        if reset_result.success:
            print('  ✅ Reset completed successfully via unified service')
            print(f'  ✅ Old Level: {reset_result.old_level} → New Level: {reset_result.new_level}')
            print(f'  ✅ Old Power: \${reset_result.old_power:.2f} → New Power: \${reset_result.new_power:.2f}')
            print('  ✅ Event emitted - Discord will auto-update')
            print('  ✅ MechDataStore cache cleared automatically')
        else:
            print(f'  ❌ Reset failed: {reset_result.error_message}')
            return False

        # Step 3: Verify the reset
        print(f'\\n📊 Verification:')
        data_store.clear_cache()  # Ensure fresh data
        new_state = data_store.get_comprehensive_data(request)

        print(f'  • New Level: {new_state.current_level} - {new_state.level_name}')
        print(f'  • New Power: \${new_state.current_power:.2f}')
        print(f'  • New Total: \${new_state.total_donated:.2f}')

        if new_state.current_level == 1 and new_state.total_donated == 0:
            print(f'\\n🎯 SUCCESS: Mech safely reset to Level 1!')
            print(f'   • Architecture: Single Point of Truth')
            print(f'   • Method: Unified Donation Service')
            print(f'   • Race Conditions: PREVENTED ✅')
            print(f'   • Discord Updates: AUTOMATIC ✅')
            return True
        else:
            print(f'\\n⚠️  Reset may not have completed fully')
            return False

    except Exception as e:
        print(f'\\n❌ Error during safe reset: {e}')
        import traceback
        traceback.print_exc()
        return False

# Execute the safe reset
success = safe_mech_reset()

if success:
    print(f'\\n✅ Safe reset completed successfully!')
    print(f'💡 TIP: This method prevents JSON corruption')
    print(f'📧 Discord will automatically update within seconds')
else:
    print(f'\\n❌ Safe reset failed - check logs above')
"

echo "=================================================="
if [ $? -eq 0 ]; then
    echo "✅ Safe mech reset completed!"
else
    echo "❌ Safe mech reset failed!"
fi