#!/bin/bash
# Fix Config Persistence - Remove Legacy Files
# This script backs up and removes legacy config files that conflict with the new modular structure

set -e

echo "🔧 DockerDiscordControl - Config Persistence Fix"
echo "=================================================="
echo ""

# Create backup directory
BACKUP_DIR="config/legacy_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
echo "📦 Created backup directory: $BACKUP_DIR"
echo ""

# List of legacy files to remove
LEGACY_FILES=(
    "config/docker_config.json"
    "config/bot_config.json"
    "config/channels_config.json"
    "config/web_config.json"
)

echo "🔄 Moving legacy files to backup..."
for file in "${LEGACY_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ Backing up: $file"
        cp "$file" "$BACKUP_DIR/"
        rm "$file"
        echo "    → Removed from active config"
    else
        echo "  ⊘ Not found: $file (already removed or never existed)"
    fi
done

echo ""
echo "✅ Legacy files have been removed!"
echo ""
echo "📁 Backup location: $BACKUP_DIR"
echo ""
echo "ℹ️  The system will now use ONLY the modular config structure:"
echo "   - Containers: config/containers/*.json"
echo "   - Channels: config/channels/*.json (if exists)"
echo "   - Other settings: config/config.json, config/auth.json, etc."
echo ""
echo "🔄 Please restart the container for changes to take effect:"
echo "   docker restart dockerdiscordcontrol"
echo ""
echo "⚠️  If something goes wrong, you can restore from: $BACKUP_DIR"
