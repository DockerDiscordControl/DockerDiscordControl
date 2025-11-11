#!/bin/bash

echo "=== Fixing 100% Evolution Display Issue ==="
echo

# 1. Pull latest code
echo "1. Pulling latest code..."
git pull

# 2. Clear Python cache
echo "2. Clearing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
find . -name "*.pyo" -delete 2>/dev/null

# 3. Clear container's Python cache
echo "3. Clearing container Python cache..."
docker exec dockerdiscordcontrol find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
docker exec dockerdiscordcontrol find /app -name "*.pyc" -delete 2>/dev/null || true

# 4. Restart container
echo "4. Restarting container..."
docker restart dockerdiscordcontrol

echo
echo "=== Waiting for container to start..."
sleep 10

# 5. Force a cache refresh by triggering the bot
echo "5. Container restarted. The bot should now show correct evolution %"
echo

echo "=== Done! ==="
echo "Discord should now show 30% evolution instead of 100%"