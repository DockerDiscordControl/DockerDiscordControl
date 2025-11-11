#!/bin/bash
# Fix the display_name saving issue directly in the running container

echo "🔧 Fixing display_name saving directly in Docker Container"
echo "=========================================================="

cd /mnt/user/appdata/dockerdiscordcontrol

echo ""
echo "1. Prüfe aktuelle Code-Version im Container:"
echo "---------------------------------------------"
docker exec dockerdiscordcontrol grep -n "display_names = \[" /app/services/config/config_service.py | head -5

echo ""
echo "2. Patche config_service.py im Container:"
echo "-----------------------------------------"
docker exec dockerdiscordcontrol bash -c '
# Backup original
cp /app/services/config/config_service.py /app/services/config/config_service.py.backup

# Apply the fix using Python to ensure correct formatting
cat > /tmp/fix_display_name.py << EOF
import re

# Read the file
with open("/app/services/config/config_service.py", "r") as f:
    content = f.read()

# Find and replace the display_names list logic
# Replace the entire block from line 1421 to 1456
old_pattern = r"(\s+)# Handle different display_name formats\n\s+display_names = \[\].*?logger\.debug\(f\"\[FORM_DEBUG\] Parsed display_names for \{container_name\}: \{display_names\}\"\)"
new_code = """        # Handle different display_name formats - now as single string!
        display_name = container_name  # Default to container name

        # If it'\''s an array, take first element
        if isinstance(display_name_raw, list) and len(display_name_raw) > 0:
            display_name_raw = display_name_raw[0]

        if isinstance(display_name_raw, str):
            # Clean up any stringified list representations
            if display_name_raw.startswith('\''['\'') and display_name_raw.endswith('\'']'\''):
                # It'\''s a stringified list like "['\'Name1'\'', '\''Name2'\'']"
                try:
                    import ast
                    parsed_list = ast.literal_eval(display_name_raw)
                    if isinstance(parsed_list, list) and len(parsed_list) > 0:
                        # Take the first element
                        display_name = str(parsed_list[0])
                    else:
                        # Couldn'\''t parse, use raw value
                        display_name = display_name_raw.strip("[]'\''\\\"")
                except:
                    # Failed to parse, treat as regular string
                    display_name = display_name_raw.strip("[]'\''\\\"")
            else:
                # It'\''s a regular string, use as-is
                display_name = display_name_raw.strip()

        # Ensure we have a valid display name
        if not display_name:
            display_name = container_name

        logger.debug(f"[FORM_DEBUG] Parsed display_name for {container_name}: {display_name}")"""

# Apply the replacement
content = re.sub(old_pattern, new_code, content, flags=re.DOTALL)

# Also fix the server_config to use display_name instead of display_names
content = content.replace("'\''display_name'\'': display_names,", "'\''display_name'\'': display_name,")

# Write back
with open("/app/services/config/config_service.py", "w") as f:
    f.write(content)

print("✅ Fixed config_service.py")
EOF

python3 /tmp/fix_display_name.py
'

echo ""
echo "3. Patch container_info_web_handler.py für Debug-Logging:"
echo "----------------------------------------------------------"
docker exec dockerdiscordcontrol bash -c '
# Add debug logging to see what is being saved
sed -i "/display_name_raw = server.get/a\\            logger.info(f\"[DISPLAY_NAME_DEBUG] Container: {container_name}, Raw display_name from server: {repr(display_name_raw)}, Type: {type(display_name_raw)}\")" /app/app/utils/container_info_web_handler.py

sed -i "/container_config\['\''display_name'\''\] = display_name/a\\            logger.info(f\"[DISPLAY_NAME_DEBUG] Container: {container_name}, Final display_name being saved: {repr(display_name)}, Type: {type(display_name)}\")" /app/app/utils/container_info_web_handler.py

echo "✅ Added debug logging"
'

echo ""
echo "4. Restart gunicorn to reload code:"
echo "------------------------------------"
docker exec dockerdiscordcontrol bash -c '
# Kill gunicorn to force reload
pkill -HUP gunicorn || pkill gunicorn
sleep 2
# It should auto-restart
'

echo ""
echo "Warte 5 Sekunden für Gunicorn-Neustart..."
sleep 5

echo ""
echo "5. Prüfe ob Web UI noch erreichbar ist:"
echo "----------------------------------------"
curl -s http://localhost:8374 > /dev/null && echo "✅ Web UI läuft wieder" || echo "❌ Web UI nicht erreichbar"

echo ""
echo "6. Zeige Logs für Debug-Ausgaben:"
echo "---------------------------------"
docker logs dockerdiscordcontrol --tail 20

echo ""
echo "✅ Fixes angewendet!"
echo ""
echo "JETZT BITTE NOCHMAL TESTEN:"
echo "============================"
echo "1. Gehe zu http://192.168.1.249:8374/config"
echo "2. Ändere 'Display Name in Bot' von 'Icarus Server' zu 'Icarus TEST'"
echo "3. Klicke auf 'Save Configuration'"
echo ""
echo "Dann prüfe mit:"
echo "  grep display_name config/containers/Icarus.json"
echo ""
echo "Und zeige die Logs:"
echo "  docker logs dockerdiscordcontrol --tail 50 | grep DISPLAY_NAME"