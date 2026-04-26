# Feature Plan: Auto-Action System (AAS) for Update Notifications

## 🎯 Vision
A generic, flexible system that allows DDC users to automatically trigger container actions when specific messages appear in monitored Discord channels. This system follows the **Service First** architecture and acts as a "Single Point of Truth" for automation rules.

## 📋 Use Cases

### Primary Use Case
- **Game Server Updates:** Monitor official game Discords (forwarded to local channel) → Auto-restart game server container upon "Update Released" message.
- **Maintenance Mode:** Detect "Maintenance" announcements → Stop container.
- **Event Start:** Detect "Servers Online" → Start container.

### Extended Use Cases
- **Recreate Container:** For updates requiring image pulls.
- **Notification Only:** Admin alerts without action.
- **Multiple containers:** One update triggers multiple servers (e.g., Cluster).
- **Chain Reactions:** Trigger secondary actions after primary completes (z.B. Backup → Stop → Pull → Start).
- **Version Tracking:** Extract version numbers from messages for logging/display.

## 🏗️ Architecture Design (Service First)

The implementation will strictly follow the Service First architecture pattern.

### 1. Data Layer (Single Point of Truth)
- **Config File:** `config/auto_actions.json`
- **Service:** `services/automation/auto_action_config_service.py`
    - Responsibilities: Load, Save, Validate, CRUD operations.
    - Ensures ID uniqueness and data integrity.

### 2. Logic Layer (The Brain)
- **Service:** `services/automation/automation_service.py`
    - **Core Logic:** `process_discord_message(message_obj)`
    - **Matching Engine:** Checks Channel ID, User ID/Source, Keywords, Regex.
    - **Safety Checks:** Validates Cooldowns and Constraints.
    - **Execution:** Orchestrates the action via `docker_control_service`.

### 3. Trigger Layer (Discord Interface)
- **Cog:** `cogs/auto_action_monitor.py`
    - **Role:** Passive Listener.
    - **Action:** Listens to `on_message`. Extracts data (Content, Author, Channel). Forwards to `AutomationService`.
    - **Constraint:** No business logic in Cog!

### 4. UI Layer (Web & Discord)
- **Web UI:** Integrated into the Main Dashboard (`/`) under "Tasks" section.
    - **Tab/Accordion:** "Auto-Actions (AAS)" next to "Scheduled Tasks".
    - **Management:** Add/Edit/Delete rules via Modal.
- **Discord UI:** "Show Tasks" command/view extended.
    - **Button:** `[📋 Show Auto-Actions]` added to task view.
    - **Display:** Shows active rules for the specific container.

---

## 🛠️ JSON Configuration Schema

```json
{
  "auto_actions": [
    {
      "id": "uuid-v4-example",
      "name": "Icarus Update Watcher",
      "enabled": true,
      "priority": 10,                           // Higher = checked first (for overlapping rules)

      "trigger": {
        "channel_ids": ["1442345023181164554"],
        "keywords": ["Update", "Patch", "Hotfix"],
        "ignore_keywords": ["Driver", "Issue"], // Optional: Prevent false positives
        "match_mode": "any",                    // "any" | "all"
        "regex_pattern": null,                  // Optional: Advanced matching (e.g., "v\\d+\\.\\d+")
        "search_in": ["content", "embeds"],     // Where to search: content, embeds, author_name
        "source_filter": {
          "allowed_user_ids": ["1442544645908201633"],
          "allowed_usernames": ["Enshrouded #patch-notes"],
          "is_webhook": null                    // true = only webhooks, false = only users, null = both
        }
      },

      "action": {
        "type": "RESTART",                      // RESTART, STOP, START, RECREATE, NOTIFY
        "containers": ["Icarus"],
        "delay_seconds": 0,
        "notification_channel_id": null,        // Override: Where to post feedback (null = source channel)
        "silent": false                         // true = no Discord feedback message
      },

      "safety": {
        "cooldown_minutes": 1440,
        "only_if_running": true,
        "only_if_stopped": false,               // For START actions
        "require_confirmation": false           // Future: Require admin approval before execution
      },

      "metadata": {
        "created_at": "2025-01-15T10:00:00Z",
        "last_triggered": null,
        "trigger_count": 0,
        "last_matched_message": null            // For debugging: snippet of last matched message
      }
    }
  ],

  "global_settings": {
    "enabled": true,                            // Master switch for all AAS
    "default_notification_channel": null,       // Fallback if not set per rule
    "global_cooldown_seconds": 30,              // Min time between ANY AAS execution
    "log_all_checks": false,                    // Debug mode: Log every message check
    "protected_containers": ["ddc"],            // Container die NICHT via AAS gesteuert werden dürfen
    "audit_channel_id": null,                   // Optional: Dedizierter Channel für AAS-Events
    "audit_level": "actions_only"               // "all" | "actions_only" | "errors_only"
  }
}
```

