# SOLUTION: Discord Shows 100% Evolution Instead of 30%

## Problem
Discord bot shows 100% evolution after donations, but should show 30%.
- Expected: Level 2, Evolution 30% ($4.50 of $15.00)
- Actual: Level 2, Evolution 100%
- Web UI: Shows correctly after fixes

## Root Cause
The Docker container has **cached Python bytecode** (.pyc files) with the old `BarsCompat` dataclass definition using `int` types instead of `float` types. This causes decimal values to be truncated:
- Old (cached): `mech_progress_current: int` → 4.5 becomes 15 (or similar wrong value)
- New (fixed): `mech_progress_current: float` → 4.5 stays as 4.5

## Solution Steps

### Option A: Clear Python Cache (Quick Fix)
Run these commands **ON YOUR UNRAID SERVER** (via SSH or Terminal):

```bash
# 1. Clear all Python cache inside the container
docker exec dockerdiscordcontrol sh -c 'find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /app -name "*.pyc" -delete 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /app -name "*.pyo" -delete 2>/dev/null || true'

# 2. Restart the container to reload fresh code
docker restart dockerdiscordcontrol

# 3. Wait 20 seconds for bot to start
sleep 20

# 4. Check the logs to verify
docker logs --tail 50 dockerdiscordcontrol | grep "EVOLUTION DEBUG"
```

You should see in the logs:
```
EVOLUTION DEBUG - Calculation: (4.5/15.0)*100 = 30.00%
```

### Option B: Full Container Rebuild (Guaranteed Fix)
If Option A doesn't work, rebuild the container completely:

```bash
# 1. Stop and remove the container
docker stop dockerdiscordcontrol
docker rm dockerdiscordcontrol

# 2. Run your rebuild script
./rebuild.sh

# OR manually recreate:
# docker run -d --name dockerdiscordcontrol \
#   -v /path/to/code:/app \
#   -v /path/to/config:/config \
#   your-image-name
```

### Option C: Automated Fix Script
We've created `fix_container_evolution.sh` that you can run:

```bash
# On Unraid server:
cd /mnt/user/appdata/dockerdiscordcontrol
./fix_container_evolution.sh
```

## Verification
After fixing, verify in Discord:
1. Use your status command (e.g., `/ss` or `!status`)
2. Look for: `Mech Status Evolution: ███████████░░░░░░░░░░░░░░░░░░ 30.0%`
3. NOT: `Mech Status Evolution: ██████████████████████████████ 100.0%`

## Why This Happened
1. We fixed the code to use `float` types in `services/mech/mech_data_store.py`
2. The code was updated on the host via network share
3. The container volume mount picked up the new .py files
4. BUT: Python had already compiled and cached the old class definition as .pyc files
5. Python loads .pyc files preferentially, ignoring the updated .py files

## Prevention
To prevent this in the future after major type changes:
- Always clear Python cache when changing data types
- Consider adding to rebuild.sh: `docker exec dockerdiscordcontrol find /app -name "*.pyc" -delete`
- Use `importlib.reload()` for critical modules during development

## Debug Commands
If you need to debug further:

```bash
# Run debug script inside container
docker exec dockerdiscordcontrol python3 /app/debug_discord_evolution.py

# Check what Discord bot sees
docker exec dockerdiscordcontrol python3 -c "
from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
cache = get_mech_status_cache_service()
result = cache.get_cached_status(MechStatusCacheRequest(include_decimals=True, force_refresh=True))
print(f'Current: {result.bars.mech_progress_current}, Max: {result.bars.mech_progress_max}')
print(f'Percentage: {(result.bars.mech_progress_current/result.bars.mech_progress_max)*100:.1f}%')
"
```

## Status
- ✅ Fixed calculation logic in progress_service.py
- ✅ Fixed type conversion (int→float) in mech_data_store.py
- ✅ Fixed Web UI display
- ✅ Added debug logging
- ⚠️ Need to clear container Python cache for Discord bot to show correctly