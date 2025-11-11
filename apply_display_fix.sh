#!/bin/bash
# Apply display_name fix and restart container

echo "🔧 Applying display_name Fix for Port 8374"
echo "============================================"

cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Zeige aktuelle display_name in Icarus.json:"
echo "----------------------------------------------"
grep display_name config/containers/Icarus.json

echo ""
echo "2. Container stoppen:"
echo "--------------------"
docker stop dockerdiscordcontrol

echo ""
echo "3. Container starten:"
echo "--------------------"
docker start dockerdiscordcontrol

echo ""
echo "Warte 15 Sekunden für Container-Start..."
sleep 15

echo ""
echo "4. Prüfe ob Web UI erreichbar ist:"
echo "-----------------------------------"
curl -s http://localhost:8374 > /dev/null && echo "✅ Web UI ist erreichbar auf Port 8374" || echo "❌ Web UI nicht erreichbar"

echo ""
echo "5. Zeige Web UI Prozess im Container:"
echo "--------------------------------------"
docker exec dockerdiscordcontrol ps aux | grep web_ui | grep -v grep

echo ""
echo "✅ Container neu gestartet!"
echo ""
echo "JETZT BITTE TESTEN:"
echo "==================="
echo "1. Gehe zu http://192.168.1.249:8374/config"
echo "2. Ändere 'Display Name in Bot' von 'Icarus Server' zu 'Icarus TEST'"
echo "3. Klicke auf 'Save Configuration'"
echo "4. Führe dann dieses Kommando aus um zu prüfen:"
echo "   grep display_name config/containers/Icarus.json"
echo ""
echo "Die Änderung sollte jetzt gespeichert werden!"