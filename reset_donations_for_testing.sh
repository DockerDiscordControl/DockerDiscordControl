#!/bin/bash

echo "============================================================"
echo "RESET: Donations & Power Gift für Testing"
echo "============================================================"
echo

# 1. Stop container
echo "[1/5] Stopping container..."
docker stop dockerdiscordcontrol
sleep 2

# 2. Reset snapshot
echo "[2/5] Resetting snapshot to Level 1, 0 donations..."
cat > config/progress/snapshots/main.json << 'EOF'
{
  "mech_id": "main",
  "level": 1,
  "evo_acc": 0,
  "power_acc": 0,
  "goal_requirement": 1050,
  "difficulty_bin": 1,
  "goal_started_at": "2025-11-11T15:00:00.000000+00:00",
  "last_decay_day": "2025-11-11",
  "power_decay_per_day": 100,
  "version": 1,
  "last_event_seq": 0,
  "mech_type": "default",
  "last_user_count_sample": 1,
  "cumulative_donations_cents": 0
}
EOF

# 3. Clear event logs COMPLETELY
echo "[3/5] Clearing event logs..."
rm -f config/progress/events.jsonl 2>/dev/null
rm -f config/progress/last_seq.txt 2>/dev/null
echo "0" > config/progress/last_seq.txt

# 4. Clear donation history
echo "[4/5] Clearing donation history..."
cat > config/mech_donations.json << 'EOF'
{
  "donations": []
}
EOF

# 5. Verify reset
echo "[5/5] Verifying reset..."
echo
cat config/progress/snapshots/main.json
echo

echo "============================================================"
echo "✅ RESET COMPLETE!"
echo
echo "System zurückgesetzt:"
echo "- Level: 1"
echo "- Power: 0 (Power-Geschenk wird beim Start gegeben!)"
echo "- Evolution: 0"
echo "- Donations: 0"
echo
echo "Jetzt einfach rebuild ausführen:"
echo "  scripts/./rebuild.sh"
echo
echo "Beim Start bekommst du automatisch das Power-Geschenk (1-3$)"
echo "weil power_acc == 0!"
echo "============================================================"
