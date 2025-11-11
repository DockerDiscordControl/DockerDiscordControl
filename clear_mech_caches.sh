#!/bin/bash

echo "=== Clearing all Mech-related caches ==="
echo

# Clear cache directories if they exist
CACHE_DIRS=(
    "cache/mech_cache"
    "cache/evolution_cache"
    "cache/mech_status_cache"
    "cache"
)

for dir in "${CACHE_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "Clearing directory: $dir"
        find "$dir" -name "*.json" -type f -delete 2>/dev/null
        find "$dir" -name "*.cache" -type f -delete 2>/dev/null
        find "$dir" -name "*.pkl" -type f -delete 2>/dev/null
    fi
done

# Clear specific cache files
CACHE_FILES=(
    "cache/mech_cache.json"
    "cache/evolution_cache.json"
    "cache/mech_status.json"
    "mech_cache.json"
    "evolution_cache.json"
)

for file in "${CACHE_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "Removing file: $file"
        rm -f "$file"
    fi
done

# Clear Python __pycache__ directories that might contain cached data
echo "Clearing Python caches..."
find services/mech -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# If running in Docker, clear inside container too
if [ -f /.dockerenv ]; then
    echo "Running inside Docker - clearing container caches..."
    find /app/cache -type f -delete 2>/dev/null
    find /app -name "*.pyc" -delete 2>/dev/null
fi

echo
echo "=== Cache clearing complete ==="
echo "Please restart the bot for changes to take effect."