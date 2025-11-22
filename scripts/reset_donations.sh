#!/bin/bash
# =============================================================================
# DockerDiscordControl - Reset All Donations (Test Mode)
# =============================================================================
# WARNUNG: Löscht ALLE Donations und Event-Historie!
# Nur für Test-Betrieb geeignet!
# =============================================================================

set -e

echo "🔄 DDC - Reset All Donations"
echo "=============================="
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
BACKUP_DIR="/Volumes/appdata/dockerdiscordcontrol/config/progress/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "/Volumes/appdata/dockerdiscordcontrol/config/progress/events.jsonl" ]; then
    cp "/Volumes/appdata/dockerdiscordcontrol/config/progress/events.jsonl" "$BACKUP_DIR/"
    echo "✅ Event log backed up to: $BACKUP_DIR"
fi

if [ -d "/Volumes/appdata/dockerdiscordcontrol/config/progress/snapshots" ]; then
    cp -r "/Volumes/appdata/dockerdiscordcontrol/config/progress/snapshots" "$BACKUP_DIR/"
    echo "✅ Snapshots backed up to: $BACKUP_DIR"
fi

echo ""
echo "🗑️  Lösche Event Log..."
echo "" > /Volumes/appdata/dockerdiscordcontrol/config/progress/events.jsonl
echo "✅ Event log gelöscht"

echo ""
echo "🗑️  Lösche Snapshots..."
rm -rf /Volumes/appdata/dockerdiscordcontrol/config/progress/snapshots/*
echo "✅ Snapshots gelöscht"

echo ""
echo "🗑️  Reset Sequenz-Nummer..."
echo "0" > /Volumes/appdata/dockerdiscordcontrol/config/progress/last_seq.txt
echo "✅ Sequenz zurückgesetzt"

echo ""
echo "🔄 Starte Container neu..."
docker restart ddc

echo ""
echo "✅ Reset abgeschlossen!"
echo "📊 Status:"
echo "   - Alle Donations gelöscht"
echo "   - Level reset zu 1"
echo "   - Power reset zu $0"
echo "   - Backup erstellt in: $BACKUP_DIR"
echo ""
echo "🎉 Fertig! DDC ist jetzt im frischen Zustand."
