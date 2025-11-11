#!/bin/bash
# Run this script ON THE UNRAID SERVER to fix Discord showing 100% evolution

echo "============================================================"
echo "AUTOMATED FIX: Discord 100% Evolution Issue"
echo "This script must be run ON THE UNRAID SERVER"
echo "============================================================"
echo

# Step 1: Clear Python cache inside container
echo "[1/5] Clearing Python cache inside container..."
docker exec dockerdiscordcontrol sh -c 'find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /app -name "*.pyc" -delete 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'find /app -name "*.pyo" -delete 2>/dev/null || true'
docker exec dockerdiscordcontrol sh -c 'rm -rf /tmp/*pyc* 2>/dev/null || true'
echo "   ✓ Python cache cleared"

# Step 2: Force reimport modules inside container
echo "[2/5] Running force reimport script inside container..."
docker exec dockerdiscordcontrol python3 /app/force_reimport.py

# Step 3: Restart the container
echo "[3/5] Restarting container..."
docker restart dockerdiscordcontrol

# Step 4: Wait for container to fully start
echo "[4/5] Waiting 20 seconds for container to start..."
sleep 20

# Step 5: Check the logs
echo "[5/5] Checking container logs for evolution percentage..."
echo
echo "Recent evolution-related logs:"
echo "-------------------------------"
docker logs --tail 200 dockerdiscordcontrol 2>&1 | grep -i "evolution\|mech.*progress\|bars.*debug" | tail -10

echo
echo "============================================================"
echo "FIX COMPLETE!"
echo "Discord should now show 30% evolution instead of 100%"
echo
echo "To verify in Discord:"
echo "1. Go to your Discord server"
echo "2. Use your status command (e.g., /ss or !status)"
echo "3. Check if evolution shows ~30% instead of 100%"
echo
echo "If still showing 100%, try Option B: Full container rebuild"
echo "Run: ./rebuild.sh"
echo "============================================================"