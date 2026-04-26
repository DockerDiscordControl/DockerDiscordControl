# Feature Request: Auto-Action System for Update Notifications

## 💡 Concept

A generic, flexible system that allows DDC users to automatically trigger container actions when specific messages appear in monitored Discord channels.

## 🎯 Use Case Example

**Scenario:**
1. User has Discord server with channel `#tech-updates`
2. User subscribes to Icarus Discord's announcement channel (auto-forwarded to `#tech-updates`)
3. When Icarus posts weekly update → Message appears in `#tech-updates`
4. DDC bot reads message → Detects keyword "update" → Automatically restarts Icarus container

**This should work for ANY application/service with Discord update notifications!**

## 📋 Common Use Cases

- **Game Servers:** Monitor game Discord → Auto-restart on updates
- **Media Servers:** Plex/Jellyfin announcements → Restart container
- **Application Updates:** Any app with Discord notifications → Auto-action
- **Custom Services:** Flexible enough for any scenario

## 🏗️ Proposed Architecture

### Configuration Structure

Each auto-action is independently configurable:

```json
{
  "auto_actions": [
    {
      "id": "icarus_auto_update",
      "enabled": true,
      "name": "Icarus Auto-Update",
      "description": "Automatically restart Icarus when updates are posted",

      "trigger": {
        "channel_id": "1234567890",
        "keywords": ["update", "released", "v\\d+\\.\\d+\\.\\d+"],
        "match_mode": "any",  // "any" | "all" | "regex"
        "case_sensitive": false,
        "source_restriction": {
          "enabled": true,
          "allowed_servers": ["987654321"],
          "allowed_channels": ["announcement_channel_id"],
          "allowed_users": []
        }
      },

      "action": {
        "type": "restart_container",  // "restart" | "stop" | "start" | "recreate" | "notification_only"
        "containers": ["icarus-server"],
        "mode": "delayed",  // "immediate" | "delayed" | "confirmation"

        "delay_config": {
          "delay_seconds": 60,
          "allow_cancel": true,
          "cancel_timeout": 60
        },

        "confirmation_config": {
          "require_admin": true,
          "timeout_seconds": 300,
          "auto_proceed_on_timeout": false
        }
      },

      "safety": {
        "cooldown_seconds": 3600,
        "max_triggers_per_day": 5,
        "only_if_running": true,
        "backup_before_action": false
      },

      "notifications": {
        "notify_on_trigger": true,
        "notify_on_action": true,
        "notify_on_error": true,
        "notification_channels": ["admin_channel_id"],
        "mention_roles": ["@Admin"]
      },

      "logging": {
        "log_all_matches": true,
        "log_channel": "log_channel_id"
      }
    }
  ]
}
```

## 🎨 Key Features

### 1. Flexible Trigger System
- **Channel Monitoring:** Monitor any Discord channel for messages
- **Keyword Detection:** Configurable keywords with multiple match modes
- **Match Modes:**
  - `ANY`: Match if any keyword found
  - `ALL`: Match only if all keywords found
  - `REGEX`: Full regex pattern matching
- **Source Restrictions:** Only trigger from specific servers/channels/users

### 2. Multiple Action Types
- **Container Actions:** restart, stop, start, recreate
- **Notification Only:** Just notify admins without action
- **Multi-Container:** Trigger multiple containers at once

### 3. Execution Modes

#### Immediate Mode
```
Trigger detected → Execute action immediately
Risk: High | Speed: Fast | Control: None
```

#### Delayed Mode with Cancel
```
Trigger detected →
  ↓
Post: "🔄 Restarting icarus-server in 60s [❌ Cancel]"
  ↓
Wait 60 seconds (cancellable)
  ↓
Execute action
Risk: Medium | Speed: Medium | Control: User can cancel
```

#### Confirmation Mode
```
Trigger detected →
  ↓
Post: "🔔 Update detected: v2.3.0
      [✅ Restart Now] [❌ Ignore] [⏰ Remind 1h]"
  ↓
Wait for user confirmation
  ↓
Execute if confirmed
Risk: Low | Speed: Slow | Control: Full user control
```

