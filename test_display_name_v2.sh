#!/bin/bash
# Enhanced test script with better logging

echo "🔧 Enhanced Test für Display Name Problem"
echo "=========================================="

# Für Unraid-Konsole anpassen
cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Aktuelle display_name in Icarus.json:"
echo "-----------------------------------------"
grep display_name config/containers/Icarus.json

echo ""
echo "2. Starte Container mit erhöhtem Log-Level:"
echo "-----------------------------------------"
docker stop dockerdiscordcontrol
docker start dockerdiscordcontrol

echo ""
echo "Warte 10 Sekunden für Container-Start..."
sleep 10

echo ""
echo "3. Teste Web UI Erreichbarkeit:"
echo "-----------------------------------------"
curl -s http://localhost:5001 > /dev/null && echo "✅ Web UI ist erreichbar" || echo "❌ Web UI nicht erreichbar"

echo ""
echo "4. Zeige Container Logs (letzte 30 Zeilen):"
echo "-----------------------------------------"
docker logs dockerdiscordcontrol --tail 30

echo ""
echo "5. Bitte jetzt im Browser:"
echo "-----------------------------------------"
echo "➡️  Gehe zu http://deine-ip:5001/config"
echo "➡️  Ändere 'Display Name in Bot' von 'Icarus Server' zu 'Icarus TEST'"
echo "➡️  Klicke auf 'Save Configuration'"
echo ""
read -p "Drücke Enter NACHDEM du gespeichert hast..."

echo ""
echo "6. Zeige Logs nach dem Speichern (mit DISPLAY_NAME):"
echo "------------------------------------------------------"
docker logs dockerdiscordcontrol 2>&1 | tail -100 | grep -E "DISPLAY_NAME|save_config_api|FORM_DEBUG|SAVE_DEBUG|Configuration saved"

echo ""
echo "7. Zeige alle kürzlichen INFO Logs:"
echo "------------------------------------"
docker logs dockerdiscordcontrol 2>&1 | tail -50 | grep -E "INFO|ERROR|WARNING"

echo ""
echo "8. Prüfe ob Änderung in JSON gespeichert wurde:"
echo "------------------------------------------------"
echo "Display Name in Icarus.json:"
grep display_name config/containers/Icarus.json

echo ""
echo "9. Zeige komplette Icarus.json:"
echo "--------------------------------"
cat config/containers/Icarus.json | python3 -m json.tool 2>/dev/null || cat config/containers/Icarus.json

echo ""
echo "✅ Test abgeschlossen!"
echo ""
echo "Falls die Änderung NICHT gespeichert wurde, prüfe ob:"
echo "- Die Logs 'DISPLAY_NAME_SAVE_DEBUG' zeigen"
echo "- Die Logs 'save_config_api' zeigen"
echo "- Es Fehlermeldungen gibt"