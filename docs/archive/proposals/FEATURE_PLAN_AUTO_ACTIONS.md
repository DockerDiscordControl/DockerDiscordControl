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
- **Chain Reactions:** Trigger secondary actions after primary completes (e.g. Backup → Stop → Pull → Start).
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
    "protected_containers": ["ddc"],            // Containers that must NOT be controlled via AAS
    "audit_channel_id": null,                   // Optional: dedicated channel for AAS events
    "audit_level": "actions_only"               // "all" | "actions_only" | "errors_only"
  }
}
```

### Schema explanations

| Field | Purpose |
|------|-------|
| `priority` | When several rules match, the one with the highest priority is executed |
| `search_in` | Important! Discord bots often send **embeds**, not plain text |
| `is_webhook` | Forwarding bots (such as Discohook) appear as webhooks |
| `metadata` | Maintained automatically by the system, not edited by the user |
| `global_cooldown_seconds` | Prevents spam when many triggers fire at the same time |

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
- Approval Workflow (admin must confirm the action before it is executed).
- Import/Export of rules (JSON download/upload).

---

## ⚠️ Edge Cases & Error Handling

### Message Parsing
| Scenario | Solution |
|----------|--------|
| Message has only embeds, no content | `search_in: ["embeds"]` must search embed title + description + fields |
| Webhook messages (e.g. from Discohook/MEE6) | `author.bot = true` AND `webhook_id` present → `is_webhook` filter |
| Edited Messages | Monitor the `on_message_edit` event as well? (opt-in per rule) |
| Deleted Messages | Ignore - action already triggered or not relevant |
| Bot's own messages | **Always ignore** to prevent loops |

### Execution Failures
| Scenario | Solution |
|----------|--------|
| Container does not exist | Log error + Discord message "⚠️ AAS Failed: Container 'X' not found" |
| Docker API Timeout | Retry 1x after 5s, then error notification |
| Container already in the desired state | No error, but info log "Container already running, skipping" |
| Several rules match at the same time | Execute only the highest priority, log the others as "skipped (lower priority)" |

### Safety
| Scenario | Solution |
|----------|--------|
| Cooldown active | Log: "Skipped: Cooldown active (X min remaining)" |
| `only_if_running` but container stopped | Skip + optional notification |
| Rapid-Fire Messages (Spam) | `global_cooldown_seconds` blocks all AAS for N seconds |

---

## 🔒 Security & Access Control

### 1. Permissions (Access Control)

#### Web UI
| Action | Required permission |
|--------|---------------------------|
| View AAS rules | Authenticated (login) |
| Create/edit rule | Authenticated (login) |
| Delete rule | Authenticated (login) |
| Change global settings | Authenticated (login) |

> **Note:** DDC currently has a single-user concept. If multi-user is planned, a role system (Admin/Operator/Viewer) should be introduced.

#### Discord Commands (if implemented)
| Action | Required |
|--------|-------------|
| Show AAS status | Defined `ALLOWED_USER_IDS` |
| Enable/disable rule | Defined `ALLOWED_USER_IDS` |
| Create rule via Discord | **Do not implement** - too complex, use the Web UI |

### 2. Input Validation

| Field | Validation |
|------|-------------|
| `name` | Max 100 characters, no HTML/script tags, alphanumeric + spaces |
| `channel_ids` | Must be valid Discord snowflake IDs (17-19 digits) |
| `keywords` | Max 50 keywords, each max 100 characters |
| `regex_pattern` | Validate regex syntax, timeout on execution (max 100ms) |
| `containers` | Validate against the existing container list on save |
| `delay_seconds` | 0-3600 (max 1 hour) |
| `cooldown_minutes` | 1-10080 (1 minute to 7 days) |

#### Regex safety (ReDoS Prevention)
```python
# Example: safe regex execution with timeout
import re
import signal

def safe_regex_match(pattern, text, timeout_ms=100):
    """Runs a regex with a timeout to prevent ReDoS."""
    # Implementation with threading/signal timeout
    pass
```

### 3. Container protection

#### Blacklist for critical containers
```json
{
  "global_settings": {
    "protected_containers": ["ddc", "portainer", "traefik"],
    "allow_protected_override": false
  }
}
```

| Container | Reason for protection |
|-----------|-----------------|
| `ddc` | Stopping itself would disable AAS |
| `portainer` | Management tool |
| `traefik` / `nginx-proxy` | Network infrastructure |

> **Recommendation:** Warning when trying to add protected containers to a rule. Override only with explicit confirmation.

### 4. Channel validation

**Problem:** A user could enter a channel ID that the bot cannot read.

**Solution:**
```python
async def validate_channel_access(channel_id: str) -> tuple[bool, str]:
    """Checks whether the bot can read the channel."""
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return False, "Channel not found or bot has no access"

    permissions = channel.permissions_for(channel.guild.me)
    if not permissions.read_messages:
        return False, "Bot has no read permission in this channel"

    return True, "OK"
