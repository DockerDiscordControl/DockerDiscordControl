#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Test script to manually modify Icarus container config and verify save
"""

import json
import os
from pathlib import Path

def test_manual_save():
    """Test manual save to container config file."""

    container_file = Path('config/containers/Icarus.json')

    print("🔍 Testing Container Config Save")
    print("=" * 60)

    # Read current config
    with open(container_file, 'r') as f:
        config = json.load(f)

    print(f"\n📋 Current Icarus config:")
    print(f"   Display Name: {config.get('display_name')}")
    print(f"   Allowed Actions: {config.get('allowed_actions')}")
    print(f"   Active: {config.get('active')}")

    # Make a test change - remove 'restart' if present, add if not
    actions = config.get('allowed_actions', [])

    if 'restart' in actions:
        print(f"\n🔄 TEST: Removing 'restart' action...")
        actions.remove('restart')
        test_action = "REMOVED restart"
    else:
        print(f"\n🔄 TEST: Adding 'restart' action...")
        actions.append('restart')
        test_action = "ADDED restart"

    config['allowed_actions'] = actions

    # Try to save
    print(f"\n💾 Attempting to save...")
    try:
        with open(container_file, 'w') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"   ✅ Save successful!")
    except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
        print(f"   ❌ Save failed: {e}")
        return

    # Verify save
    print(f"\n🔍 Verifying save...")
    with open(container_file, 'r') as f:
        verify_config = json.load(f)

    print(f"   New Allowed Actions: {verify_config.get('allowed_actions')}")

    if verify_config.get('allowed_actions') == actions:
        print(f"   ✅ Verification successful! ({test_action})")
    else:
        print(f"   ❌ Verification failed!")
        print(f"      Expected: {actions}")
        print(f"      Got: {verify_config.get('allowed_actions')}")

    print(f"\n📊 File Info:")
    stat = container_file.stat()
    print(f"   Path: {container_file}")
    print(f"   Size: {stat.st_size} bytes")
    print(f"   Owner: {stat.st_uid}")
    print(f"   Permissions: {oct(stat.st_mode)[-3:]}")

    print("\n" + "=" * 60)
    print("✅ Test complete!")
    print("\nNow check if this change persists after './rebuild.sh'")

if __name__ == '__main__':
    os.chdir('/app')  # Ensure we're in the right directory inside container
    test_manual_save()
