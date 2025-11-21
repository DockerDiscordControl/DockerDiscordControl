#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regenerate Mech Display Cache - Manual regeneration script

Run this script if you need to regenerate all mech display images:
- After updating mech evolution PNG files
- After cache corruption
- After major system changes

Usage:
    python3 scripts/regenerate_mech_display_cache.py

Or from root directory:
    DDC_WEB_PORT=5001 python3 scripts/regenerate_mech_display_cache.py
"""

import sys
import os
from pathlib import Path
import discord

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def main():
    print('🎨 MECH DISPLAY CACHE REGENERATION')
    print('=' * 50)

    try:
        from services.mech.mech_display_cache_service import get_mech_display_cache_service, MechDisplayCacheRequest

        display_cache_service = get_mech_display_cache_service()

        # Force regenerate ALL images (shadow + unlocked)
        print('Regenerating ALL mech display images...')
        print('• Shadow silhouettes for all levels (1-11)')
        print('• Unlocked display animations for all levels')
        print()

        request = MechDisplayCacheRequest(force_regenerate=True)
        result = display_cache_service.pre_render_all_displays(request)

        if result.success:
            print(f'✅ SUCCESS: {result.message}')
            print(f'📊 Processed {result.levels_processed} evolution levels')
            print()
            print('🚀 Discord interactions will now load instantly!')
            print('🎯 No bot restart required.')
        else:
            print(f'❌ ERROR: {result.message}')
            return 1

    except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
        print(f'❌ CRITICAL ERROR: {e}')
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == '__main__':
    exit(main())