### Schema-Erklärungen

| Feld | Zweck |
|------|-------|
| `priority` | Bei mehreren matchenden Regeln wird die mit höchster Priorität ausgeführt |
| `search_in` | Wichtig! Discord-Bots senden oft **Embeds**, nicht plain text |
| `is_webhook` | Forwarding-Bots (wie Discohook) erscheinen als Webhooks |
| `metadata` | Wird automatisch vom System gepflegt, nicht vom User editiert |
| `global_cooldown_seconds` | Verhindert Spam bei vielen gleichzeitigen Triggern |

## 🎨 UI & UX Strategy

### Web UI (Main Dashboard)
The "Tasks" section will be split into two tabs:
1.  **Scheduled Tasks:** Existing Cron-based restarts.
2.  **Auto-Actions (AAS):** New Event-based rules.
    *   **Table:** Name, Trigger Summary, Action, Last Run.
    *   **Button:** `[+ Add Auto-Action]` opens a detailed configuration modal.

### Trigger Configuration (Modal)
- **Channel:** Input ID (e.g., `#tech-updates`).
- **Keywords:** Tag-Input for trigger words.
- **Source Validation:** Input for User ID (to strictly allow only the update bot).
- **Cooldown:** Default 24h (Slider/Input).

### Discord Feedback
- When AAS triggers:
    - Bot posts in the source channel (or control channel): "🤖 **AAS Triggered:** 'Icarus Update' detected. Restarting Icarus in 60s..."

---

## 🚀 Implementation Phases

### Phase 1: Core Backend
1.  **Scaffold:** Create `services/automation/` structure.
2.  **Config Service:** Implement `AutoActionConfigService` (JSON handling).
3.  **Logic Core:** Implement `AutomationService` (Matching & Execution).
4.  **Discord Hook:** Implement `AutoActionMonitor` Cog.
5.  **Embed Support:** Parse Embed title, description, fields for keyword matching.
6.  **Integration Test:** Manual test with dummy message.

### Phase 2: UI Integration
1.  **Web Backend:** Add routes for AAS CRUD (`services/web/blueprints/automation_routes.py`).
2.  **Web Frontend:** Update `index.html` to include AAS tab and forms.
3.  **Discord UI:** Update Task View with "Show AAS" button.
4.  **Test Mode Button:** "Test Rule" button that simulates a match without executing.

### Phase 3: Advanced Features (Future)
- "Recreate" Action (requires Docker Image Pull logic).
- Multi-Stage Actions (Backup → Update → Restart).
- Approval Workflow (Admin muss Aktion bestätigen bevor sie ausgeführt wird).
- Import/Export von Regeln (JSON download/upload).

---

## ⚠️ Edge Cases & Fehlerbehandlung

### Message Parsing
| Szenario | Lösung |
|----------|--------|
| Message hat nur Embeds, kein Content | `search_in: ["embeds"]` muss Embed-Title + Description + Fields durchsuchen |
| Webhook-Messages (z.B. von Discohook/MEE6) | `author.bot = true` UND `webhook_id` vorhanden → `is_webhook` Filter |
| Edited Messages | `on_message_edit` Event ebenfalls monitoren? (Opt-in per Regel) |
| Deleted Messages | Ignorieren - Action bereits getriggert oder nicht relevant |
| Bot's eigene Messages | **Immer ignorieren** um Loops zu verhindern |

### Execution Failures
| Szenario | Lösung |
|----------|--------|
| Container existiert nicht | Log Error + Discord-Nachricht "⚠️ AAS Failed: Container 'X' not found" |
| Docker API Timeout | Retry 1x nach 5s, dann Error-Notification |
| Container bereits im gewünschten State | Kein Error, aber Info-Log "Container already running, skipping" |
| Mehrere Regeln matchen gleichzeitig | Nur höchste Priorität ausführen, andere loggen als "skipped (lower priority)" |

