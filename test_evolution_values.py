#!/usr/bin/env python3
"""Test what evolution values Discord receives"""

from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest

cache = get_mech_status_cache_service()
result = cache.get_cached_status(MechStatusCacheRequest(include_decimals=True, force_refresh=True))

print("=" * 60)
print("EVOLUTION VALUES TEST")
print("=" * 60)
print(f"mech_progress_current: {result.bars.mech_progress_current}")
print(f"mech_progress_max: {result.bars.mech_progress_max}")
print(f"Type current: {type(result.bars.mech_progress_current).__name__}")
print(f"Type max: {type(result.bars.mech_progress_max).__name__}")
print()
if result.bars.mech_progress_max > 0:
    pct = (result.bars.mech_progress_current / result.bars.mech_progress_max) * 100
    print(f"Calculated percentage: {pct:.1f}%")
    print()
    if pct > 99:
        print("❌ PROBLEM: Shows 100%!")
    else:
        print("✓ OK: Shows correct percentage")
else:
    print("ERROR: max is 0")
print("=" * 60)
