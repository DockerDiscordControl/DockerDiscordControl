#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Volumes/appdata/dockerdiscordcontrol')

print("Testing imports...")

try:
    from services.mech.progress_service import add_system_donation
    print("✓ add_system_donation import successful")

    # Test the function signature
    import inspect
    sig = inspect.signature(add_system_donation)
    print(f"Function signature: {sig}")

except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
    print(f"✗ Import failed: {e}")
    import traceback
    traceback.print_exc()

# Also test if bot.py can be imported
print("\nTesting bot.py syntax...")
try:
    with open('/Volumes/appdata/dockerdiscordcontrol/bot.py', 'r') as f:
        code = f.read()
        compile(code, 'bot.py', 'exec')
    print("✓ bot.py syntax is valid")
except SyntaxError as e:
    print(f"✗ Syntax error in bot.py: {e}")
    import traceback
    traceback.print_exc()
