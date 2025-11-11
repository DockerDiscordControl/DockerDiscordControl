#!/bin/bash
# Test script to diagnose display_name saving issue

echo "🔧 Test Script für Display Name Speicher-Problem"
echo "================================================"

# Für Unraid-Konsole anpassen
cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Zeige aktuelle display_name in Icarus.json:"
echo "-------------------------------------------"
grep display_name config/containers/Icarus.json

echo ""
echo "2. Starte Container neu für Code-Änderungen:"
echo "-------------------------------------------"
docker restart dockerdiscordcontrol

echo ""
echo "Warte 10 Sekunden für Container-Start..."
sleep 10

echo ""
echo "3. Tail Docker Logs (letzte 100 Zeilen mit DISPLAY_NAME_DEBUG):"
echo "-------------------------------------------"
docker logs dockerdiscordcontrol 2>&1 | tail -100 | grep -E "DISPLAY_NAME_DEBUG|FORM_DEBUG|SAVE_DEBUG"

echo ""
echo "4. Bitte jetzt im Browser:"
echo "-------------------------------------------"
echo "- Gehe zu http://deine-ip:5001/config"
echo "- Ändere den Display Name von 'Icarus Server' zu 'Icarus TEST'"
echo "- Klicke auf Speichern"
echo "- Drücke dann Enter hier..."
read -p "Drücke Enter nach dem Speichern..."

echo ""
echo "5. Zeige Logs nach dem Speichern:"
echo "-------------------------------------------"
docker logs dockerdiscordcontrol 2>&1 | tail -50 | grep -E "DISPLAY_NAME_DEBUG|FORM_DEBUG|SAVE_DEBUG"

echo ""
echo "6. Prüfe ob Änderung gespeichert wurde:"
echo "-------------------------------------------"
grep display_name config/containers/Icarus.json

echo ""
echo "7. Kompletter Container-Inhalt:"
echo "-------------------------------------------"
cat config/containers/Icarus.json

echo ""
echo "✅ Test abgeschlossen!"