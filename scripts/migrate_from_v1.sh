#!/bin/bash
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - v1.1.x to v2.0 Migration Script              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script header
echo -e "${CYAN}"
echo "============================================================================"
echo "  DDC v1.1.x → v2.0 MIGRATION SCRIPT"
echo "  Automatic migration from legacy to modular configuration"
echo "============================================================================"
echo -e "${NC}"

# Function to log messages
log_info() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_step() {
    echo -e "${BLUE}🔄 $1${NC}"
}

# Check for existing v1.1.x config
log_step "Checking for v1.1.x configuration..."

V1_CONFIG=""
if [[ -f "config/config.json" ]]; then
    # Check if it's actually a v1.1.x config (has servers field)
    if grep -q '"servers"' config/config.json 2>/dev/null; then
        V1_CONFIG="config/config.json"
        log_info "Found v1.1.x config at config/config.json"
    fi
fi

if [[ -z "$V1_CONFIG" ]]; then
    log_warn "No v1.1.x configuration found!"
    echo ""
    echo "This script is for migrating from DDC v1.1.x to v2.0"
    echo "If you have a v1.1.x config in a different location, please copy it to:"
    echo "  config/config.json"
    echo ""
    echo "Then run this script again."
    exit 0
fi

# Show what will be migrated
log_step "Analyzing v1.1.x configuration..."

echo ""
echo -e "${CYAN}Configuration to be migrated:${NC}"
echo "============================="

# Count servers
SERVER_COUNT=$(grep -o '"docker_name"' "$V1_CONFIG" | wc -l)
echo "  📦 Servers/Containers: $SERVER_COUNT"

# Check for channels
if grep -q '"channel_permissions"' "$V1_CONFIG"; then
    echo "  📺 Channel permissions: Yes"
fi

# Check for web UI
if grep -q '"web_ui_password_hash"' "$V1_CONFIG"; then
    echo "  🔐 Web UI configuration: Yes"
fi

# Check for advanced settings
if grep -q '"advanced_settings"' "$V1_CONFIG"; then
    echo "  ⚙️  Advanced settings: Yes"
fi

echo ""

# Backup warning
echo -e "${YELLOW}⚠️  IMPORTANT:${NC}"
echo "This will migrate your v1.1.x configuration to the new v2.0 format."
echo "Your original config will be backed up automatically."
echo ""

read -p "Do you want to continue with the migration? (y/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warn "Migration cancelled by user"
    exit 0
fi

# Create backup
log_step "Creating backup of current configuration..."

BACKUP_DIR="config/backup_v1_migration_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup all existing config files
cp -r config/*.json "$BACKUP_DIR/" 2>/dev/null || true

log_info "Backup created in: $BACKUP_DIR"

# Run the migration through Python
log_step "Starting automatic migration..."

python3 << 'EOF'
import sys
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, '.')

try:
    # Import and run ConfigService - it will auto-migrate
    from services.config.config_service import get_config_service
    
    logger.info("🔄 Initializing ConfigService (will trigger auto-migration)...")
    
    # Clear any cached instance
    import services.config.config_service as cs
    cs._config_service_instance = None
    
    # Initialize - this triggers migration
    config_service = get_config_service()
    config = config_service.get_config()
    
    # Report results
    servers = config.get('servers', [])
    channels = config.get('channel_permissions', {})
    
    print("")
    print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
    print("")
    print(f"📊 Migration Results:")
    print(f"   - {len(servers)} servers/containers migrated")
    print(f"   - {len(channels)} channel configurations migrated")
    print(f"   - Language: {config.get('language', 'not set')}")
    print(f"   - Timezone: {config.get('timezone', 'not set')}")
    print(f"   - Advanced settings: {len(config.get('advanced_settings', {}))}")
    
    # Clean up old JSON files after successful migration
    print("")
    print("🧹 Cleaning up old configuration files...")
    legacy_files = ['bot_config.json', 'docker_config.json', 'web_config.json', 'channels_config.json', 'advanced_settings.json', 'heartbeat.json']
    removed_files = []
    
    for filename in legacy_files:
        file_path = Path(f'./config/{filename}')
        if file_path.exists():
            try:
                file_path.unlink()
                removed_files.append(filename)
            except Exception as e:
                print(f"   Warning: Could not remove {filename}: {e}")
    
    if removed_files:
        print(f"   ✅ Removed legacy files: {', '.join(removed_files)}")
    else:
        print("   No legacy files found to remove")
    
    # Check if modular structure was created
    config_dir = Path('./config')
    if (config_dir / 'channels').exists():
        print("")
        print("✅ Real modular structure created:")
        print(f"   - channels/ directory with {len(list((config_dir / 'channels').glob('*.json')))} files")
        
    if (config_dir / 'containers').exists():
        print(f"   - containers/ directory with {len(list((config_dir / 'containers').glob('*.json')))} files")
    
    sys.exit(0)
    
except Exception as e:
    print(f"❌ Migration failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF

MIGRATION_RESULT=$?

if [ $MIGRATION_RESULT -eq 0 ]; then
    echo ""
    log_info "Migration completed successfully!"
    
    echo ""
    echo -e "${CYAN}📁 NEW CONFIGURATION STRUCTURE:${NC}"
    echo "================================"
    
    # List new structure
    if [[ -d "config/channels" ]]; then
        echo "  📂 config/channels/ - Individual channel configs"
    fi
    
    if [[ -d "config/containers" ]]; then
        echo "  📂 config/containers/ - Individual container configs"
    fi
    
    echo "  📄 config/config.json - System settings"
    echo "  📄 config/auth.json - Bot authentication"
    echo "  📄 config/heartbeat.json - Heartbeat settings"
    echo "  📄 config/advanced_settings.json - Advanced settings"
    echo "  📄 config/web_ui.json - Web interface settings"
    
    echo ""
    echo -e "${GREEN}🎉 YOUR DDC INSTALLATION HAS BEEN UPGRADED TO v2.0!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Restart your DDC container/service"
    echo "2. Verify all containers and channels are working"
    echo "3. Check the web interface"
    echo ""
    echo "Your original config has been backed up to: $BACKUP_DIR"
    
else
    log_error "Migration failed!"
    echo ""
    echo "Your original configuration is safe in: $BACKUP_DIR"
    echo "Please check the error messages above and try again."
    echo ""
    echo "If you continue to have issues, please report them at:"
    echo "https://github.com/YOUR_REPO/issues"
fi