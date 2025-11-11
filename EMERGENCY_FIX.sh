#!/bin/bash

echo "============================================================"
echo "EMERGENCY FIX: Force Update Container Code"
echo "Container is using OLD code from Docker image!"
echo "============================================================"
echo

# Step 1: Verify the mount
echo "[1/6] Checking if volume is mounted correctly..."
docker exec dockerdiscordcontrol ls -la /app/services/mech/mech_data_store.py

# Step 2: Force copy the correct file into container
echo "[2/6] Force copying correct mech_data_store.py into container..."
docker cp services/mech/mech_data_store.py dockerdiscordcontrol:/app/services/mech/mech_data_store.py

# Step 3: Verify the file was updated
echo "[3/6] Verifying file contains float types..."
docker exec dockerdiscordcontrol grep "mech_progress_current.*float" /app/services/mech/mech_data_store.py

# Step 4: Clear ALL Python caches
echo "[4/6] Clearing ALL Python caches aggressively..."
docker exec dockerdiscordcontrol sh -c 'find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /app -name "*.pyc" -delete 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /app -name "*.pyo" -delete 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'rm -rf /tmp/*.pyc /tmp/__pycache__ 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /usr -name "*.pyc" | grep -E "services/mech" | xargs rm -f 2>/dev/null || true'

# Step 5: Restart the Discord bot process
echo "[5/6] Restarting Discord bot..."
docker restart dockerdiscordcontrol

echo "[6/6] Waiting for bot to start (30 seconds)..."
sleep 30

# Test the fix
echo
echo "============================================================"
echo "Testing the fix..."
docker exec dockerdiscordcontrol python3 -c "
from services.mech.mech_data_store import BarsCompat
b = BarsCompat(mech_progress_current=4.5, mech_progress_max=15.0)
print(f'Test: {b.mech_progress_current}/{b.mech_progress_max} = {(b.mech_progress_current/b.mech_progress_max)*100:.1f}%')
print(f'Types: current={type(b.mech_progress_current).__name__}, max={type(b.mech_progress_max).__name__}')

from services.mech.mech_status_cache_service import get_mech_status_cache_service, MechStatusCacheRequest
cache = get_mech_status_cache_service()
result = cache.get_cached_status(MechStatusCacheRequest(include_decimals=True, force_refresh=True))
if result.success:
    c = result.bars.mech_progress_current
    m = result.bars.mech_progress_max
    print(f'Actual: {c}/{m} = {(c/m)*100:.1f}%')
"

echo
echo "============================================================"
echo "If this shows 30%, Discord should now show 30% too!"
echo "If still 100%, you need to REBUILD the Docker image:"
echo
echo "docker stop dockerdiscordcontrol"
echo "docker rm dockerdiscordcontrol"
echo "./rebuild.sh"
echo "============================================================"