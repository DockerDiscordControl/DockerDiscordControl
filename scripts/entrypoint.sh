#!/bin/sh
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

# Fail on error
set -e

echo "==============================================================="
echo "   DockerDiscordControl (DDC) - Container Startup              "
echo "==============================================================="
echo "   Version: 2.5.0 (Optimized)"
echo "   Architecture: Single Process (Waitress + Bot)"
echo "==============================================================="

# Function to check directory permissions
check_permissions() {
    local dir=$1
    if [ ! -w "$dir" ]; then
        echo "ERROR: No write permission for $dir"
        echo "Current user: $(id)"
        ls -ld "$dir"
        return 1
    fi
}

# Ensure config directory exists and is writable
if [ ! -d "/app/config" ]; then
    echo "Creating config directory..."
    mkdir -p /app/config
fi
check_permissions "/app/config"

# Ensure logs directory exists and is writable
if [ ! -d "/app/logs" ]; then
    echo "Creating logs directory..."
    mkdir -p /app/logs
fi
check_permissions "/app/logs"

# Ensure cached_displays directory exists and is writable
if [ ! -d "/app/cached_displays" ]; then
    echo "Creating cached_displays directory..."
    mkdir -p /app/cached_displays
fi
check_permissions "/app/cached_displays"

# Unraid/Docker permission fix
# If running as root (UID 0), try to switch to ddc user (UID 1000)
# But if the mounted volumes are owned by nobody/users (99:100), we might need to adjust
if [ "$(id -u)" = "0" ]; then
    echo "Running as root, fixing permissions..."
    chown -R ddc:ddc /app/config /app/logs /app/cached_displays
    echo "Switching to user ddc..."
    exec su-exec ddc "$0" "$@"
fi

# Start the application via the single entry point
echo "Starting application (run.py)..."
exec python3 run.py
