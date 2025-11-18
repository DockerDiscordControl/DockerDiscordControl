#!/bin/sh
# Entrypoint script for DockerDiscordControl
# Ensures proper permissions for non-root user 'ddc'

echo "Starting DockerDiscordControl as user: $(whoami) (UID: $(id -u), GID: $(id -g))"
echo "Groups: $(groups)"

# Check Docker socket access
if [ -S /var/run/docker.sock ]; then
    echo "Docker socket found at /var/run/docker.sock"
    
    # Get socket group ownership
    SOCKET_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock 2>/dev/null)
    
    if [ -n "$SOCKET_GID" ]; then
        echo "Docker socket GID: $SOCKET_GID"
        
        # Check if we're in the docker group
        if groups | grep -q docker; then
            echo "User 'ddc' is in docker group - container control should work"
        else
            echo "WARNING: User 'ddc' is not in docker group - container control may not work"
        fi
    fi
    
    # Test Docker access using Python SDK (no docker-cli binary needed)
    if python3 -c "import docker; docker.from_env().ping()" > /dev/null 2>&1; then
        echo "✓ Docker daemon accessible via Python SDK"
    else
        echo "⚠ WARNING: Cannot access Docker daemon - container control will not work"
        echo "  Make sure the Docker socket is mounted and accessible"
    fi
else
    echo "⚠ WARNING: Docker socket not found at /var/run/docker.sock"
    echo "  Container control features will not work"
fi

# Ensure directories exist with correct permissions
mkdir -p /app/config /app/logs /app/config/info /app/config/tasks
echo "Directory permissions set"

# Start supervisord to manage both bot and web UI
echo "Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf