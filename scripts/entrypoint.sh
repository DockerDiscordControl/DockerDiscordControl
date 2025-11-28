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
echo "   Version: 2.1.2 (Optimized)"
echo "   Architecture: Single Process (Waitress + Bot)"
echo "==============================================================="

# Default UID/GID (can be overridden via environment variables)
PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Function to check directory permissions
check_permissions() {
    local dir=$1
    if [ ! -w "$dir" ]; then
        echo "ERROR: No write permission for $dir"
        echo "Current user: $(id)"
        ls -ld "$dir"
        return 1
    fi
    return 0
}

# Unraid/Docker permission fix
# If running as root (UID 0), fix permissions and switch to ddc user
if [ "$(id -u)" = "0" ]; then
    echo "Running as root, setting up permissions..."
    echo "Target UID: $PUID, Target GID: $PGID"

    # Modify ddc user/group to match PUID/PGID if different
    if [ "$PUID" != "1000" ] || [ "$PGID" != "1000" ]; then
        echo "Adjusting ddc user to UID=$PUID, GID=$PGID..."

        # Change group GID
        if [ "$PGID" != "1000" ]; then
            delgroup ddc 2>/dev/null || true
            addgroup -g "$PGID" -S ddc 2>/dev/null || true
        fi

        # Change user UID and group
        if [ "$PUID" != "1000" ]; then
            deluser ddc 2>/dev/null || true
            adduser -u "$PUID" -G ddc -D -H -s /sbin/nologin ddc 2>/dev/null || true
        fi
    fi

    # Ensure directories exist
    mkdir -p /app/config /app/logs /app/cached_displays
    mkdir -p /app/config/info /app/config/tasks /app/config/channels

    # Fix ownership of data directories
    echo "Fixing ownership of data directories..."
    chown -R "$PUID:$PGID" /app/config /app/logs /app/cached_displays 2>/dev/null || true

    # Also fix ownership of app directory for write access
    chown "$PUID:$PGID" /app 2>/dev/null || true

    # Verify permissions after fix
    if ! check_permissions "/app/config"; then
        echo ""
        echo "==============================================================="
        echo "   PERMISSION FIX FAILED                                       "
        echo "==============================================================="
        echo "Could not fix permissions for /app/config"
        echo ""
        echo "Please ensure your volume mount has correct permissions:"
        echo "  - On Unraid: Set PUID and PGID to match your user (usually 99:100)"
        echo "  - Example: docker run -e PUID=99 -e PGID=100 ..."
        echo ""
        echo "Or manually fix permissions on the host:"
        echo "  chown -R 1000:1000 /path/to/your/config"
        echo "==============================================================="
        exit 1
    fi

    echo "Permissions configured successfully."
    echo "Dropping privileges to ddc user (UID=$PUID)..."

    # Execute this script again as the ddc user
    exec su-exec "$PUID:$PGID" "$0" "$@"
fi

# At this point we're running as the ddc user (non-root)
echo "Running as user: $(id)"

# Final permission check (should pass now)
if ! check_permissions "/app/config"; then
    echo ""
    echo "==============================================================="
    echo "   PERMISSION ERROR                                            "
    echo "==============================================================="
    echo "Cannot write to /app/config"
    echo ""
    echo "Try setting PUID/PGID environment variables to match your host user."
    echo "On Unraid, this is typically PUID=99 and PGID=100"
    echo "==============================================================="
    exit 1
fi

if ! check_permissions "/app/logs"; then
    echo "WARNING: Cannot write to /app/logs, logging may fail"
fi

# Start the application via the single entry point
echo "Starting application (run.py)..."
exec python3 run.py
