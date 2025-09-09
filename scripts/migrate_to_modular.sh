#!/bin/bash
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Modular Config Migration Script               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
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

log_success() {
    echo -e "${PURPLE}🎉 $1${NC}"
}

# Script header
echo -e "${CYAN}"
echo "============================================================================"
echo "  DDC MODULAR CONFIG MIGRATION SCRIPT"
echo "  Converting legacy config structure to modular architecture"
echo "============================================================================"
echo -e "${NC}"

# Check if we're in the right directory
if [[ ! -f "config/bot_config.json" && ! -f "config/docker_config.json" ]]; then
    log_error "Not in DDC directory or config files not found!"
    echo "Please run this script from the DDC root directory"
    exit 1
fi

# Change to config directory
cd config

log_step "Starting modular config migration..."

# Create backup first
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
log_step "Creating backup in $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"
cp *.json "$BACKUP_DIR/" 2>/dev/null || true
log_info "Backup created in config/$BACKUP_DIR"

# Step 1: Create modular directories
log_step "Creating modular directory structure..."
mkdir -p channels containers
chmod 755 channels containers
log_info "Created directories: channels/ containers/"

# Step 2: Migrate channels
log_step "Migrating channels configuration..."

if [[ -f "channels_config.json" ]]; then
    # Extract channel data using Python for reliable JSON parsing
    python3 << 'EOF'
import json
import sys

