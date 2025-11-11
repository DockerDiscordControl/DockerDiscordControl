#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

# Simulate form data with restart=1
test_form_data = {
    'selected_servers': ['Icarus'],
    'display_name_Icarus': 'Icarus Server',
    'allow_status_Icarus': '1',
    'allow_start_Icarus': '1',
    'allow_stop_Icarus': '1',
    'allow_restart_Icarus': '1',  # <- This should add 'restart'!
}

print("🔍 Testing Form Parser")
print("=" * 60)
print("\n📋 Input Form Data:")
for key, value in test_form_data.items():
    print(f"   {key}: {value}")

# Parse using the actual function
from services.config.config_service import _parse_servers_from_form

result = _parse_servers_from_form(test_form_data)

print("\n📊 Parsed Result:")
print(f"   Number of servers: {len(result)}")

if result:
    server = result[0]
    print(f"\n   Server: {server.get('container_name')}")
    print(f"   Display Name: {server.get('display_name')}")
    print(f"   Allowed Actions: {server.get('allowed_actions')}")

    if 'restart' in server.get('allowed_actions', []):
        print("\n   ✅ SUCCESS: 'restart' is in allowed_actions!")
    else:
        print("\n   ❌ PROBLEM: 'restart' is MISSING from allowed_actions!")
        print(f"   Expected: ['status', 'start', 'stop', 'restart']")
        print(f"   Got:      {server.get('allowed_actions')}")
else:
    print("   ❌ No servers parsed!")

print("\n" + "=" * 60)
