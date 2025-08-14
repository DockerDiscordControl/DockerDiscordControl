#!/bin/bash
# DockerDiscordControl - Secure Environment Loader
# This script securely loads environment variables from config files

set -euo pipefail

CONFIG_DIR="/app/config"
BOT_CONFIG_FILE="$CONFIG_DIR/bot_config.json"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ENV-LOADER] $1"
}

# Function to extract token from JSON config
extract_token_from_config() {
    if [[ -f "$BOT_CONFIG_FILE" ]]; then
        # Use jq if available, otherwise use Python
        if command -v jq >/dev/null 2>&1; then
            jq -r '.bot_token // empty' "$BOT_CONFIG_FILE" 2>/dev/null || echo ""
        else
            python3 -c "
import json, sys
try:
    with open('$BOT_CONFIG_FILE', 'r') as f:
        data = json.load(f)
        print(data.get('bot_token', ''))
except:
    print('')
" 2>/dev/null || echo ""
        fi
    else
        echo ""
    fi
}

# Main security enhancement
main() {
    log "🔒 DDC Security Enhancement - Loading environment variables"
    
    # Check if DISCORD_BOT_TOKEN is already set
    if [[ -n "${DISCORD_BOT_TOKEN:-}" ]]; then
        log "✅ DISCORD_BOT_TOKEN already set via environment variable (secure)"
        return 0
    fi
    
    # Try to load from config file as fallback
    log "⚠️  DISCORD_BOT_TOKEN not found in environment, checking config file"
    
    TOKEN=$(extract_token_from_config)
    
    if [[ -n "$TOKEN" && "$TOKEN" != "null" ]]; then
        export DISCORD_BOT_TOKEN="$TOKEN"
        log "✅ Loaded bot token from config file and exported to environment"
        log "💡 Recommendation: Set DISCORD_BOT_TOKEN environment variable directly for better security"
        return 0
    else
        log "❌ No bot token found in config file"
        log "🔧 Please set DISCORD_BOT_TOKEN environment variable or configure bot_config.json"
        return 1
    fi
}

# Run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi