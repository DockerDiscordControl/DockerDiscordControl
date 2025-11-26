# Auto-Action System (AAS)

The Auto-Action System (AAS) is DDC's intelligent automation layer that monitors Discord channels for specific messages and automatically triggers Docker container actions. This enables fully automated game server updates, deployments, and notifications based on update bots like Steam DB, Discohook, or custom webhooks.

## Overview

```
Discord Message → AutoActionMonitor → AutomationService → Docker Action
       ↓                  ↓                  ↓                 ↓
   (Webhook/Bot)    (Listener Cog)    (Matching Logic)   (start/stop/restart)
```

### Key Features

- **Keyword Matching**: Trigger on specific words with AND/OR logic
- **Required Keywords**: Mandatory keywords that must ALL match (e.g., product name)
- **Regex Support**: Python regex patterns with ReDoS protection (500ms timeout)
- **Fuzzy Matching**: 85% similarity threshold for typo tolerance on keywords > 4 characters
- **Ignore Keywords**: Blacklist words that prevent triggering (e.g., "driver issue")
- **Source Filtering**: Whitelist specific User IDs, Usernames, or Webhooks only
- **Multi-Container Actions**: Apply actions to multiple containers per rule
- **Cooldown System**: Atomic per-container cooldowns to prevent spam
- **Protected Containers**: Global blacklist that AAS cannot touch

---

## Configuration

### Global Settings

Found in the Web UI under **Auto-Actions → Global Settings** tab.

| Setting | Default | Description |
|:--------|:--------|:------------|
| **System Enabled** | `true` | Master switch to enable/disable all auto-actions |
| **Global Cooldown** | `30` seconds | Minimum time between ANY auto-action execution |
| **Protected Containers** | `ddc, portainer` | Comma-separated list of containers AAS cannot control |
| **Audit Channel** | `(None)` | Discord channel for logging all AAS events |

### Rule Structure

Each rule consists of four sections:

#### 1. Basic Info
- **Name**: Human-readable identifier (max 100 characters)
- **Priority**: 1-100, higher executes first when multiple rules match (default: 10)
- **Enabled**: Toggle rule on/off without deleting

#### 2. Trigger Conditions

| Field | Required | Description |
|:------|:---------|:------------|
| **Monitored Channel ID(s)** | Yes | Discord Channel IDs to monitor (comma-separated) |
| **Required Keywords** | No | ALL must match (AND logic), e.g., product name like "Icarus" |
| **Trigger Keywords** | No | At least one must match based on Match Mode |
| **Match Mode** | - | `any` (OR) or `all` (AND) for trigger keywords |
| **Ignore Keywords** | No | If ANY of these are found, rule is blocked |
| **Regex Pattern** | No | Python regex, case-insensitive, multiline |
| **Allowed User IDs** | No | Whitelist specific users/bots by Discord ID |
| **Webhook Only** | No | Only trigger on webhook messages |

**Validation**: At least ONE of `required_keywords`, `keywords`, or `regex_pattern` must be defined.

#### 3. Action & Execution

| Field | Default | Description |
|:------|:--------|:------------|
| **Action Type** | - | `RESTART`, `STOP`, `START`, `NOTIFY`, `RECREATE` (MVP: same as RESTART) |
| **Target Containers** | - | One or more containers to apply the action to |
| **Delay** | `0` seconds | Wait time before executing (max 3600s / 1 hour) |
| **Feedback Channel** | Source channel | Where to send action notifications |
| **Silent** | `false` | Suppress feedback messages |

#### 4. Safety Settings

| Field | Default | Range | Description |
|:------|:--------|:------|:------------|
| **Cooldown** | `1440` min (24h) | 1-10080 min | Per-container cooldown after execution |
| **Only if Running** | `true` | - | Only execute if container is currently running |

---

## Matching Logic

The AutomationService (`services/automation/automation_service.py:116`) processes messages in this order:

```
1. Pre-Filter (Channel, User, Webhook) → Fast rejection
2. Regex Pattern (if defined) → 500ms timeout protection
3. Ignore Keywords → Blacklist check
4. Required Keywords → ALL must match (AND)
5. Trigger Keywords → Based on match_mode (any/all)
```

