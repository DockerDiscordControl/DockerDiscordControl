#!/bin/bash
# Debug warum display_name nicht gespeichert wird

echo "🔍 DEBUG: Display Name Save Problem"
echo "===================================="

cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Check ob config/containers beschreibbar ist:"
echo "------------------------------------------------"
docker exec dockerdiscordcontrol ls -la config/containers/Icarus.json

echo ""
echo "2. Test direktes Schreiben im Container:"
echo "-----------------------------------------"
docker exec dockerdiscordcontrol bash -c '
echo "Test schreiben in Container..."
echo "{\"test\": \"write\"}" > /app/config/containers/test_write.json
if [ -f /app/config/containers/test_write.json ]; then
  echo "✅ Schreiben funktioniert!"
  cat /app/config/containers/test_write.json
  rm /app/config/containers/test_write.json
else
  echo "❌ Schreiben fehlgeschlagen!"
fi
'

echo ""
echo "3. Check ob Code gemountet oder im Image ist:"
echo "----------------------------------------------"
docker exec dockerdiscordcontrol bash -c '
echo "Prüfe ob /app/services/config/config_service.py existiert:"
ls -la /app/services/config/config_service.py

echo ""
echo "Prüfe display_names Code (sollte Liste sein wenn alt):"
grep -n "display_names = \[" /app/services/config/config_service.py | head -3
'

echo ""
echo "4. Check Docker Mounts:"
echo "------------------------"
docker inspect dockerdiscordcontrol | grep -A 20 Mounts

echo ""
echo "5. Rebuild.sh vorhanden?"
echo "-------------------------"
if [ -f rebuild.sh ]; then
  echo "✅ rebuild.sh existiert"
  ls -la rebuild.sh
  echo ""
  echo "Inhalt (erste 10 Zeilen):"
  head -10 rebuild.sh
else
  echo "❌ Kein rebuild.sh gefunden"
fi

echo ""
echo "6. Check Dockerfile für Build-Infos:"
echo "-------------------------------------"
if [ -f Dockerfile ]; then
  echo "Dockerfile gefunden:"
  grep -E "COPY|ADD|services|config_service" Dockerfile
else
  echo "Kein Dockerfile im Hauptverzeichnis"
fi

echo ""
echo "📝 ANALYSE:"
echo "-----------"
echo "Wenn die Dateien gemountet sind → rebuild.sh sollte helfen"
echo "Wenn der Code im Image ist → Container muss neu gebaut werden"
echo "Wenn Schreiben nicht funktioniert → Permissions Problem"