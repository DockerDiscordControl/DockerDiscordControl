#!/bin/bash

echo "============================================================"
echo "FORCE FIX: Discord 100% Evolution Display Issue"
echo "============================================================"
echo
echo "This script will aggressively clear ALL Python cache to fix the issue."
echo

# 1. Show current status
echo "1. Current snapshot values:"
echo "   Reading config/progress/snapshots/main.json..."
grep -E "(evo_acc|goal_requirement|level)" config/progress/snapshots/main.json | sed 's/^/   /'
echo

# 2. Clear ALL Python cache on host
echo "2. Clearing ALL Python cache on host..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
find . -name "*.pyo" -delete 2>/dev/null
echo "   ✓ Host cache cleared"

# 3. Clear Python cache INSIDE container (if we can SSH to Unraid)
echo
echo "3. To clear container cache, run these commands on your Unraid server:"
echo
echo "   # Clear all Python cache inside container"
echo "   docker exec dockerdiscordcontrol sh -c 'find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true'"
echo "   docker exec dockerdiscordcontrol sh -c 'find /app -name \"*.pyc\" -delete 2>/dev/null || true'"
echo "   docker exec dockerdiscordcontrol sh -c 'find /app -name \"*.pyo\" -delete 2>/dev/null || true'"
echo
echo "   # Force Python to drop all imported modules"
echo "   docker exec dockerdiscordcontrol sh -c 'rm -rf /tmp/*pyc* 2>/dev/null || true'"
echo
echo "   # Restart the container completely"
echo "   docker restart dockerdiscordcontrol"
echo
echo "   # Wait for bot to restart"
echo "   sleep 15"
echo
echo "   # Check container logs for evolution percentage"
echo "   docker logs --tail 50 dockerdiscordcontrol | grep -i evolution"
echo

# 4. Alternative: Full container rebuild
echo "4. If the above doesn't work, try a FULL REBUILD:"
echo
echo "   # Stop and remove container"
echo "   docker stop dockerdiscordcontrol"
echo "   docker rm dockerdiscordcontrol"
echo
echo "   # Rebuild container from scratch (run your rebuild script)"
echo "   ./rebuild.sh"
echo
echo "============================================================"
echo "Expected result: Discord should show 30% evolution, not 100%"
echo "============================================================"