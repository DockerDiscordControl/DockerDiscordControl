#!/bin/bash
# Test container save functionality

echo "==================================="
echo "Container Save Test Script"
echo "==================================="
echo ""

# Navigate to DDC directory
cd /mnt/user/appdata/dockerdiscordcontrol || exit 1

echo "1. Pulling latest changes..."
git pull

echo ""
echo "2. Rebuilding container..."
./rebuild.sh

echo ""
echo "3. Waiting for services to start..."
sleep 10

echo ""
echo "4. Starting Web UI logs monitoring..."
echo "   (Logs will appear below when you save in the Web UI)"
echo ""
echo "==================================="
echo "INSTRUCTIONS:"
echo "1. Open Web UI: http://192.168.1.249:8374"
echo "2. Go to 'Container Selection & Bot Permissions'"
echo "3. Select some containers"
echo "4. Set display names and allowed actions"
echo "5. Click 'Save Configuration'"
echo "6. Watch the logs below for DEBUG messages"
echo "==================================="
echo ""

# Monitor logs with highlighting
tail -f logs/webui.log | grep --line-buffered -E "FORM_DEBUG|SAVE_DEBUG|PROCESS_DEBUG" | while IFS= read -r line
do
    if [[ $line == *"[SAVE_DEBUG]"* ]]; then
        echo -e "\033[0;32m$line\033[0m"  # Green for SAVE_DEBUG
    elif [[ $line == *"[FORM_DEBUG]"* ]]; then
        echo -e "\033[0;34m$line\033[0m"  # Blue for FORM_DEBUG
    elif [[ $line == *"[PROCESS_DEBUG]"* ]]; then
        echo -e "\033[0;35m$line\033[0m"  # Magenta for PROCESS_DEBUG
    else
        echo "$line"
    fi
done