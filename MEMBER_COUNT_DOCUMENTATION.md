# Member Count Documentation

## Wie funktioniert der Member Count?

### Discord API: `guild.member_count`

Der Bot verwendet `guild.member_count` - ein Property, das **ohne Members Intent** verfügbar ist.

### Was wird gezählt?

**`guild.member_count` zählt ALLE Mitglieder:**
- ✅ Online Members
- ✅ Offline Members
- ✅ Idle/DND Members
- ✅ Bots
- ✅ Alle Status-Arten

**WICHTIG:** Dies ist die **GESAMTE** Server-Mitgliederzahl, nicht nur die momentan online sind!

### Warum brauchen wir kein Members Intent?

Discord stellt `guild.member_count` als **öffentliche Server-Statistik** bereit:
- Keine privilegierten Intents erforderlich
- Enthält nur die Zahl, keine individuellen Member-Daten
- Wird vom Discord-Server automatisch bereitgestellt

### Alternative: `guild.members` (NICHT verwendet)

Wir verwenden **NICHT** `guild.members` weil:
- ❌ Benötigt Members Intent (hoher RAM-Verbrauch)
- ❌ Cached nur sichtbare Members
- ❌ Kann unvollständig sein ohne Intent

### Wann wird der Member Count aktualisiert?

Der Member Count wird bei **jeder Discord-Donation** aktualisiert:

1. User spendet via Discord `/donate` Command
2. Bot ruft `guild.member_count` ab
3. `MemberCountUpdated` Event wird ins Event-Log geschrieben
4. Member Count wird im Snapshot gespeichert
5. Nächstes Level-Up nutzt diesen Count für Kostenberechnung

### Code-Locations:

**Donation Processing:**
```python
# services/donation/unified_donation_service.py:279
await self._update_member_count_if_needed(request.bot_instance)
```

**Member Count Abruf:**
```python
# services/donation/unified_donation_service.py:353
member_count = guild.member_count if guild.member_count else 1
```

**Event-Log Update:**
```python
# services/mech/progress_service.py:566-577
def update_member_count(self, member_count: int) -> None:
    evt = Event(
        type="MemberCountUpdated",
        payload={"member_count": max(0, member_count)}
    )
    append_event(evt)
    snap.last_user_count_sample = max(0, member_count)
```

### Verifizierung:

Um zu überprüfen ob Member Count Updates funktionieren:

1. **Event Log prüfen:**
   ```bash
   grep "MemberCountUpdated" config/progress/events.jsonl
   ```

2. **Snapshot prüfen:**
   ```bash
   cat config/progress/snapshots/main.json | grep last_user_count_sample
   ```

3. **Test mit Discord Donation:**
   - Spende via Discord `/donate` Command
   - Prüfe Event-Log für MemberCountUpdated Event
   - Member Count sollte die GESAMTE Server-Größe widerspiegeln

### Beispiel Event:

```json
{
  "seq": 3,
  "ts": "2025-11-09T15:57:08.164509+00:00",
  "type": "MemberCountUpdated",
  "mech_id": "main",
  "payload": {
    "member_count": 42
  }
}
```

## Zusammenfassung:

- ✅ **Online + Offline**: Zählt ALLE Mitglieder (nicht nur online)
- ✅ **Bots inklusive**: Bots werden mitgezählt
- ✅ **Kein Intent nötig**: Funktioniert ohne Members Intent
- ✅ **Auto-Update**: Bei jeder Discord-Donation aktualisiert
- ✅ **Event-Sourcing**: Wird im Event-Log protokolliert