try:
    with open('channels_config.json', 'r', encoding='utf-8') as f:
        channels_data = json.load(f)
    
    channel_permissions = channels_data.get('channel_permissions', {})
    
    # Create individual channel files
    for channel_id, channel_config in channel_permissions.items():
        channel_config['channel_id'] = channel_id
        
        with open(f'channels/{channel_id}.json', 'w', encoding='utf-8') as f:
            json.dump(channel_config, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Created: channels/{channel_id}.json ({channel_config.get('name', channel_id)})")
    
    print(f"✅ Migrated {len(channel_permissions)} channels")
    
except Exception as e:
    print(f"❌ Error migrating channels: {e}")
    sys.exit(1)
EOF

    # Create default channel config
    cat > channels/default.json << 'EOF'
{
  "name": "Default Channel Settings",
  "commands": {
    "serverstatus": true,
    "command": false,
    "control": false,
    "schedule": false
  },
  "post_initial": false,
  "update_interval_minutes": 10,
  "inactivity_timeout_minutes": 10,
  "enable_auto_refresh": true,
  "recreate_messages_on_inactivity": true
}
EOF
    log_info "Created: channels/default.json"
else
    log_warn "channels_config.json not found - skipping channel migration"
fi

# Step 3: Migrate containers
log_step "Migrating container configurations..."

if [[ -f "docker_config.json" ]]; then
    # Extract container data using Python
    python3 << 'EOF'
import json
import sys

try:
    with open('docker_config.json', 'r', encoding='utf-8') as f:
        docker_data = json.load(f)
    
    servers = docker_data.get('servers', [])
    
    # Create individual container files
    for server in servers:
        container_name = server.get('docker_name', server.get('name', 'unknown'))
        
        with open(f'containers/{container_name}.json', 'w', encoding='utf-8') as f:
            json.dump(server, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Created: containers/{container_name}.json")
    
    print(f"✅ Migrated {len(servers)} containers")
    
    # Create docker_settings.json
    docker_settings = {
        "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
        "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
        "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
        "max_log_lines": docker_data.get("max_log_lines", 50)
    }
    
    with open('docker_settings.json', 'w', encoding='utf-8') as f:
        json.dump(docker_settings, f, indent=2, ensure_ascii=False)
    
    print("✅ Created: docker_settings.json")
    
except Exception as e:
    print(f"❌ Error migrating containers: {e}")
    sys.exit(1)
EOF
else
    log_warn "docker_config.json not found - skipping container migration"
fi

# Step 4: Migrate system configs
log_step "Creating system configuration files..."

if [[ -f "bot_config.json" ]]; then
    # Extract system configs using Python
    python3 << 'EOF'
import json
import sys

try:
    with open('bot_config.json', 'r', encoding='utf-8') as f:
        bot_data = json.load(f)
    
    # Create config.json (main system config)
    main_config = {
        "language": bot_data.get("language", "en"),
        "timezone": bot_data.get("timezone", "UTC"),
        "guild_id": bot_data.get("guild_id"),
        "system_logs": {
            "level": "INFO",
            "max_file_size_mb": 10,
            "backup_count": 5,
            "enable_debug": False
        }
    }
    
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(main_config, f, indent=2, ensure_ascii=False)
    
    print("✅ Created: config.json")
    
    # Create heartbeat.json
    heartbeat_config = {
        "heartbeat_channel_id": bot_data.get("heartbeat_channel_id"),
        "enabled": bot_data.get("heartbeat_channel_id") is not None,
        "interval_minutes": 30,
        "message_template": "🤖 DDC Heartbeat - All systems operational"
    }
    
    with open('heartbeat.json', 'w', encoding='utf-8') as f:
        json.dump(heartbeat_config, f, indent=2, ensure_ascii=False)
    
    print("✅ Created: heartbeat.json")
    
    # Create auth.json
    auth_config = {
        "bot_token": bot_data.get("bot_token"),
        "encryption_enabled": True
    }
    
    with open('auth.json', 'w', encoding='utf-8') as f:
        json.dump(auth_config, f, indent=2, ensure_ascii=False)
    
    print("✅ Created: auth.json")
    
except Exception as e:
    print(f"❌ Error creating system configs: {e}")
    sys.exit(1)
EOF
else
    log_warn "bot_config.json not found - creating default system configs"
    
    # Create default configs
    cat > config.json << 'EOF'
{
  "language": "en",
  "timezone": "UTC",
  "guild_id": null,
  "system_logs": {
    "level": "INFO",
    "max_file_size_mb": 10,
    "backup_count": 5,
    "enable_debug": false
  }
}
EOF

    cat > heartbeat.json << 'EOF'
{
  "heartbeat_channel_id": null,
  "enabled": false,
  "interval_minutes": 30,
  "message_template": "🤖 DDC Heartbeat - All systems operational"
}
EOF

    cat > auth.json << 'EOF'
{
  "bot_token": null,
  "encryption_enabled": true
}
EOF
    
    log_info "Created default system configs"
fi

# Step 5: Migrate web configs
log_step "Creating web configuration files..."

if [[ -f "web_config.json" ]]; then
    # Extract web configs using Python
    python3 << 'EOF'
import json
import sys

try:
    with open('web_config.json', 'r', encoding='utf-8') as f:
        web_data = json.load(f)
    
    # Create advanced_settings.json
    advanced_settings = web_data.get("advanced_settings", {})
    
    with open('advanced_settings.json', 'w', encoding='utf-8') as f:
        json.dump(advanced_settings, f, indent=2, ensure_ascii=False)
    
    print("✅ Created: advanced_settings.json")
    
    # Create web_ui.json (without advanced_settings)
    web_ui_config = {
        "web_ui_user": web_data.get("web_ui_user", "admin"),
        "web_ui_password_hash": web_data.get("web_ui_password_hash"),
        "admin_enabled": web_data.get("admin_enabled", True),
        "session_timeout": web_data.get("session_timeout", 3600),
        "donation_disable_key": web_data.get("donation_disable_key", ""),
        "scheduler_debug_mode": web_data.get("scheduler_debug_mode", False)
    }
    
    with open('web_ui.json', 'w', encoding='utf-8') as f:
        json.dump(web_ui_config, f, indent=2, ensure_ascii=False)
    
    print("✅ Created: web_ui.json")
    
except Exception as e:
    print(f"❌ Error creating web configs: {e}")
    sys.exit(1)
EOF
else
    log_warn "web_config.json not found - creating default web configs"
    
    cat > advanced_settings.json << 'EOF'
{
  "DDC_DOCKER_CACHE_DURATION": 30,
  "DDC_DOCKER_QUERY_COOLDOWN": 2,
  "DDC_DOCKER_MAX_CACHE_AGE": 300,
  "DDC_ENABLE_BACKGROUND_REFRESH": true,
  "DDC_BACKGROUND_REFRESH_INTERVAL": 300,
  "DDC_BACKGROUND_REFRESH_LIMIT": 50,
  "DDC_BACKGROUND_REFRESH_TIMEOUT": 30,
  "DDC_MAX_CONTAINERS_DISPLAY": 100,
  "DDC_SCHEDULER_CHECK_INTERVAL": 120,
  "DDC_MAX_CONCURRENT_TASKS": 3,
  "DDC_TASK_BATCH_SIZE": 5,
  "DDC_LIVE_LOGS_REFRESH_INTERVAL": 5,
  "DDC_LIVE_LOGS_MAX_REFRESHES": 12,
  "DDC_LIVE_LOGS_TAIL_LINES": 50,
  "DDC_LIVE_LOGS_TIMEOUT": 120,
  "DDC_LIVE_LOGS_ENABLED": true,
  "DDC_LIVE_LOGS_AUTO_START": false,
  "DDC_FAST_STATS_TIMEOUT": 10,
  "DDC_SLOW_STATS_TIMEOUT": 30,
  "DDC_CONTAINER_LIST_TIMEOUT": 15
}
EOF

    cat > web_ui.json << 'EOF'
{
  "web_ui_user": "admin",
  "web_ui_password_hash": null,
  "admin_enabled": true,
  "session_timeout": 3600,
  "donation_disable_key": "",
  "scheduler_debug_mode": false
}
EOF
    
    log_info "Created default web configs"
fi

# Step 6: Handle system_tasks.json
log_step "Handling system tasks..."

if [[ -f "tasks.json" && ! -f "system_tasks.json" ]]; then
    cp tasks.json system_tasks.json
    log_info "Created: system_tasks.json (copied from tasks.json)"
elif [[ ! -f "system_tasks.json" ]]; then
    echo '{}' > system_tasks.json
    log_info "Created: system_tasks.json (empty)"
fi

# Step 7: Set proper permissions
log_step "Setting file permissions..."
chmod 644 channels/*.json containers/*.json *.json 2>/dev/null || true

# Try to set ownership (may fail if not root, but that's okay)
if command -v chown >/dev/null 2>&1; then
    chown -R 99:100 channels containers 2>/dev/null || true
    chown 99:100 *.json 2>/dev/null || true
fi

# Step 8: Verify migration
log_step "Verifying migration..."

echo ""
echo -e "${CYAN}📁 NEW MODULAR STRUCTURE:${NC}"
echo "=========================="

if [[ -d "channels" ]]; then
    CHANNEL_COUNT=$(ls -1 channels/*.json 2>/dev/null | wc -l)
    echo -e "${GREEN}📂 channels/ (${CHANNEL_COUNT} files)${NC}"
    for file in channels/*.json; do
        if [[ -f "$file" ]]; then
            echo "   - $(basename "$file")"
        fi
    done
fi

echo ""

if [[ -d "containers" ]]; then
    CONTAINER_COUNT=$(ls -1 containers/*.json 2>/dev/null | wc -l)
    echo -e "${GREEN}📂 containers/ (${CONTAINER_COUNT} files)${NC}"
    for file in containers/*.json; do
        if [[ -f "$file" ]]; then
            echo "   - $(basename "$file")"
        fi
    done
fi

echo ""
echo -e "${CYAN}📄 NEW CONFIG FILES:${NC}"
echo "===================="

CONFIG_FILES=("config.json" "auth.json" "heartbeat.json" "advanced_settings.json" "web_ui.json" "docker_settings.json" "system_tasks.json")

for file in "${CONFIG_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        echo -e "   ${GREEN}✅ $file${NC}"
    else
        echo -e "   ${RED}❌ $file${NC}"
    fi
done

echo ""
echo -e "${CYAN}📋 EXISTING FILES (unchanged):${NC}"
echo "================================"
for file in spam_protection.json mech_donations.json mech_state.json server_order.json update_status.json; do
    if [[ -f "$file" ]]; then
        echo -e "   ${GREEN}✅ $file${NC}"
    fi
done

# Step 9: Summary
echo ""
log_success "MODULAR CONFIG MIGRATION COMPLETED!"
echo ""
echo -e "${YELLOW}📌 NEXT STEPS:${NC}"
echo "1. Restart your DDC application to use the new modular structure"
echo "2. Verify that all containers and channels are working properly"
echo "3. Check the web interface for any configuration issues"
echo "4. The old config files have been backed up in: config/$BACKUP_DIR"
echo ""
echo -e "${CYAN}🎯 YOUR MODULAR ARCHITECTURE IS NOW READY!${NC}"
echo "   ✅ Individual channel configurations"
echo "   ✅ Individual container configurations" 
echo "   ✅ Separated system, auth, and web configs"
echo "   ✅ Clean, maintainable structure"
echo ""
echo -e "${GREEN}Migration script completed successfully! 🚀${NC}"