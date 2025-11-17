#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Force reimport of critical modules to fix cached bytecode issue.
Run this INSIDE the container after clearing .pyc files.
"""

import sys
import importlib

print("=" * 60)
print("FORCE REIMPORT: Reloading critical modules")
print("=" * 60)

# List of modules that need to be reloaded
modules_to_reload = [
    'services.mech.mech_data_store',
    'services.mech.progress_service',
    'services.mech.mech_status_cache_service',
    'services.mech.mech_service',
    'cogs.docker_control',
    'cogs.status_handlers'
]

print("\nStep 1: Removing modules from sys.modules...")
for module_name in modules_to_reload:
    if module_name in sys.modules:
        print(f"  - Removing {module_name}")
        del sys.modules[module_name]
    # Also remove any submodules
    to_remove = [key for key in sys.modules if key.startswith(module_name + '.')]
    for key in to_remove:
        print(f"  - Removing {key}")
        del sys.modules[key]

print("\nStep 2: Force reimport of modules...")
for module_name in modules_to_reload:
    try:
        print(f"  - Importing {module_name}")
        importlib.import_module(module_name)
    except (AttributeError, IOError, ImportError, KeyError, ModuleNotFoundError, OSError, PermissionError, RuntimeError, TypeError) as e:
        print(f"    WARNING: Could not import {module_name}: {e}")

print("\nStep 3: Verify BarsCompat has float types...")
from services.mech.mech_data_store import BarsCompat
import inspect

# Check the type annotations
sig = inspect.signature(BarsCompat)
print("\nBarsCompat field types:")
for field_name, field_info in BarsCompat.__dataclass_fields__.items():
    if 'progress' in field_name:
        print(f"  - {field_name}: {field_info.type}")

# Create a test instance
bars = BarsCompat()
print("\nTest instance values:")
print(f"  - mech_progress_current: {bars.mech_progress_current} (type: {type(bars.mech_progress_current).__name__})")
print(f"  - mech_progress_max: {bars.mech_progress_max} (type: {type(bars.mech_progress_max).__name__})")

# Test with actual values
bars_test = BarsCompat(mech_progress_current=4.5, mech_progress_max=15.0)
print("\nTest with decimal values:")
print(f"  - mech_progress_current: {bars_test.mech_progress_current} (type: {type(bars_test.mech_progress_current).__name__})")
print(f"  - mech_progress_max: {bars_test.mech_progress_max} (type: {type(bars_test.mech_progress_max).__name__})")

if type(bars_test.mech_progress_current).__name__ == 'float':
    print("\n✓ SUCCESS: BarsCompat is using float types!")
else:
    print("\n✗ FAILED: BarsCompat is still using int types!")
    print("  The .pyc cache is still active. Need more aggressive clearing.")

print("\nStep 4: Test the actual calculation...")
from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest

cache_service = get_mech_status_cache_service()
cache_request = MechStatusCacheRequest(include_decimals=True, force_refresh=True)
result = cache_service.get_cached_status(cache_request)

if result.success:
    current = result.bars.mech_progress_current
    max_val = result.bars.mech_progress_max
    print(f"\nCache service values:")
    print(f"  - mech_progress_current: {current} (type: {type(current).__name__})")
    print(f"  - mech_progress_max: {max_val} (type: {type(max_val).__name__})")

    if max_val > 0:
        percentage = (current / max_val) * 100
        print(f"  - Calculated percentage: {percentage:.1f}%")

        if abs(percentage - 30.0) < 0.1:
            print("\n✓ SUCCESS: Evolution shows 30% as expected!")
        else:
            print(f"\n✗ PROBLEM: Evolution shows {percentage:.1f}% instead of 30%")
else:
    print(f"\n✗ ERROR: {result.error_message}")

print("\n" + "=" * 60)
print("DONE - Check Discord to see if it now shows 30%")
print("=" * 60)