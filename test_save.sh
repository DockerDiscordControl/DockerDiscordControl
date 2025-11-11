#!/bin/bash
# Simple test to check if container config changes persist

echo "🔍 Testing Container Config Persistence"
echo "========================================"

# Check current state
echo ""
echo "📋 BEFORE CHANGE:"
cat config/containers/Icarus.json | grep -A 5 "allowed_actions"

# Make a change using Python inside container
docker exec dockerdiscordcontrol python3 -c "
import json
from pathlib import Path

config_file = Path('/app/config/containers/Icarus.json')
with open(config_file, 'r') as f:
    config = json.load(f)

actions = config.get('allowed_actions', [])
print('Current actions:', actions)

if 'restart' in actions:
    actions.remove('restart')
    print('Removed restart')
else:
    actions.append('restart')
    print('Added restart')

config['allowed_actions'] = actions

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print('Saved successfully!')
print('New actions:', actions)
"

echo ""
echo "📋 AFTER CHANGE:"
cat config/containers/Icarus.json | grep -A 5 "allowed_actions"

echo ""
echo "✅ Test complete!"
echo ""
echo "Now run './rebuild.sh' and check again:"
echo "cat config/containers/Icarus.json | grep -A 5 'allowed_actions'"