### Safety
| Szenario | Lösung |
|----------|--------|
| Cooldown aktiv | Log: "Skipped: Cooldown active (X min remaining)" |
| `only_if_running` aber Container stopped | Skip + optional notification |
| Rapid-Fire Messages (Spam) | `global_cooldown_seconds` verhindert alle AAS für N Sekunden |

---

## 🔒 Security & Access Control

### 1. Berechtigungen (Access Control)

#### Web UI
| Aktion | Erforderliche Berechtigung |
|--------|---------------------------|
| AAS-Regeln anzeigen | Authentifiziert (Login) |
| Regel erstellen/bearbeiten | Authentifiziert (Login) |
| Regel löschen | Authentifiziert (Login) |
| Global Settings ändern | Authentifiziert (Login) |

> **Hinweis:** DDC hat derzeit ein Single-User-Konzept. Falls Multi-User geplant ist, sollte ein Role-System (Admin/Operator/Viewer) eingeführt werden.

#### Discord Commands (falls implementiert)
| Aktion | Erforderlich |
|--------|-------------|
| AAS-Status anzeigen | Definierte `ALLOWED_USER_IDS` |
| Regel aktivieren/deaktivieren | Definierte `ALLOWED_USER_IDS` |
| Regel erstellen via Discord | **Nicht implementieren** - zu komplex, Web UI nutzen |

### 2. Input Validation

| Feld | Validierung |
|------|-------------|
| `name` | Max 100 Zeichen, keine HTML/Script-Tags, alphanumerisch + Leerzeichen |
| `channel_ids` | Muss gültige Discord Snowflake IDs sein (17-19 Ziffern) |
| `keywords` | Max 50 Keywords, je max 100 Zeichen |
| `regex_pattern` | Regex-Syntax validieren, Timeout bei Ausführung (max 100ms) |
| `containers` | Gegen existierende Container-Liste validieren bei Speichern |
| `delay_seconds` | 0-3600 (max 1 Stunde) |
| `cooldown_minutes` | 1-10080 (1 Minute bis 7 Tage) |

#### Regex-Sicherheit (ReDoS Prevention)
```python
# Beispiel: Sichere Regex-Ausführung mit Timeout
import re
import signal

def safe_regex_match(pattern, text, timeout_ms=100):
    """Führt Regex mit Timeout aus um ReDoS zu verhindern."""
    # Implementation mit Threading/Signal-Timeout
    pass
```

### 3. Container-Schutz

#### Blacklist für kritische Container
```json
{
  "global_settings": {
    "protected_containers": ["ddc", "portainer", "traefik"],
    "allow_protected_override": false
  }
}
```

| Container | Grund für Schutz |
|-----------|-----------------|
| `ddc` | Selbst-Stopp würde AAS deaktivieren |
| `portainer` | Management-Tool |
| `traefik` / `nginx-proxy` | Netzwerk-Infrastruktur |

> **Empfehlung:** Warning bei Versuch, geschützte Container in Regel aufzunehmen. Override nur mit expliziter Bestätigung.

### 4. Channel-Validierung

**Problem:** User könnte Channel-ID eingeben, die der Bot nicht lesen kann.

**Lösung:**
```python
async def validate_channel_access(channel_id: str) -> tuple[bool, str]:
    """Prüft ob Bot den Channel lesen kann."""
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return False, "Channel nicht gefunden oder Bot hat keinen Zugriff"

    permissions = channel.permissions_for(channel.guild.me)
    if not permissions.read_messages:
        return False, "Bot hat keine Leserechte in diesem Channel"

    return True, "OK"
```

- Bei Regel-Speicherung: Validierung durchführen, Warning anzeigen wenn fehlgeschlagen
- Regel trotzdem speichern erlauben (Channel könnte später verfügbar werden)

### 5. Abuse Prevention

| Risiko | Mitigation |
|--------|-----------|
| Spam-Trigger (viele Messages in kurzer Zeit) | `global_cooldown_seconds` (Standard: 30s) |
| Selbst-Trigger (Bot reagiert auf eigene Messages) | Immer `message.author.id != bot.user.id` prüfen |
| Cross-Rule Cascade (Regel A triggert Regel B) | AAS-Feedback-Messages von Matching ausschließen |
| Regex-Bomb (komplexe Regex blockiert System) | Timeout + Komplexitäts-Check |
| Unauthorized Rule Creation | Web UI Login erforderlich |

