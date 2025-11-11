#!/usr/bin/env python3
"""
Debug script to trace why Discord shows 100% evolution
"""

import sys
import json

print("=" * 60)
print("Debugging 100% Evolution Display Issue")
print("=" * 60)

# 1. Check raw snapshot
print("\n1. RAW SNAPSHOT VALUES:")
with open('config/progress/snapshots/main.json', 'r') as f:
    snap = json.load(f)
    print(f"   evo_acc: {snap['evo_acc']} cents")
    print(f"   goal_requirement: {snap['goal_requirement']} cents")
    print(f"   Ratio: {(snap['evo_acc'] / snap['goal_requirement'] * 100) if snap['goal_requirement'] > 0 else 0:.1f}%")

# 2. Check progress service
print("\n2. PROGRESS SERVICE VALUES:")
from services.mech.progress_service import get_progress_service
ps = get_progress_service()
state = ps.get_state()
print(f"   evo_current: ${state.evo_current:.2f}")
print(f"   evo_max: ${state.evo_max:.2f}")
print(f"   evo_percent: {state.evo_percent}%")

# 3. Check MechDataStore
print("\n3. MECH DATA STORE VALUES:")
from services.mech.mech_data_store import MechDataStore, MechDataRequest
store = MechDataStore()
# Direct call to internal method
prog_state = ps.get_state()
print(f"   prog_state.evo_current: {prog_state.evo_current}")
print(f"   prog_state.evo_max: {prog_state.evo_max}")

# Create BarsCompat as the code does
from services.mech.mech_data_store import BarsCompat
bars = BarsCompat(
    Power_current=prog_state.power_current,
    Power_max_for_level=prog_state.power_max,
    mech_progress_current=prog_state.evo_current,
    mech_progress_max=prog_state.evo_max
)
print(f"   bars.mech_progress_current: {bars.mech_progress_current}")
print(f"   bars.mech_progress_max: {bars.mech_progress_max}")
if bars.mech_progress_max > 0:
    calc_pct = (bars.mech_progress_current / bars.mech_progress_max * 100)
    print(f"   Calculated %: {calc_pct:.1f}%")

# 4. Check MechStatusCacheService
print("\n4. MECH STATUS CACHE SERVICE:")
from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
cache_service = get_mech_status_cache_service()
cache_request = MechStatusCacheRequest(include_decimals=True, force_refresh=True)
result = cache_service.get_cached_status(cache_request)
if result.success:
    print(f"   bars.mech_progress_current: {result.bars.mech_progress_current}")
    print(f"   bars.mech_progress_max: {result.bars.mech_progress_max}")
    if result.bars.mech_progress_max > 0:
        calc_pct = (result.bars.mech_progress_current / result.bars.mech_progress_max * 100)
        print(f"   Calculated %: {calc_pct:.1f}%")
else:
    print(f"   ERROR: {result.error_message}")

# 5. Simulate Discord calculation
print("\n5. DISCORD BOT CALCULATION SIMULATION:")
evolution_current = result.bars.mech_progress_current
evolution_max = result.bars.mech_progress_max
print(f"   evolution_current: {evolution_current}")
print(f"   evolution_max: {evolution_max}")
if evolution_max > 0:
    next_percentage = min(100, max(0, (evolution_current / evolution_max) * 100))
    print(f"   next_percentage: {next_percentage:.1f}%")
    print(f"   Discord would show: {next_percentage:.1f}%")

print("\n" + "=" * 60)
print("PROBLEM FOUND:")
if evolution_current == evolution_max and evolution_max > 0:
    print(f"   evolution_current ({evolution_current}) == evolution_max ({evolution_max})")
    print("   This causes 100% display!")
    print("   WRONG VALUES are being returned somewhere in the chain!")
elif calc_pct >= 99:
    print(f"   Percentage is {calc_pct:.1f}% - close to 100%")
else:
    print(f"   Values look correct ({calc_pct:.1f}%) - cache issue?")
print("=" * 60)