### Search Scope

By default, AAS searches both:
- **Message Content**: The text body of the message
- **Embeds**: Title, description, footer, and field values

All matching is **case-insensitive**.

### Fuzzy Matching

For keywords longer than 4 characters, AAS uses `difflib.SequenceMatcher` with an **85% similarity threshold**. This catches typos like:
- `update` matches `updat` or `updaet`
- `released` matches `releasd`

*Source: `services/automation/automation_service.py:187-194`*

---

## Safety Mechanisms

### Atomic Cooldown Locking

To prevent race conditions when multiple messages arrive simultaneously, AAS uses atomic check-and-set via `acquire_execution_lock()`:

```python
# services/automation/auto_action_state_service.py:155
with self._lock:
    # 1. Check cooldowns
    # 2. Immediately set cooldowns (ATOMIC)
    # 3. Return permission
```

If execution fails, cooldowns are released to allow immediate retry.

### ReDoS Protection

Regex patterns are executed in a separate thread with a **500ms timeout** to prevent catastrophic backtracking attacks:

```python
# services/automation/automation_service.py:132
matched = await asyncio.wait_for(
    asyncio.to_thread(self._safe_regex_search, pattern, text),
    timeout=0.5
)
```

Additionally, dangerous patterns like `(a+)+` are rejected at validation time.

### Protected Containers

Containers listed in `protected_containers` (global settings) can NEVER be controlled by AAS, regardless of rule configuration. Actions are logged as `SKIPPED` with reason "Protected container".

*Default: `ddc, portainer`*

---

## Execution History

All AAS executions are recorded to `config/auto_actions_state.json` with:
- Timestamp
- Rule ID and name
- Container name
- Action type
- Result: `SUCCESS`, `FAILED`, or `SKIPPED`
- Details (error message or skip reason)

History is persisted across restarts and limited to **100 entries per container**.

---

## API Endpoints

All endpoints require authentication (`@auth.login_required`).

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/api/automation/rules` | List all rules |
| `POST` | `/api/automation/rules` | Create new rule |
| `PUT` | `/api/automation/rules/<rule_id>` | Update existing rule |
| `DELETE` | `/api/automation/rules/<rule_id>` | Delete rule |
| `GET` | `/api/automation/settings` | Get global settings |
| `POST` | `/api/automation/settings` | Update global settings |
| `GET` | `/api/automation/history?limit=50` | Get execution history |
| `POST` | `/api/automation/test` | Dry-run test (no execution) |
| `GET` | `/api/automation/channels` | List available Discord channels |

*Source: `app/blueprints/automation_routes.py`*

---

## Discord Integration

### Message Listener

The `AutoActionMonitor` cog (`cogs/auto_action_monitor.py`) listens to ALL messages in guilds where the bot is present. It:

1. Ignores bot's own messages (loop protection)
2. Ignores DMs
3. Extracts embed content (title, description, footer, fields)
4. Builds `TriggerContext` object
5. Forwards to `AutomationService.process_message()`

### Auto-Action Button

In the container task management view, each container has a blue "Auto-Action" button. Clicking it shows:
- All rules targeting that container
- Rule status (enabled/disabled)
- Action type and keywords
- Cooldown and priority

*Source: `cogs/status_info_integration.py:1455`*

---

## Web UI

Access the AAS configuration via the Web Dashboard:
1. Click **"Auto-Actions"** in the navigation
2. Three tabs available:
   - **Rules**: View, create, edit, delete rules
   - **Execution History**: Recent triggers with results
   - **Global Settings**: Master switch, cooldowns, protected containers

### Rule Editor

The rule editor modal provides:
- Form validation before save
- Live keyword testing (dry run)
- Bootstrap tooltips explaining each field
- Container checkbox selection (only shows active containers)
- Feedback channel selection from configured status/control channels

---

## Example Use Case

**Scenario**: Automatically restart Icarus game server when Steam DB announces an update.

**Configuration**:
```
Rule Name: Icarus Update Watcher
Priority: 10

Trigger:
  - Channel ID: 123456789012345678 (Steam DB update channel)
  - Required Keywords: Icarus
  - Trigger Keywords: update, released, patch, hotfix
  - Match Mode: any (OR)
  - Ignore Keywords: driver, issue, rollback

