#!/bin/bash
# Test the COMPLETE save chain

echo "Creating full save chain test..."

cat > /mnt/user/appdata/dockerdiscordcontrol/config/test_full_save.py << 'ENDPYTHON'
#!/usr/bin/env python3
import sys
import json
sys.path.insert(0, '/app')

print("🔍 Testing COMPLETE Save Chain")
print("=" * 60)

# Step 1: Parse form data
print("\n📝 STEP 1: Parsing form data...")
from services.config.config_service import _parse_servers_from_form

test_form_data = {
    'selected_servers': ['Icarus'],
    'display_name_Icarus': 'Icarus Server',
    'allow_status_Icarus': '1',
    'allow_start_Icarus': '1',
    'allow_stop_Icarus': '1',
    'allow_restart_Icarus': '1',
}

parsed_servers = _parse_servers_from_form(test_form_data)
print(f"   Parsed servers: {len(parsed_servers)}")
print(f"   Icarus actions: {parsed_servers[0].get('allowed_actions')}")

# Step 2: Call save_container_configs_from_web
print("\n💾 STEP 2: Calling save_container_configs_from_web...")
from app.utils.container_info_web_handler import save_container_configs_from_web

results = save_container_configs_from_web(parsed_servers)
print(f"   Save results: {results}")

# Step 3: Read the JSON file to verify
print("\n🔍 STEP 3: Reading saved JSON file...")
with open('/app/config/containers/Icarus.json', 'r') as f:
    saved_config = json.load(f)

print(f"   Saved allowed_actions: {saved_config.get('allowed_actions')}")

# Step 4: Compare
print("\n📊 COMPARISON:")
print(f"   Parsed:  {parsed_servers[0].get('allowed_actions')}")
print(f"   Saved:   {saved_config.get('allowed_actions')}")

if saved_config.get('allowed_actions') == parsed_servers[0].get('allowed_actions'):
    print("\n   ✅ SUCCESS: Data saved correctly!")
else:
    print("\n   ❌ PROBLEM: Data was corrupted during save!")
    print(f"   Missing: {set(parsed_servers[0].get('allowed_actions')) - set(saved_config.get('allowed_actions'))}")

print("\n" + "=" * 60)
ENDPYTHON

echo "Running test in Docker container..."
docker exec dockerdiscordcontrol python3 /app/config/test_full_save.py

echo ""
echo "Cleaning up..."
rm /mnt/user/appdata/dockerdiscordcontrol/config/test_full_save.py

echo "Test complete!"
