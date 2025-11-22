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
BACKUP_DIR="/Volumes/appdata/dockerdiscordcontrol/data/progress/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f "/Volumes/appdata/dockerdiscordcontrol/data/progress/event_log.jsonl" ]; then
    cp "/Volumes/appdata/dockerdiscordcontrol/data/progress/event_log.jsonl" "$BACKUP_DIR/"
    echo "✅ Event log backed up to: $BACKUP_DIR"
fi

if [ -f "/Volumes/appdata/dockerdiscordcontrol/data/progress/snapshot.json" ]; then
    cp "/Volumes/appdata/dockerdiscordcontrol/data/progress/snapshot.json" "$BACKUP_DIR/"
    echo "✅ Snapshot backed up to: $BACKUP_DIR"
fi

echo ""
echo "🗑️  Lösche Event Log..."
echo "" > /Volumes/appdata/dockerdiscordcontrol/data/progress/event_log.jsonl
echo "✅ Event log gelöscht"

echo ""
echo "🗑️  Lösche Snapshot..."
rm -f /Volumes/appdata/dockerdiscordcontrol/data/progress/snapshot.json
echo "✅ Snapshot gelöscht"

echo ""
echo "🔄 Starte Container neu..."
docker restart DockerDiscordControl

echo ""
echo "✅ Reset abgeschlossen!"
echo "📊 Status:"
echo "   - Alle Donations gelöscht"
echo "   - Level reset zu 1"
echo "   - Power reset zu $0"
echo "   - Backup erstellt in: $BACKUP_DIR"
echo ""
echo "🎉 Fertig! DDC ist jetzt im frischen Zustand."
