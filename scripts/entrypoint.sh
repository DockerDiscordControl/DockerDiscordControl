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

# Function to get docker socket GID
get_docker_socket_gid() {
    if [ -S /var/run/docker.sock ]; then
        stat -c %g /var/run/docker.sock 2>/dev/null || \
        ls -ln /var/run/docker.sock | awk '{print $4}'
    fi
}

# Unraid/Docker permission fix
# If running as root (UID 0), fix permissions and switch to ddc user
if [ "$(id -u)" = "0" ]; then
    echo "Running as root, setting up permissions..."
    echo "Target UID: $PUID, Target GID: $PGID"

    # Get docker socket GID for later
    DOCKER_GID=$(get_docker_socket_gid)
    if [ -n "$DOCKER_GID" ]; then
        echo "Docker socket GID: $DOCKER_GID"
    fi

    # Modify ddc user/group to match PUID/PGID if different
    if [ "$PUID" != "1000" ] || [ "$PGID" != "1000" ]; then
        echo "Adjusting ddc user to UID=$PUID, GID=$PGID..."

        # Step 1: Delete user first (before group)
        deluser ddc 2>/dev/null || true

        # Step 2: Handle group
        if [ "$PGID" != "1000" ]; then
            delgroup ddc 2>/dev/null || true
            addgroup -g "$PGID" -S ddc 2>/dev/null || addgroup -S ddc 2>/dev/null || true
        fi

        # Step 3: Recreate user with correct UID/GID
        adduser -u "$PUID" -G ddc -D -H -s /sbin/nologin ddc 2>/dev/null || \
        adduser -G ddc -D -H -s /sbin/nologin ddc 2>/dev/null || true

        echo "User ddc recreated with UID=$PUID, GID=$PGID"
    fi

    # Step 4: Ensure docker socket access (critical for DDC!)
    if [ -n "$DOCKER_GID" ]; then
        # Create docker group with socket's GID if it doesn't exist
        DOCKER_GROUP_NAME=$(awk -F: -v gid="$DOCKER_GID" '($3 == gid) { print $1; exit }' /etc/group 2>/dev/null || true)
        if [ -z "$DOCKER_GROUP_NAME" ]; then
            DOCKER_GROUP_NAME="dockersock"
            addgroup -g "$DOCKER_GID" -S "$DOCKER_GROUP_NAME" 2>/dev/null || true
        fi
        # Add ddc user to docker socket group
        addgroup ddc "$DOCKER_GROUP_NAME" 2>/dev/null || true
        echo "Added ddc to docker group ($DOCKER_GROUP_NAME, GID=$DOCKER_GID)"
    fi

    # Step 5: Ensure directories exist
    mkdir -p /app/config /app/logs /app/cached_displays
    mkdir -p /app/config/info /app/config/tasks /app/config/channels

    # Step 6: Fix ownership of data directories
    echo "Fixing ownership of data directories..."

    # Try chown - if it fails (e.g., NFS with root_squash), we'll detect it
    CHOWN_FAILED=0
    chown -R "$PUID:$PGID" /app/config 2>/dev/null || CHOWN_FAILED=1
    chown -R "$PUID:$PGID" /app/logs 2>/dev/null || true
    chown -R "$PUID:$PGID" /app/cached_displays 2>/dev/null || true
    chown "$PUID:$PGID" /app 2>/dev/null || true

    # Step 7: Verify we can actually write (the real test)
    # Create a test file as the target user to verify permissions work
    TEST_FILE="/app/config/.permission_test_$$"
    if su-exec "$PUID:$PGID" touch "$TEST_FILE" 2>/dev/null; then
        rm -f "$TEST_FILE" 2>/dev/null || true
        echo "Permission verification: SUCCESS"
    else
        # chown didn't work and we can't write - this is a real problem
        echo ""
        echo "==============================================================="
        echo "   PERMISSION ERROR - CANNOT WRITE TO CONFIG                   "
        echo "==============================================================="
        echo ""
        echo "The container cannot write to /app/config as UID $PUID."
        echo ""
        echo "This usually happens on Unraid/NAS systems where:"
        echo "  1. The volume is owned by a different user (e.g., nobody:users)"
        echo "  2. NFS root_squash prevents permission changes"
        echo ""
        echo "SOLUTIONS:"
        echo ""
        echo "  Option 1: Set PUID/PGID to match volume owner"
        echo "    On Unraid, typically: PUID=99 PGID=100"
        echo "    Check owner with: ls -ln /path/to/config"
        echo ""
        echo "  Option 2: Fix permissions on host"
        echo "    chown -R $PUID:$PGID /path/to/config"
        echo ""
        echo "  Option 3: Use permissive mode (less secure)"
        echo "    chmod -R 777 /path/to/config"
        echo ""
        echo "Current volume permissions:"
        ls -ld /app/config
        echo "==============================================================="
        exit 1
    fi

    echo "Dropping privileges to ddc user (UID=$PUID)..."

    # Build supplementary groups string for su-exec
    SUPP_GROUPS="$PGID"
    if [ -n "$DOCKER_GID" ] && [ "$DOCKER_GID" != "$PGID" ]; then
        SUPP_GROUPS="$SUPP_GROUPS,$DOCKER_GID"
    fi

    # Execute this script again as the ddc user with docker group
    exec su-exec "$PUID:$PGID" "$0" "$@"
fi

# At this point we're running as the ddc user (non-root)
echo "Running as user: $(id)"

# Verify docker socket access
if [ -S /var/run/docker.sock ]; then
    if [ -r /var/run/docker.sock ]; then
        echo "Docker socket: accessible"
    else
        echo "WARNING: Docker socket exists but is not readable!"
        echo "Docker operations may fail. Check docker socket permissions."
    fi
fi

# Final permission check
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