```

- On saving a rule: run the validation, show a warning if it failed
- Still allow saving the rule (the channel could become available later)

### 5. Abuse Prevention

| Risk | Mitigation |
|--------|-----------|
| Spam trigger (many messages in a short time) | `global_cooldown_seconds` (default: 30s) |
| Self-trigger (bot reacts to its own messages) | Always check `message.author.id != bot.user.id` |
| Cross-rule cascade (rule A triggers rule B) | Exclude AAS feedback messages from matching |
| Regex bomb (complex regex blocks the system) | Timeout + complexity check |
| Unauthorized Rule Creation | Web UI login required |

### 6. Audit trail for configuration changes

Every change to AAS rules is logged:

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

### Log categories and levels

| Category | Level | Example |
|-----------|-------|----------|
| **AAS.Match** | INFO | Rule matched message |
| **AAS.Execute** | INFO | Executing action |
| **AAS.Skip** | DEBUG | Skipped due to cooldown |
| **AAS.Error** | ERROR | Container not found |
| **AAS.Config** | INFO | Rule created/modified/deleted |
| **AAS.Security** | WARNING | Validation failed, protected container |

### Structured log format

```python
# Integration with the existing logging_utils.py
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
    "audit_channel_id": "123456789",  // Dedicated channel for all AAS events
    "audit_level": "all"              // "all" | "actions_only" | "errors_only"
  }
}
```

**Audit Channel Messages:**
- `✅ [AAS] Restarted 'Icarus' (triggered by: Icarus Update rule)`
- `⏭️ [AAS] Skipped 'Valheim Restart' - cooldown active`
- `❌ [AAS] Failed to stop 'Unknown' - container not found`

### Web UI - History View (Phase 2+)
- Table with the last 50 AAS events
- Spalten: Timestamp, Rule Name, Trigger Message (snippet), Action, Result (✅/❌)
- Filter: By Rule, By Container, By Result
- **Export:** CSV/JSON download for analysis

### Log Retention
| Log type | Retention |
|---------|-----------|
| Execution Logs | 30 days (in `auto_actions_history.json`) |
| Config Audit Log | 90 days |
| Debug Logs | 7 days (only with `log_all_checks: true`) |

---

## 🧪 Testing Strategy

### Unit Tests
- `test_auto_action_config_service.py`: CRUD, Validation, ID-Uniqueness
- `test_automation_service.py`: Keyword matching, Regex matching, Cooldown logic

### Integration Tests
- Mock Discord Message → Verify correct action triggered
- Mock Docker API → Verify correct commands sent

### Manual Testing Checklist
- [ ] Create rule via Web UI
- [ ] Edit rule via Web UI
- [ ] Delete rule via Web UI
- [ ] Trigger with keyword in message.content
- [ ] Trigger with keyword in embed
- [ ] Trigger from webhook source
- [ ] Cooldown prevents re-trigger
- [ ] Multiple Container Action
- [ ] "Test Rule" button works
- [ ] AAS history shows events correctly

---

## 🔄 Message Flow Diagram

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

## 🤔 Open Questions / Decisions

1. **Regex in Phase 1 or 2?**
   - Pro Phase 1: many update bots have structured messages ("Version 1.2.3")
   - Contra: increases complexity, keywords are enough for the MVP

2. **Notification Channel Strategy**
   - Option A: always reply in the source channel
   - Option B: dedicated AAS log channel (configurable)
   - Option C: both (per-rule override)
   - **Recommendation:** Option C - flexible for different setups

3. **Container-Name vs Container-ID**
   - Container names can change (Docker recreate)
   - IDs are stable but user-unfriendly
   - **Recommendation:** use names, raise an error if not found

4. **Monitor edit events?**
   - Some bots edit announcements afterwards
   - Risk: double trigger if the edit contains keywords
   - **Recommendation:** opt-in per rule, default OFF

5. **Persistence of the metadata**
   - Store in the same `auto_actions.json`?
   - Separate `auto_actions_state.json`?
   - **Recommendation:** separate state file for a clean separation

6. **Protected Containers - hardcoded or configurable?**
   - Option A: always protect DDC hardcoded, the rest configurable
   - Option B: everything configurable (user responsibility)
   - **Recommendation:** Option A - DDC self-protection is critical

7. **Audit Log Storage**
   - Option A: own JSON file (`config/aas_audit.json`)
   - Option B: integrate into the existing `AuditLogService`
   - Option C: both (structured in JSON + human-readable in the existing logs)
   - **Recommendation:** Option C - maximum flexibility

8. **Rate limiting for validation checks**
   - Should every Discord message be checked against all rules?
   - With 100 rules and an active channel = performance problem
   - **Recommendation:** channel ID index for O(1) lookup instead of O(n) iteration

---

## 📁 File Structure (Overview)

```
config/
├── auto_actions.json          # Rule definitions (user-editable)
├── auto_actions_state.json    # Runtime state (last_triggered, counts)
└── auto_actions_audit.json    # Config change history

services/
└── automation/
    ├── __init__.py
    ├── auto_action_config_service.py   # CRUD for rules
    ├── auto_action_state_service.py    # State management (cooldowns, counts)
    └── automation_service.py           # Matching engine + execution

cogs/
└── auto_action_monitor.py     # Discord Event Listener
```

---

**Status:** 🟢 Ready for Implementation
**Architecture:** Service First, Single Process
**Next Step:** Phase 1 Implementation - Core Backend