Action:
  - Type: RESTART
  - Target: icarus-server
  - Delay: 30 seconds
  - Feedback Channel: (same as trigger)

Safety:
  - Cooldown: 1440 minutes (24 hours)
  - Only If Running: Yes
```

**Result**: When a message containing "Icarus" AND any of ("update", "released", "patch", "hotfix") appears in the monitored channel, the `icarus-server` container restarts after a 30-second delay. The rule won't fire again for 24 hours.

---

## External Service Integration (Zapier, IFTTT, n8n)

AAS can be triggered by **any external service** without exposing your Web UI to the internet. The secret: **Discord Webhooks as a secure relay**.

```
┌─────────────────────────────────────────────────────────────────┐
│                         INTERNET                                │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│  │ Zapier  │    │  IFTTT  │    │   n8n   │    │ GitHub  │      │
│  └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘      │
│       │              │              │              │            │
│       └──────────────┴──────────────┴──────────────┘            │
│                              │                                  │
│                              ▼                                  │
│                    Discord Webhook URL                          │
│                    (discord.com/api/...)                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                     YOUR LOCAL NETWORK                           │
│                                                                  │
│   Discord Bot ◄── reads messages ── Discord Channel             │
│        │                              (AAS Webhook Channel)      │
│        ▼                                                         │
│   AAS Monitor ── matches keywords ── Auto-Action Rule            │
│        │                                                         │
│        ▼                                                         │
│   Docker Action (restart/stop/start)                             │
│                                                                  │
│   Web UI stays LOCAL - never exposed to internet!                │
└──────────────────────────────────────────────────────────────────┘
```

### Why This Architecture?

| Aspect | Benefit |
|:-------|:--------|
| **Security** | Web UI never exposed; Discord handles authentication |
| **Audit Trail** | All triggers visible in Discord channel history |
| **No Port Forwarding** | Only outbound connections from your server |
| **Universal Compatibility** | Works with 5000+ Zapier apps, IFTTT services, etc. |

---

### Setup: Discord Webhook

1. **Create a dedicated channel** in your Discord server (e.g., `#automation-webhooks`)
2. **Channel Settings → Integrations → Webhooks → New Webhook**
3. Name it (e.g., "Zapier Automation") and copy the **Webhook URL**
4. **Important**: Keep this URL secret - anyone with it can post to your channel

### Setup: AAS Rule for Webhooks

```
Rule Name: External Automation Trigger
Priority: 10

Trigger:
  - Channel ID: [your #automation-webhooks channel ID]
  - Required Keywords: [unique identifier, e.g., "DEPLOY-MYAPP"]
  - Webhook Only: ✓ (checked - Advanced Options)

Action:
  - Type: RESTART
  - Target: my-app-container
  - Delay: 10 seconds

Safety:
  - Cooldown: 60 minutes
```

The **"Webhook Only"** checkbox (`cogs/auto_action_monitor.py:52`) ensures the rule only triggers from webhook messages, ignoring any human messages in the channel.

---

### Example: Zapier Integration

**Scenario**: Restart your app container when a new GitHub release is published.

#### Step 1: Zapier Zap Configuration

| Setting | Value |
|:--------|:------|
| **Trigger App** | GitHub |
| **Trigger Event** | New Release |
| **Repository** | `your-username/your-repo` |
| **Action App** | Discord |
| **Action Event** | Send Channel Message |
| **Webhook URL** | (paste your Discord webhook URL) |
| **Message** | `DEPLOY-MYAPP: New release {{tag_name}} published` |

#### Step 2: AAS Rule

```
Rule Name: GitHub Release Deploy
Trigger:
  - Channel: #automation-webhooks
  - Required Keywords: DEPLOY-MYAPP
  - Trigger Keywords: release, published
  - Webhook Only: ✓

Action:
  - Type: RESTART
  - Target: my-app
  - Delay: 30 seconds
```

**Result**: GitHub release → Zapier → Discord webhook → AAS → Container restart

---

### Example: IFTTT Integration

**Scenario**: Start your Minecraft server when you send a specific SMS.

#### Step 1: IFTTT Applet Configuration

