#!/bin/bash
# ⚠️  DEPRECATED: This script causes race conditions and JSON corruption!
# ✅ USE INSTEAD: ./scripts/safe_reset_mech.py

echo "❌ DEPRECATED SCRIPT - DO NOT USE!"
echo "=================================================="
echo "⚠️  This script causes race conditions with Discord bot!"
echo "⚠️  It directly writes to JSON files while Discord is running!"
echo "⚠️  This corrupts the donation database!"
echo ""
echo "✅ USE THE SAFE VERSION INSTEAD:"
echo "   python3 ./scripts/safe_reset_mech.py"
echo ""
echo "❌ ABORTING to prevent data corruption..."
exit 1

# OLD UNSAFE CODE BELOW (commented out to prevent usage)
# echo "🔄 Resetting Mech system to Level 1..."
echo "=================================================="

# Execute reset inside Docker container
docker exec dockerdiscordcontrol python3 -c "
import json
from datetime import datetime

print('📊 Current Status:')
try:
    with open('/app/config/mech_donations.json', 'r') as f:
        donations = json.load(f)
    print(f'  • Donations: {len(donations.get(\"donations\", []))}')
except:
    print('  • Donations: 0')

try:
    with open('/app/config/achieved_levels.json', 'r') as f:
        levels = json.load(f)
    print(f'  • Current Level: {levels.get(\"current_level\", 1)}')
except:
    print('  • Current Level: 1')

print('\n🚀 Performing reset...')

# Reset donations
with open('/app/config/mech_donations.json', 'w') as f:
    json.dump({'donations': []}, f, indent=2)
print('  ✅ Donations cleared')

# Reset achieved levels
with open('/app/config/achieved_levels.json', 'w') as f:
    json.dump({
        'current_level': 1,
        'achieved_levels': {
            '1': {
                'level': 1,
                'cost_paid': 0,
                'achieved_at': datetime.now().isoformat(),
                'locked': True
            }
        },
        'last_updated': datetime.now().isoformat()
    }, f, indent=2)
print('  ✅ Achieved levels reset to Level 1')

# Reset mech state
try:
    with open('/app/config/mech_state.json', 'r') as f:
        state = json.load(f)
    for channel_id in state.get('last_glvl_per_channel', {}):
        state['last_glvl_per_channel'][channel_id] = 1
    for channel_id in state.get('mech_expanded_states', {}):
        state['mech_expanded_states'][channel_id] = False
    state['last_update'] = datetime.now().isoformat()
    with open('/app/config/mech_state.json', 'w') as f:
        json.dump(state, f, indent=2)
    print('  ✅ Mech state reset to Level 1')
except Exception as e:
    print(f'  ⚠️  Mech state: {e}')

# Reset evolution mode
try:
    with open('/app/config/evolution_mode.json', 'w') as f:
        json.dump({
            'use_dynamic': False,
            'difficulty_multiplier': 1.0,
            'last_updated': datetime.now().isoformat()
        }, f, indent=2)
    print('  ✅ Evolution mode reset')
except Exception as e:
    print(f'  ⚠️  Evolution mode: {e}')

print('\n🎯 Mech system successfully reset to Level 1!')
print('   • Current Level: 1')
print('   • Total Donations: \$0')
print('   • Next Level Cost: \$40')
print('\n✅ Reset complete! You can now start testing from Level 1.')
"

echo "=================================================="
echo "✅ Mech reset completed!"