### 6. Audit Trail für Konfigurationsänderungen

Jede Änderung an AAS-Regeln wird geloggt:

```json
{
  "audit_log": [
    {
      "timestamp": "2025-01-15T10:30:00Z",
      "action": "RULE_CREATED",
      "rule_id": "uuid-xyz",
      "rule_name": "Icarus Update",
      "source": "web_ui",
      "ip_address": "192.168.1.100",
      "details": { "containers": ["Icarus"], "action_type": "RESTART" }
    },
    {
      "timestamp": "2025-01-15T11:00:00Z",
      "action": "RULE_MODIFIED",
      "rule_id": "uuid-xyz",
      "changes": { "cooldown_minutes": { "old": 1440, "new": 720 } }
    }
  ]
}
```

---

## 📊 Logging & Monitoring

### Log-Kategorien und Levels

| Kategorie | Level | Beispiel |
|-----------|-------|----------|
| **AAS.Match** | INFO | Rule matched message |
| **AAS.Execute** | INFO | Executing action |
| **AAS.Skip** | DEBUG | Skipped due to cooldown |
| **AAS.Error** | ERROR | Container not found |
| **AAS.Config** | INFO | Rule created/modified/deleted |
| **AAS.Security** | WARNING | Validation failed, protected container |

### Strukturiertes Log-Format

```python
# Integration mit bestehendem logging_utils.py
logger.info(
    "AAS rule matched",
    extra={
        "component": "AAS",
        "event": "MATCH",
        "rule_id": "uuid-xyz",
        "rule_name": "Icarus Update",
        "channel_id": "123456789",
        "message_snippet": "Update 1.2.3 released...",
        "matched_keywords": ["Update"],
    }
)
```

### Execution Log Events
```
[AAS] Rule 'Icarus Update' matched message in #patch-notes
[AAS] ├─ Keywords matched: ['Update']
[AAS] ├─ Source validated: Bot 'Enshrouded #patch-notes' (ID: 123456)
[AAS] └─ Executing RESTART on container 'Icarus' (delay: 0s)
[AAS] Action completed successfully (duration: 2.3s)

[AAS] Rule 'Icarus Update' checked but skipped
[AAS] └─ Reason: Cooldown active (23h 15m remaining)

[AAS] Rule 'Backup Trigger' checked but skipped
[AAS] └─ Reason: Container 'Backup' is not running (only_if_running=true)

[AAS] ⚠️ Rule 'Test Rule' execution FAILED
[AAS] └─ Error: Container 'NonExistent' not found
```

### Discord Audit Channel (Optional)

```json
{
  "global_settings": {
    "audit_channel_id": "123456789",  // Dedizierter Channel für alle AAS-Events
    "audit_level": "all"              // "all" | "actions_only" | "errors_only"
  }
}
```

**Audit Channel Messages:**
- `✅ [AAS] Restarted 'Icarus' (triggered by: Icarus Update rule)`
- `⏭️ [AAS] Skipped 'Valheim Restart' - cooldown active`
- `❌ [AAS] Failed to stop 'Unknown' - container not found`

### Web UI - History View (Phase 2+)
- Tabelle mit letzten 50 AAS-Events
- Spalten: Timestamp, Rule Name, Trigger Message (snippet), Action, Result (✅/❌)
- Filter: By Rule, By Container, By Result
- **Export:** CSV/JSON Download für Analyse

### Log Retention
| Log-Typ | Retention |
|---------|-----------|
| Execution Logs | 30 Tage (in `auto_actions_history.json`) |
| Config Audit Log | 90 Tage |
| Debug Logs | 7 Tage (nur bei `log_all_checks: true`) |

---

## 🧪 Testing-Strategie

### Unit Tests
- `test_auto_action_config_service.py`: CRUD, Validation, ID-Uniqueness
- `test_automation_service.py`: Keyword matching, Regex matching, Cooldown logic

### Integration Tests
- Mock Discord Message → Verify correct action triggered
- Mock Docker API → Verify correct commands sent