| Setting | Value |
|:--------|:------|
| **If This (Trigger)** | Android SMS → New SMS received matches search |
| **Search Phrase** | `start minecraft` |
| **Then That (Action)** | Webhooks → Make a web request |
| **URL** | (your Discord webhook URL) |
| **Method** | POST |
| **Content Type** | application/json |
| **Body** | `{"content": "MINECRAFT-START: SMS trigger received"}` |

#### Step 2: AAS Rule

```
Rule Name: SMS Minecraft Starter
Trigger:
  - Channel: #automation-webhooks
  - Required Keywords: MINECRAFT-START
  - Webhook Only: ✓

Action:
  - Type: START
  - Target: minecraft-server
```

**Result**: SMS → IFTTT → Discord webhook → AAS → Container start

---

### Example: n8n / Home Assistant Integration

**Scenario**: Stop game servers when leaving home (via Home Assistant presence detection).

#### n8n Workflow

```
[Home Assistant Trigger: Person leaves home]
        │
        ▼
[Discord Node: Send Webhook Message]
  - Webhook URL: (your Discord webhook)
  - Content: "HOME-AWAY: User left home, shutting down servers"
        │
        ▼
[AAS picks up message and stops containers]
```

#### AAS Rule

```
Rule Name: Away Mode - Stop Servers
Trigger:
  - Channel: #automation-webhooks
  - Required Keywords: HOME-AWAY
  - Webhook Only: ✓

Action:
  - Type: STOP
  - Target: minecraft-server, valheim-server, icarus-server
```

---

### Best Practices for External Integrations

| Practice | Reason |
|:---------|:-------|
| **Use unique identifiers** | e.g., `DEPLOY-MYAPP`, `SMS-START` prevents false triggers |
| **Enable "Webhook Only"** | Ignores human messages, only responds to webhooks |
| **Dedicated channel** | Separate `#automation-webhooks` from regular channels |
| **Set appropriate cooldowns** | Prevent accidental spam (e.g., 60 min for deployments) |
| **Test with NOTIFY first** | Use `NOTIFY` action type before enabling `RESTART` |

### Supported External Services

Any service that can send HTTP POST to a Discord webhook works:

- **Zapier** (5000+ app integrations)
- **IFTTT** (SMS, email, smart home, location)
- **n8n** (self-hosted automation)
- **Home Assistant** (smart home events)
- **GitHub Actions** (CI/CD webhooks)
- **GitLab CI** (pipeline notifications)
- **Uptime Kuma** (monitoring alerts)
- **Grafana** (alerting)
- **Custom scripts** (`curl` to Discord webhook)

---

## File Structure

```
services/automation/
├── __init__.py                    # Module exports
├── automation_service.py          # Core matching & execution logic
├── auto_action_config_service.py  # Rule CRUD & validation
└── auto_action_state_service.py   # Cooldowns & history tracking

cogs/
├── auto_action_monitor.py         # Discord message listener

app/
├── blueprints/
│   └── automation_routes.py       # REST API endpoints
├── templates/
│   └── _auto_actions_modal.html   # Web UI modal
└── static/js/
    └── auto_actions.js            # Frontend logic

config/
├── auto_actions.json              # Rule definitions (persisted)
└── auto_actions_state.json        # Runtime state & history
```

---

## Validation Limits

These limits are enforced by `auto_action_config_service.py`:

| Parameter | Limit |
|:----------|:------|
| Rule name length | 100 characters |
| Keywords per rule | 50 |
| Keyword length | 100 characters |
| Regex pattern length | 500 characters |
| Priority | 1-100 |
| Cooldown | 1-10080 minutes (7 days) |
| Delay | 0-3600 seconds (1 hour) |
| History per container | 100 entries |
| API history limit | 1-500 entries |

---

## Quick Reference: curl Example

For developers who want to trigger AAS from scripts:

```bash
# Send a webhook message to trigger AAS
curl -X POST "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "DEPLOY-MYAPP: Manual deployment triggered"}'
```

This can be used in:
- CI/CD pipelines (GitHub Actions, GitLab CI, Jenkins)
- Cron jobs
- Custom monitoring scripts
- Any programming language with HTTP support

---

*Last updated: November 26, 2025*