#### Notification Only Mode
```
Trigger detected →
  ↓
Post notification
  ↓
No automatic action
Risk: None | Speed: N/A | Control: Full manual
```

### 4. Safety Mechanisms

**Rate Limiting:**
- Cooldown period between triggers (e.g., min 1 hour)
- Daily trigger limits (e.g., max 5 per day)

**Validation:**
- Verify message source (server/channel/user)
- Check container exists and is running (if `only_if_running=true`)
- Error handling with retry logic

**Manual Override:**
- Admins can disable auto-actions anytime
- Cancel pending delayed actions
- Reset cooldowns/daily limits

### 5. Web UI Configuration

**Management Page:** `/admin/auto-actions`

```
┌─────────────────────────────────────────────────────┐
│ Auto-Actions Management                             │
├─────────────────────────────────────────────────────┤
│                                                      │
│ [+ Add New Auto-Action]                             │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ✅ Icarus Auto-Update              [Edit] [🗑️]  │ │
│ │ Monitors: #tech-updates                         │ │
│ │ Action: Restart icarus-server (60s delay)       │ │
│ │ Last triggered: 2 hours ago ✅ Success          │ │
│ │ Triggers today: 1/5                             │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
└─────────────────────────────────────────────────────┘
```

**Configuration Form Sections:**
1. Basic Info (name, description, enabled)
2. Trigger Configuration (channel, keywords, match mode)
3. Action Configuration (type, containers, execution mode)
4. Safety Settings (cooldown, limits)
5. Notifications (channels, mentions)
6. Logging (options, log channel)

## 📊 Logging & Monitoring

**Event Log Format:**
```json
{
  "timestamp": "2025-11-22T15:30:00Z",
  "auto_action_id": "icarus_auto_update",
  "event_type": "trigger_detected",
  "trigger_message": {
    "channel_id": "1234567890",
    "message_id": "9876543210",
    "content": "🚀 Icarus v2.3.0 Update Released!",
    "author": "Icarus Bot",
    "server": "Icarus Discord"
  },
  "keyword_matched": ["update", "released", "v2.3.0"],
  "action_taken": true,
  "result": "success"
}
```

**Dashboard Metrics:**
- Total triggers per auto-action
- Success/failure rates
- Average delay before action
- Cancellation rates
- Cooldown hits

## 🤔 Open Questions & Design Decisions Needed

### 1. Message History on Startup
**Question:** Should the bot scan message history when starting up?

**Options:**
- **A) Scan history:** Catch updates posted while bot was offline
  - Pro: Don't miss updates
  - Con: Could trigger old updates on restart
- **B) Only new messages:** Only monitor messages after bot starts
  - Pro: No false triggers from old messages
  - Con: Miss updates posted while offline

**Recommendation:** ?

### 2. Forwarded Messages Detection
**Question:** How to detect original source for Discord forwarded messages?

Discord's message forwarding/subscription system forwards messages from one channel to another. How do we determine the original source?

**Challenges:**
- Forwarded messages show in subscribed channel
- Original server/channel info may not be in message metadata
- Need to verify message actually came from trusted source

**Possible Solutions:**
- Parse message content for original author/source
- Use embed data if available
- Trust the subscription channel itself

**Recommendation:** ?

### 3. Multiple Triggers on Same Message
**Question:** What if multiple auto-actions match the same message?

**Example:**
- Auto-Action 1: Restart "icarus-server" on keyword "update"
- Auto-Action 2: Restart "icarus-mods" on keyword "released"
- Message: "Icarus update v2.3.0 released!"

**Options:**
- **A) Execute all:** Run all matching auto-actions
  - Pro: Full flexibility
  - Con: Could cause too many actions
- **B) Execute first only:** First match wins
  - Pro: Predictable behavior
  - Con: Need manual ordering
- **C) Priority system:** User defines priority for each auto-action
  - Pro: Full control
  - Con: More complex configuration

**Recommendation:** ?

### 4. Container Groups
**Question:** Should we support container groups for batch operations?