### Manual Testing Checklist
- [ ] Regel erstellen via Web UI
- [ ] Regel editieren via Web UI
- [ ] Regel löschen via Web UI
- [ ] Trigger mit Keyword in message.content
- [ ] Trigger mit Keyword in Embed
- [ ] Trigger von Webhook-Source
- [ ] Cooldown verhindert Re-Trigger
- [ ] Multiple Container Action
- [ ] "Test Rule" Button funktioniert
- [ ] AAS-History zeigt Events korrekt

---

## 🔄 Message Flow Diagramm

```
Discord Message
      │
      ▼
┌─────────────────────┐
│ AutoActionMonitor   │  (Cog - Passive Listener)
│ on_message event    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ AutomationService   │  (Logic Layer)
│ process_message()   │
│  ├─ Is AAS enabled? │
│  ├─ Is own message? │──→ SKIP (prevent loops)
│  ├─ Load rules      │
│  ├─ For each rule:  │
│  │   ├─ Channel?    │
│  │   ├─ Source?     │
│  │   ├─ Keywords?   │
│  │   ├─ Cooldown?   │
│  │   └─ Container?  │
│  └─ Execute match   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ DockerControlService│  (Existing)
│ restart_container() │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Discord Feedback    │
│ "🤖 AAS Triggered"  │
└─────────────────────┘
```

---

## 🤔 Offene Fragen / Entscheidungen

1. **Regex in Phase 1 oder 2?**
   - Pro Phase 1: Viele Update-Bots haben strukturierte Messages ("Version 1.2.3")
   - Contra: Erhöht Komplexität, Keywords reichen für MVP

2. **Notification Channel Strategy**
   - Option A: Immer im Source-Channel antworten
   - Option B: Dedizierter AAS-Log-Channel (konfigurierbar)
   - Option C: Beides (per-rule override)
   - **Empfehlung:** Option C - flexibel für verschiedene Setups

3. **Container-Name vs Container-ID**
   - Container-Namen können sich ändern (Docker recreate)
   - IDs sind stabil aber user-unfreundlich
   - **Empfehlung:** Namen verwenden, bei nicht-gefunden Fehler werfen

4. **Edit-Events monitoren?**
   - Manche Bots editieren Announcements nachträglich
   - Risiko: Doppel-Trigger wenn Edit Keywords enthält
   - **Empfehlung:** Opt-in per Regel, default OFF

5. **Persistenz der Metadata**
   - Im gleichen `auto_actions.json` speichern?
   - Separates `auto_actions_state.json`?
   - **Empfehlung:** Separates State-File für cleane Trennung

6. **Protected Containers - Hardcoded oder Konfigurierbar?**
   - Option A: DDC immer hardcoded schützen, Rest konfigurierbar
   - Option B: Alles konfigurierbar (User-Verantwortung)
   - **Empfehlung:** Option A - DDC-Selbstschutz ist kritisch

7. **Audit Log Storage**
   - Option A: Eigene JSON-Datei (`config/aas_audit.json`)
   - Option B: In bestehenden `AuditLogService` integrieren
   - Option C: Beides (strukturiert in JSON + menschenlesbar in bestehenden Logs)
   - **Empfehlung:** Option C - maximale Flexibilität

8. **Rate Limiting bei Validation-Checks**
   - Soll jede Discord-Message gegen alle Regeln geprüft werden?
   - Bei 100 Regeln und aktivem Channel = Performance-Problem
   - **Empfehlung:** Channel-ID Index für O(1) Lookup statt O(n) Iteration

---

## 📁 Datei-Struktur (Übersicht)

```
config/
├── auto_actions.json          # Regel-Definitionen (User-editierbar)
├── auto_actions_state.json    # Runtime-State (last_triggered, counts)
└── auto_actions_audit.json    # Config-Änderungshistorie

services/
└── automation/
    ├── __init__.py
    ├── auto_action_config_service.py   # CRUD für Regeln
    ├── auto_action_state_service.py    # State-Management (Cooldowns, Counts)
    └── automation_service.py           # Matching-Engine + Execution

cogs/
└── auto_action_monitor.py     # Discord Event Listener
```

---

**Status:** 🟢 Ready for Implementation
**Architecture:** Service First, Single Process
**Next Step:** Phase 1 Implementation - Core Backend