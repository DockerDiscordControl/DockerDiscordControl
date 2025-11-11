#!/bin/bash
# Rebuild Docker container with fixed code

echo "🔨 Rebuilding Docker Container with display_name Fix"
echo "====================================================="

cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Container stoppen:"
echo "--------------------"
docker stop dockerdiscordcontrol

echo ""
echo "2. Docker Image neu bauen:"
echo "--------------------------"
docker build -t dockerdiscordcontrol:latest .

echo ""
echo "3. Alten Container entfernen:"
echo "-----------------------------"
docker rm dockerdiscordcontrol

echo ""
echo "4. Neuen Container starten:"
echo "---------------------------"
docker run -d \
  --name dockerdiscordcontrol \
  -p 8374:8374 \
  -v /mnt/user/appdata/dockerdiscordcontrol/config:/app/config \
  -v /mnt/user/appdata/dockerdiscordcontrol/logs:/app/logs \
  -v /mnt/user/appdata/dockerdiscordcontrol/cached_animations:/app/cached_animations \
  --restart unless-stopped \
  dockerdiscordcontrol:latest

echo ""
echo "5. Warte auf Container-Start..."
sleep 10

echo ""
echo "6. Container Status:"
echo "-------------------"
docker ps | grep dockerdiscordcontrol

echo ""
echo "7. Web UI Test:"
echo "---------------"
curl -s http://localhost:8374 > /dev/null && echo "✅ Web UI läuft!" || echo "❌ Web UI nicht erreichbar"

echo ""
echo "✅ Container neu gebaut!"
echo ""
echo "JETZT TESTEN:"
echo "============="
echo "1. Gehe zu http://192.168.1.249:8374/config"
echo "2. Ändere 'Display Name in Bot' zu 'Icarus TEST'"
echo "3. Speichern"
echo "4. Prüfe mit: grep display_name config/containers/Icarus.json"