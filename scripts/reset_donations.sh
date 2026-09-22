#!/bin/bash
# =============================================================================
# DockerDiscordControl - Reset All Donations (Test Mode)
# =============================================================================
# WARNING: deletes ALL donations and the event history!
# Only suitable for test operation!
# =============================================================================

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Base directory is one level up from scripts/
BASE_DIR="$(dirname "$SCRIPT_DIR")"
PROGRESS_DIR="$BASE_DIR/config/progress"

echo "🔄 DDC - Reset All Donations"
echo "=============================="
echo ""
echo "📂 Working directory: $BASE_DIR"
echo ""
echo "⚠️  WARNING: this deletes ALL donations and the event history!"
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "❌ Aborted."
    exit 1
fi

echo ""
echo "📦 Creating backup..."
BACKUP_DIR="$PROGRESS_DIR/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "$PROGRESS_DIR/events.jsonl" ]; then
    cp "$PROGRESS_DIR/events.jsonl" "$BACKUP_DIR/"
    echo "✅ Event log backed up to: $BACKUP_DIR"
fi

if [ -d "$PROGRESS_DIR/snapshots" ]; then
    cp -r "$PROGRESS_DIR/snapshots" "$BACKUP_DIR/"
    echo "✅ Snapshots backed up to: $BACKUP_DIR"
fi

echo ""
echo "🗑️  Deleting event log..."
echo "" > "$PROGRESS_DIR/events.jsonl"
echo "✅ Event log deleted"

echo ""
echo "🗑️  Deleting snapshots..."
rm -rf "$PROGRESS_DIR/snapshots"/*
echo "✅ Snapshots deleted"

echo ""
echo "🗑️  Resetting sequence number..."
echo "0" > "$PROGRESS_DIR/last_seq.txt"
echo "✅ Sequence reset"

echo ""
echo "🔄 Restarting container..."
docker restart dockerdiscordcontrol

echo ""
echo "✅ Reset complete!"
echo "📊 Status:"
echo "   - All donations deleted"
echo "   - Level reset to 1"
echo "   - Power reset to $0"
echo "   - Backup created in: $BACKUP_DIR"
echo ""
echo "🎉 Done! DDC is now in a fresh state."
