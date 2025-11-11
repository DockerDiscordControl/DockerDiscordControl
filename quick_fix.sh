#!/bin/bash
# Quick fix - Mount the code directory

echo "⚡ Quick Fix: Mount Code Directory"
echo "==================================="

cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Aktueller Container:"
echo "-----------------------"
docker ps | grep dockerdiscordcontrol

echo ""
echo "2. Container stoppen:"
echo "--------------------"
docker stop dockerdiscordcontrol

echo ""
echo "3. Container mit Code-Mount neu starten:"
echo "----------------------------------------"
docker rm dockerdiscordcontrol

# Get existing image
IMAGE=$(docker inspect dockerdiscordcontrol 2>/dev/null | grep -o '"Image": "[^"]*"' | cut -d'"' -f4 | head -1)
if [ -z "$IMAGE" ]; then
  IMAGE="maxyz/dockerdiscordcontrol:latest"
fi

echo "Using image: $IMAGE"

docker run -d \
  --name dockerdiscordcontrol \
  -p 8374:8374 \
  -v /mnt/user/appdata/dockerdiscordcontrol/config:/app/config \
  -v /mnt/user/appdata/dockerdiscordcontrol/logs:/app/logs \
  -v /mnt/user/appdata/dockerdiscordcontrol/cached_animations:/app/cached_animations \
  -v /mnt/user/appdata/dockerdiscordcontrol/services:/app/services \
  -v /mnt/user/appdata/dockerdiscordcontrol/app:/app/app \
  --restart unless-stopped \
  $IMAGE

echo ""
echo "4. Warte auf Start..."
sleep 10

echo ""
echo "5. Container läuft?"
docker ps | grep dockerdiscordcontrol

echo ""
echo "6. Web UI Test:"
curl -s http://localhost:8374 > /dev/null && echo "✅ Web UI läuft!" || echo "❌ Web UI nicht erreichbar"

echo ""
echo "✅ Code ist jetzt gemountet!"
echo ""
echo "TEST:"
echo "====="
echo "1. Gehe zu http://192.168.1.249:8374/config"
echo "2. Ändere Display Name zu 'TEST'"
echo "3. Speichern und prüfen mit:"
echo "   grep display_name config/containers/Icarus.json"