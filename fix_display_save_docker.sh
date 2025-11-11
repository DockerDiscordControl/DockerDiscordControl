#!/bin/bash
# Fix display_name saving inside Docker container

echo "🔧 Fixing display_name saving in Docker Container"
echo "=================================================="

# Run fixes inside the Docker container
docker exec dockerdiscordcontrol bash -c '
cd /app

echo "1. Patching config_service.py to save display_name as string..."
# Backup original
cp services/config/config_service.py services/config/config_service.py.bak

# Apply fix using sed
sed -i "s/display_names = \[display_name_raw, display_name_raw\]/display_name = display_name_raw/" services/config/config_service.py
sed -i "s/display_names = \[container_name, container_name\]/display_name = container_name/" services/config/config_service.py
sed -i "s/display_names = \[display_names\[0\], display_names\[0\]\]/display_name = display_name/" services/config/config_service.py
sed -i "s/'\''display_name'\'': display_names,/'\''display_name'\'': display_name,/" services/config/config_service.py

echo "2. Checking if Web UI is running..."
ps aux | grep web_ui | grep -v grep

echo "3. Restarting Web UI process..."
pkill -f "web_ui" || true
sleep 2

# Start Web UI with correct port
DDC_WEB_PORT=8374 python3 -m app.web_ui &

echo "✅ Fixes applied inside container!"
'

echo ""
echo "✅ Container patched! Bitte teste jetzt:"
echo "1. Gehe zu http://192.168.1.249:8374/config"
echo "2. Ändere einen Display Name (z.B. 'Icarus Server' zu 'Icarus TEST')"
echo "3. Klicke auf 'Save Configuration'"
echo "4. Prüfe ob die Änderung gespeichert wurde"