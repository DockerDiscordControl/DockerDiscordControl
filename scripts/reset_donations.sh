#!/bin/bash
# =============================================================================
# DockerDiscordControl - Reset All Donations (Test Mode)
# =============================================================================
# WARNUNG: Löscht ALLE Donations und Event-Historie!
# Nur für Test-Betrieb geeignet!
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
echo "📂 Arbeitsverzeichnis: $BASE_DIR"
echo ""
echo "⚠️  WARNUNG: Dies löscht ALLE Donations und Event-Historie!"
echo ""
read -p "Fortfahren? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "❌ Abgebrochen."
    exit 1
fi

echo ""
echo "📦 Erstelle Backup..."
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
echo "🗑️  Lösche Event Log..."
echo "" > "$PROGRESS_DIR/events.jsonl"
echo "✅ Event log gelöscht"

echo ""
echo "🗑️  Lösche Snapshots..."
rm -rf "$PROGRESS_DIR/snapshots"/*
echo "✅ Snapshots gelöscht"

echo ""
echo "🗑️  Reset Sequenz-Nummer..."
echo "0" > "$PROGRESS_DIR/last_seq.txt"
echo "✅ Sequenz zurückgesetzt"

echo ""
echo "🔄 Starte Container neu..."
docker restart dockerdiscordcontrol

echo ""
echo "✅ Reset abgeschlossen!"
echo "📊 Status:"
echo "   - Alle Donations gelöscht"
echo "   - Level reset zu 1"
echo "   - Power reset zu $0"
echo "   - Backup erstellt in: $BACKUP_DIR"
echo ""
echo "🎉 Fertig! DDC ist jetzt im frischen Zustand."
