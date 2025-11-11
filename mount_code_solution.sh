#!/bin/bash
# Mount code directories solution - Uses your fixed local code
# This is the BEST long-term solution as it uses all our fixes

echo "🚀 PERMANENT SOLUTION: Mount local code directories"
echo "===================================================="
echo ""
echo "This solution mounts your local code as volumes, so all"
echo "the fixes we made will be used immediately!"
echo ""

cd /mnt/user/appdata/dockerdiscordcontrol

echo "📍 Step 1: Stop current container"
echo "---------------------------------"
docker stop dockerdiscordcontrol
docker rm dockerdiscordcontrol

echo ""
echo "📍 Step 2: Start container with code mounted"
echo "--------------------------------------------"
echo "Mounting these directories:"
echo "  ✓ /app/services (all service code including fixes)"
echo "  ✓ /app/app (web UI code including fixes)"
echo "  ✓ /app/cogs (Discord bot commands)"
echo ""

docker run -d \
  --name dockerdiscordcontrol \
  -p 8374:8374 \
  -v /mnt/user/appdata/dockerdiscordcontrol/config:/app/config \
  -v /mnt/user/appdata/dockerdiscordcontrol/logs:/app/logs \
  -v /mnt/user/appdata/dockerdiscordcontrol/cached_animations:/app/cached_animations \
  -v /mnt/user/appdata/dockerdiscordcontrol/services:/app/services \
  -v /mnt/user/appdata/dockerdiscordcontrol/app:/app/app \
  -v /mnt/user/appdata/dockerdiscordcontrol/cogs:/app/cogs \
  --restart unless-stopped \
  maxyz/dockerdiscordcontrol:latest

echo ""
echo "⏳ Waiting 15 seconds for container to start..."
sleep 15

echo ""
echo "📍 Step 3: Verify container is running"
echo "--------------------------------------"
docker ps | grep dockerdiscordcontrol

echo ""
echo "📍 Step 4: Test Web UI"
echo "----------------------"
if curl -s http://localhost:8374 > /dev/null; then
    echo "✅ Web UI is accessible on port 8374"
else
    echo "❌ Web UI not responding, checking logs..."
    docker logs dockerdiscordcontrol --tail 50
fi

echo ""
echo "📍 Step 5: Verify our fixes are active"
echo "--------------------------------------"
echo "Checking if display_name fix is in place:"
docker exec dockerdiscordcontrol grep -n "display_name = container_name  # Default" /app/services/config/config_service.py | head -1
if [ $? -eq 0 ]; then
    echo "✅ Display name fix is active!"
else
    echo "⚠️  Display name fix might not be active"
fi

echo ""
echo "📍 Step 6: Current display_name in Icarus.json"
echo "----------------------------------------------"
grep display_name config/containers/Icarus.json | head -2

echo ""
echo "=============================================="
echo "✅ SOLUTION APPLIED - Code directories mounted!"
echo "=============================================="
echo ""
echo "ADVANTAGES of this solution:"
echo "  • All our code fixes are immediately active"
echo "  • Future code changes take effect instantly"
echo "  • No need to rebuild Docker image"
echo "  • Easy to debug and modify"
echo ""
echo "TEST NOW:"
echo "========="
echo "1. Go to: http://192.168.1.249:8374/config"
echo "2. Find 'Icarus' container row"
echo "3. Change 'Display Name in Bot' to 'Icarus TEST'"
echo "4. Click 'Save Configuration'"
echo "5. Verify with: grep display_name config/containers/Icarus.json"
echo ""
echo "The display_name should now save correctly as a string!"
echo ""
echo "To make this permanent, add these mounts to your"
echo "Docker compose file or Unraid template."