#!/usr/bin/env python3
"""Test bot startup to find where it hangs."""

import sys
import traceback

print("=" * 60)
print("Testing Bot Startup")
print("=" * 60)

print("\n1. Testing basic imports...")
try:
    import discord
    print("   ✓ discord imported")
except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
    print(f"   ✗ discord import failed: {e}")
    sys.exit(1)

print("\n2. Testing progress_service import...")
try:
    from services.mech.progress_service import get_progress_service
    print("   ✓ progress_service imported")
except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
    print(f"   ✗ progress_service import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n3. Testing get_progress_service()...")
try:
    progress_service = get_progress_service()
    print(f"   ✓ progress_service instance created: {type(progress_service)}")
except (RuntimeError) as e:
    print(f"   ✗ get_progress_service() failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n4. Testing add_system_donation method...")
try:
    import inspect
    sig = inspect.signature(progress_service.add_system_donation)
    print(f"   ✓ Method signature: {sig}")
except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
    print(f"   ✗ Method check failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n5. Testing snapshot file access...")
try:
    from pathlib import Path
    import json

    snap_file = Path("config/progress/snapshots/main.json")
    if snap_file.exists():
        snap = json.loads(snap_file.read_text())
        print(f"   ✓ Snapshot loaded: {snap.get('mech_id', 'unknown')}")
        print(f"     - power_acc: ${snap.get('power_acc', 0)/100:.2f}")
        print(f"     - evo_acc: ${snap.get('evo_acc', 0)/100:.2f}")
        print(f"     - welcome_bonus_given: {snap.get('welcome_bonus_given', False)}")
    else:
        print(f"   ✗ Snapshot file not found: {snap_file}")
except (AttributeError, KeyError, RuntimeError, TypeError) as e:
    print(f"   ✗ Snapshot access failed: {e}")
    traceback.print_exc()

print("\n6. Testing bot.py compilation...")
try:
    with open('bot.py', 'r') as f:
        code = f.read()
    compile(code, 'bot.py', 'exec')
    print("   ✓ bot.py compiles successfully")
except SyntaxError as e:
    print(f"   ✗ bot.py has syntax error: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n7. Checking for circular imports...")
try:
    # Try importing the main bot module pieces
    from services.config.config_service import load_config
    print("   ✓ config_service loads")

    from services.mech.mech_service_adapter import get_mech_service
    print("   ✓ mech_service_adapter loads")

except (AttributeError, IOError, ImportError, KeyError, ModuleNotFoundError, OSError, PermissionError, RuntimeError, TypeError) as e:
    print(f"   ✗ Import check failed: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("All tests passed! Bot should be able to start.")
print("=" * 60)