**Example:**
```json
{
  "container_groups": {
    "all-game-servers": ["icarus", "valheim", "minecraft"],
    "production-stack": ["web", "api", "database"]
  }
}
```

Then auto-action can target: `"containers": ["@all-game-servers"]`

**Recommendation:** Nice-to-have or MVP feature?

### 5. Webhook Support
**Question:** Should we support external webhook triggers (beyond Discord messages)?

**Use Cases:**
- GitHub release webhooks
- External monitoring tools
- CI/CD pipelines

**Recommendation:** Future feature or include in MVP?

### 6. MVP Scope
**Question:** What MUST be in v1.0, what can wait?

**Proposed MVP:**
- ✅ Basic trigger system (channel + keywords)
- ✅ Simple match mode (ANY keywords)
- ✅ Container restart action
- ✅ Delayed mode with cancel
- ✅ Basic cooldown
- ✅ Web UI for configuration

**Future (v2.0+):**
- ⏳ Regex matching
- ⏳ Multiple containers per action
- ⏳ Container groups
- ⏳ Webhook support
- ⏳ Backup before action
- ⏳ Advanced notification customization

**Recommendation:** ?

## 🔧 Implementation Phases

### Phase 1: Core Infrastructure
1. Config schema definition
2. Config service (load/save/validate)
3. Trigger detection (on_message handler)
4. Action executor (container actions)

### Phase 2: Safety & Control
1. Cooldown system
2. Source validation
3. Delayed actions with cancel
4. Confirmation mode

### Phase 3: Web UI
1. List view (all auto-actions)
2. Add/Edit form
3. Status dashboard
4. Manual controls

### Phase 4: Advanced Features
1. Regex support
2. Multiple containers
3. Notification customization
4. Backup integration

## 📝 Example Configurations

### Simple Auto-Restart
```json
{
  "name": "Simple Icarus Restart",
  "trigger": {
    "channel_id": "tech-updates",
    "keywords": ["update"],
    "match_mode": "any"
  },
  "action": {
    "type": "restart_container",
    "containers": ["icarus-server"],
    "mode": "immediate"
  },
  "safety": {
    "cooldown_seconds": 3600
  }
}
```

### Delayed with Cancel Button
```json
{
  "name": "Delayed Icarus Restart",
  "trigger": {
    "channel_id": "tech-updates",
    "keywords": ["v\\d+\\.\\d+\\.\\d+", "released"],
    "match_mode": "all"
  },
  "action": {
    "type": "restart_container",
    "containers": ["icarus-server"],
    "mode": "delayed",
    "delay_config": {
      "delay_seconds": 300,
      "allow_cancel": true
    }
  },
  "safety": {
    "cooldown_seconds": 7200,
    "only_if_running": true
  }
}
```

### Notification Only
```json
{
  "name": "Plex Update Notification",
  "trigger": {
    "channel_id": "plex-announcements",
    "keywords": ["plex", "update"],
    "match_mode": "all"
  },
  "action": {
    "type": "notification_only"
  },
  "notifications": {
    "notify_on_trigger": true,
    "notification_channels": ["admin-channel"],
    "mention_roles": ["@Admin"]
  }
}
```

## 🎯 Benefits

1. **Automation:** Reduce manual work for regular updates
2. **Flexibility:** Works with any service that posts Discord updates
3. **Safety:** Multiple safeguards prevent accidental actions
4. **Control:** Users configure exactly what they want
5. **Transparency:** Full logging and monitoring

## 🚀 Next Steps

1. **Community Feedback** - Gather input on design decisions
2. **Answer Open Questions** - Finalize architecture
3. **Define MVP Scope** - What goes in v1.0
4. **Implementation** - Start coding Phase 1

---

**Status:** 💭 Planning / Design Phase
**Priority:** TBD
**Labels:** `enhancement`, `feature-request`, `automation`
**Complexity:** High
**Estimated Effort:** Multiple weeks

**Feedback Needed:**
- [ ] Design approval
- [ ] Open questions answered
- [ ] MVP scope defined
- [ ] Implementation priority
