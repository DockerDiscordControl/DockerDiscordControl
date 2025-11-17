#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Debug script to find why Discord shows 100% evolution
Run this INSIDE the container to see what values Discord gets
"""

print("=" * 60)
print("Discord Evolution Debug - What Discord Bot Sees")
print("=" * 60)

# Import exactly as Discord does
from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest

print("\n1. Getting cache service (like Discord does)...")
cache_service = get_mech_status_cache_service()

print("\n2. Making request with force_refresh=True...")
cache_request = MechStatusCacheRequest(include_decimals=True, force_refresh=True)
mech_cache_result = cache_service.get_cached_status(cache_request)

if not mech_cache_result.success:
    print(f"ERROR: {mech_cache_result.error_message}")
else:
    print(f"✓ Success! Got cached status")

    print("\n3. Values Discord receives:")
    print(f"   Level: {mech_cache_result.level}")
    print(f"   bars.mech_progress_current: {mech_cache_result.bars.mech_progress_current}")
    print(f"   bars.mech_progress_max: {mech_cache_result.bars.mech_progress_max}")

    # Simulate Discord calculation
    evolution_current = mech_cache_result.bars.mech_progress_current
    evolution_max = mech_cache_result.bars.mech_progress_max

    print(f"\n4. Discord variables:")
    print(f"   evolution_current = {evolution_current}")
    print(f"   evolution_max = {evolution_max}")

    if evolution_max > 0:
        next_percentage = min(100, max(0, (evolution_current / evolution_max) * 100))
        print(f"\n5. Discord calculation:")
        print(f"   next_percentage = min(100, max(0, ({evolution_current} / {evolution_max}) * 100))")
        print(f"   next_percentage = {next_percentage:.1f}%")
        print(f"\n   Discord will show: {next_percentage:.1f}%")
    else:
        print(f"\n5. evolution_max is 0, Discord shows 0%")

# Check the underlying data
print("\n" + "=" * 60)
print("6. Checking underlying progress_service...")
from services.mech.progress_service import get_progress_service
ps = get_progress_service()
state = ps.get_state()
print(f"   progress_service.evo_current: ${state.evo_current:.2f}")
print(f"   progress_service.evo_max: ${state.evo_max:.2f}")
print(f"   progress_service.evo_percent: {state.evo_percent}%")

# Check raw snapshot
print("\n7. Checking raw snapshot...")
import json
with open('config/progress/snapshots/main.json', 'r') as f:
    snap = json.load(f)
print(f"   evo_acc: {snap['evo_acc']} cents")
print(f"   goal_requirement: {snap['goal_requirement']} cents")

print("\n" + "=" * 60)
print("DIAGNOSIS:")
if evolution_current == evolution_max and evolution_max > 0:
    print(f"❌ PROBLEM: evolution_current ({evolution_current}) == evolution_max ({evolution_max})")
    print("   This causes 100% display!")
    print("   The cache service is returning WRONG values!")
elif next_percentage > 99:
    print(f"❌ PROBLEM: Percentage is {next_percentage:.1f}%")
else:
    print(f"✓ Values look correct ({next_percentage:.1f}%)")
print("=" * 60)