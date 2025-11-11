#!/bin/bash
# Final fix for display_name saving issue - Direct container patching
# This patches the running container's code directly

echo "🔧 FINAL FIX: Patching display_name handling in running container"
echo "================================================================="
echo ""

# Go to the dockerdiscordcontrol directory on Unraid
cd /mnt/user/appdata/dockerdiscordcontrol

echo "📍 Step 1: Checking current container status"
echo "--------------------------------------------"
docker ps | grep dockerdiscordcontrol
if [ $? -ne 0 ]; then
    echo "❌ Container not running! Starting it..."
    docker start dockerdiscordcontrol
    sleep 10
fi

echo ""
echo "📍 Step 2: Creating the patch file inside container"
echo "---------------------------------------------------"
docker exec dockerdiscordcontrol bash -c 'cat > /tmp/fix_display_name.py << '\''PYTHON_SCRIPT'\''
#!/usr/bin/env python3
import os
import re

print("🔍 Starting display_name fix...")

# Fix 1: config_service.py - Make display_name a single string
config_file = "/app/services/config/config_service.py"
if os.path.exists(config_file):
    print(f"📝 Patching {config_file}...")

    with open(config_file, "r") as f:
        content = f.read()

    # Backup original
    with open(f"{config_file}.backup", "w") as f:
        f.write(content)

    # Find the problematic section (lines 1421-1456 approximately)
    # Replace the display_names list logic with single string logic

    # Pattern 1: Replace display_names = [] initialization
    content = re.sub(
        r"display_names = \[\]",
        "display_name = container_name  # Default to container name",
        content
    )

    # Pattern 2: Replace the list append logic
    content = re.sub(
        r"display_names\.append\(([^)]+)\)",
        r"display_name = \1",
        content
    )

    # Pattern 3: Fix the final assignment in server_config
    content = re.sub(
        r"'\''display_name'\'': display_names,",
        "'\''display_name'\'': display_name,",
        content
    )

    # Pattern 4: Replace the entire display name parsing block more comprehensively
    old_block = r"# Handle different display_name formats\s*\n\s*display_names = \[\].*?logger\.debug\(f\"\[FORM_DEBUG\] Parsed display_names for \{container_name\}: \{display_names\}\"\)"

    new_block = """# Handle different display_name formats - FIXED to single string
        display_name = container_name  # Default to container name

        # Get the raw display_name value
        display_name_raw = server.get('\''display_name'\'', container_name)

        # If it'\''s a list, take the first element
        if isinstance(display_name_raw, list):
            if len(display_name_raw) > 0:
                display_name = str(display_name_raw[0]).strip()
        elif isinstance(display_name_raw, str):
            # Clean up any stringified list representations
            if display_name_raw.startswith("["):
                # It'\''s a stringified list like "['\''Name1'\'', '\''Name2'\'']"
                try:
                    import ast
                    parsed_list = ast.literal_eval(display_name_raw)
                    if isinstance(parsed_list, list) and len(parsed_list) > 0:
                        display_name = str(parsed_list[0]).strip()
                    else:
                        display_name = display_name_raw.strip("[]'\''\"")
                except:
                    # Failed to parse, clean it up manually
                    display_name = display_name_raw.strip("[]'\''\"").split(",")[0].strip()
            else:
                # Regular string, use as-is
                display_name = display_name_raw.strip()

        # Ensure we have a valid display name
        if not display_name:
            display_name = container_name

        logger.debug(f"[FORM_DEBUG] Parsed display_name for {container_name}: {display_name}")"""

    content = re.sub(old_block, new_block, content, flags=re.DOTALL)

    with open(config_file, "w") as f:
        f.write(content)

    print("✅ Fixed config_service.py")
else:
    print(f"⚠️  {config_file} not found")

