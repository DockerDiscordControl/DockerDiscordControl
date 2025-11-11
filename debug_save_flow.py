#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug script to trace the complete save flow and show what data gets saved
"""

import json
import sys
from pathlib import Path

def debug_save_flow():
    """Show what's currently in the container config files vs what should be there."""

    print("🔍 DEBUGGING SAVE FLOW")
    print("=" * 80)

    # 1. Show current Icarus config
    icarus_file = Path('config/containers/Icarus.json')
    print(f"\n📋 CURRENT Icarus.json:")
    print("-" * 80)
    with open(icarus_file, 'r') as f:
        icarus_config = json.load(f)
    print(json.dumps(icarus_config, indent=2))
    print(f"\n   allowed_actions: {icarus_config.get('allowed_actions')}")

    # 2. Simulate what the form SHOULD send (with restart REMOVED)
    print(f"\n\n📝 SIMULATED FORM DATA (Restart checkbox UNCHECKED):")
    print("-" * 80)
    simulated_form = {
        'selected_servers': ['Icarus'],  # Active checkbox is checked
        'display_name_Icarus': 'Icarus Server',
        'allow_status_Icarus': '1',      # Status checkbox checked
        'allow_start_Icarus': '1',       # Start checkbox checked
        'allow_stop_Icarus': '1',        # Stop checkbox checked
        # 'allow_restart_Icarus' is MISSING (checkbox unchecked!)
    }
    print(json.dumps(simulated_form, indent=2))

    # 3. Parse using the same logic as _parse_servers_from_form
    print(f"\n\n⚙️  PARSING LOGIC:")
    print("-" * 80)

    allowed_actions = []
    for action in ['status', 'start', 'stop', 'restart']:
        action_key = f'allow_{action}_Icarus'
        value = simulated_form.get(action_key)

        if value in ['1', 'on', True, 'true', 'True']:
            allowed_actions.append(action)
            print(f"   ✅ {action}: value={repr(value)} → ADDED")
        else:
            print(f"   ❌ {action}: value={repr(value)} → NOT added")

    print(f"\n   📊 Parsed allowed_actions: {allowed_actions}")
    print(f"   📊 Expected: ['status', 'start', 'stop']")
    print(f"   ✅ Match: {allowed_actions == ['status', 'start', 'stop']}")

    # 4. Check what would be saved
    print(f"\n\n💾 WHAT SHOULD BE SAVED:")
    print("-" * 80)
    new_config = icarus_config.copy()
    new_config['allowed_actions'] = allowed_actions
    print(json.dumps(new_config, indent=2))

    # 5. Comparison
    print(f"\n\n📊 COMPARISON:")
    print("-" * 80)
    print(f"   Current allowed_actions: {icarus_config.get('allowed_actions')}")
    print(f"   Should be after save:    {allowed_actions}")
    print(f"   Are they different?      {icarus_config.get('allowed_actions') != allowed_actions}")

    print("\n" + "=" * 80)
    print("✅ Analysis complete!")
    print("\nNEXT STEP: Check Web UI form HTML to verify checkbox names match!")

if __name__ == '__main__':
    import os
    os.chdir('/app' if os.path.exists('/app/config') else '.')
    debug_save_flow()
