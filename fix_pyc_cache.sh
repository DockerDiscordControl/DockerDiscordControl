#!/bin/bash

echo "=== Clearing Python Cache in Container ==="
echo

# Clear Python cache INSIDE the container
echo "Clearing .pyc files in container..."
docker exec dockerdiscordcontrol sh -c "find /app -name '*.pyc' -delete 2>/dev/null || true"
docker exec dockerdiscordcontrol sh -c "find /app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true"

# Also clear on host (mounted volume)
echo "Clearing .pyc files on host..."
find . -name "*.pyc" -delete 2>/dev/null
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Restart container to reload everything fresh
echo "Restarting container..."
docker restart dockerdiscordcontrol

echo
echo "Waiting for container to start..."
sleep 10

echo "=== Done! ==="
echo "Python cache cleared. Discord should now show correct 30% evolution."