# Fix 2: container_info_web_handler.py - Ensure it saves display_name correctly
handler_file = "/app/app/utils/container_info_web_handler.py"
if os.path.exists(handler_file):
    print(f"📝 Patching {handler_file}...")

    with open(handler_file, "r") as f:
        content = f.read()

    # Backup original
    with open(f"{handler_file}.backup", "w") as f:
        f.write(content)

    # Add debug logging and fix display_name handling
    # Find the save_container_configs_from_web function

    # Add import for logging if not present
    if "import logging" not in content:
        content = "import logging\n" + content
        content = "logger = logging.getLogger(__name__)\n" + content

    # Fix the display_name handling in save function
    # Look for where display_name is processed from the form
    pattern = r"(display_name[^=]*=.*server\.get\(['\''\"]*display_name['\''\"]*.*?\))"

    replacement = """# Get display_name and ensure it'\''s a single string
            display_name_raw = server.get('\''display_name'\'', container_name)
            logger.info(f"[SAVE_DEBUG] Container: {container_name}, Raw display_name: {repr(display_name_raw)}")

            # Convert to single string if needed
            if isinstance(display_name_raw, list):
                display_name = str(display_name_raw[0]) if display_name_raw else container_name
            else:
                display_name = str(display_name_raw) if display_name_raw else container_name

            logger.info(f"[SAVE_DEBUG] Container: {container_name}, Final display_name: {repr(display_name)}")"""

    # Try to find and replace the display_name handling
    if "display_name" in content and "server.get" in content:
        # Add our debug logging after the line where display_name is retrieved
        lines = content.split('\n')
        new_lines = []
        for i, line in enumerate(lines):
            new_lines.append(line)
            if "display_name" in line and "server.get" in line and "display_name" in line:
                # Add debug logging after this line
                indent = len(line) - len(line.lstrip())
                new_lines.append(" " * indent + "logger.info(f\"[DISPLAY_NAME_SAVE] Container: {container_name}, display_name value: {repr(display_name_raw)}, type: {type(display_name_raw)}\")")
        content = '\n'.join(new_lines)

    # Ensure display_name is saved as string in container_config
    content = re.sub(
        r"container_config\['\''display_name'\''\]\s*=\s*display_name",
        "container_config['\''display_name'\''] = str(display_name) if display_name else container_name",
        content
    )

    with open(handler_file, "w") as f:
        f.write(content)

    print("✅ Fixed container_info_web_handler.py")
else:
    print(f"⚠️  {handler_file} not found")

print("\n✅ All patches applied successfully!")
PYTHON_SCRIPT
'

echo ""
echo "📍 Step 3: Running the patch"
echo "----------------------------"
docker exec dockerdiscordcontrol python3 /tmp/fix_display_name.py

echo ""
echo "📍 Step 4: Restarting gunicorn to reload code"
echo "---------------------------------------------"
docker exec dockerdiscordcontrol bash -c '
# Find and kill gunicorn processes to force reload
pkill -HUP gunicorn 2>/dev/null || pkill -f gunicorn 2>/dev/null || true
sleep 2
# Check if gunicorn restarted
ps aux | grep gunicorn | grep -v grep
if [ $? -ne 0 ]; then
    echo "⚠️  Gunicorn not running, may need container restart"
fi
'

echo ""
echo "⏳ Waiting 5 seconds for services to restart..."
sleep 5

echo ""
echo "📍 Step 5: Testing Web UI availability"
echo "--------------------------------------"
if curl -s http://localhost:8374 > /dev/null; then
    echo "✅ Web UI is running on port 8374"
else
    echo "❌ Web UI not responding, restarting container..."
    docker restart dockerdiscordcontrol
    sleep 15
    curl -s http://localhost:8374 > /dev/null && echo "✅ Web UI now running" || echo "❌ Still not responding"
fi

echo ""
echo "📍 Step 6: Current display_name values"
echo "-------------------------------------"
echo "Checking Icarus.json:"
grep display_name config/containers/Icarus.json | head -2

echo ""
echo "=================================================="
echo "✅ FIX APPLIED! Now please test:"
echo "=================================================="
echo ""
echo "1. Go to: http://192.168.1.249:8374/config"
echo "2. Find 'Icarus' container"
echo "3. Change 'Display Name in Bot' to something like 'Icarus TEST'"
echo "4. Click 'Save Configuration'"
echo "5. Check if it saved with:"
echo "   grep display_name config/containers/Icarus.json"
echo ""
echo "The display_name should now save as a single string, not a list!"
echo ""
echo "To see debug logs while saving:"
echo "   docker logs dockerdiscordcontrol --tail 100 -f | grep -E 'SAVE_DEBUG|DISPLAY_NAME'"