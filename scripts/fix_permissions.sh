#!/bin/sh

echo "🔧 DDC: Fixing permissions for config and logs..."

# Create directories if they don't exist
mkdir -p /app/config/info /app/config/tasks /app/logs

# Set ownership to current user (99:100 on Unraid)
chown -R $(id -u):$(id -g) /app/config /app/logs

# Set permissions - config needs to be writable
chmod -R 755 /app/config
chmod -R 755 /app/logs

# Make JSON files writable
find /app/config -name "*.json" -exec chmod 666 {} \; 2>/dev/null || true

echo "✅ DDC: Permissions fixed successfully!"
echo "   Config dir: $(ls -ld /app/config)"
echo "   Logs dir: $(ls -ld /app/logs)" 