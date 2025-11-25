# Feature Plan: Auto-Action System for Update Notifications

## 🎯 Vision
A generic, flexible system that allows DDC users to automatically trigger container actions when specific messages appear in monitored Discord channels.

## 📋 Use Cases

### Primary Use Case
- **Icarus Updates:** Monitor Icarus announcements → Auto-restart Icarus container
- **Plex Updates:** Monitor Plex forums → Restart Plex container
- **Game Server Updates:** Monitor game Discord → Restart game server
- **Custom Apps:** Any app with Discord update notifications

### Extended Use Cases
- **Multiple containers:** One update triggers multiple restarts
- **Delayed actions:** Wait X minutes before action
- **Conditional actions:** Only restart if container is running
- **Notification only:** Just notify admin, don't auto-restart

## 🏗️ Architecture Design

### 1. Configuration Structure

```json
{
  "auto_actions": [
    {
      "id": "icarus_auto_update",
      "enabled": true,
      "name": "Icarus Auto-Update",
      "description": "Automatically restart Icarus when updates are posted",

      "trigger": {
        "channel_id": "1234567890",  // tech-updates channel
        "keywords": ["update", "released", "v\\d+\\.\\d+\\.\\d+"],  // Regex support
        "match_mode": "any",  // "any" | "all" | "regex"
        "case_sensitive": false,
        "source_restriction": {
          "enabled": true,
          "allowed_servers": ["987654321"],  // Only from Icarus Discord
          "allowed_channels": ["announcement_channel_id"],
          "allowed_users": []  // Optional: Only specific users
        }
      },

      "action": {
        "type": "restart_container",  // "restart" | "stop" | "start" | "recreate" | "notification_only"
        "containers": ["icarus-server"],  // Multiple containers supported
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
        "cooldown_seconds": 3600,  // Min 1 hour between actions
        "max_triggers_per_day": 5,
        "only_if_running": true,  // Only restart if container is running
        "backup_before_action": false  // Future: Create backup before restart
      },

      "notifications": {
        "notify_on_trigger": true,
        "notify_on_action": true,
        "notify_on_error": true,
        "notification_channels": ["admin_channel_id"],
        "mention_roles": ["@Admin"]
      },

      "logging": {
        "log_all_matches": true,  // Log even if action not taken (cooldown, etc.)
        "log_channel": "log_channel_id"
      }
    }
  ]
}
```

### 2. Trigger Detection System

**Event Flow:**
```
1. Message posted in Discord
   ↓
2. Bot receives on_message event
   ↓
3. Check: Is channel monitored? (channel_id match)
   ↓
4. Check: Keywords match? (keyword detection)
   ↓
5. Check: Source allowed? (server/channel/user restriction)
   ↓
6. Check: Cooldown expired?
   ↓
7. Check: Daily limit not exceeded?
   ↓
8. TRIGGER DETECTED → Process action
```

**Keyword Matching Modes:**
- **ANY:** Match if any keyword found (`update OR released OR v2.3.0`)
- **ALL:** Match only if all keywords found (`update AND released AND v2.3.0`)
- **REGEX:** Full regex pattern matching (`v?\d+\.\d+\.\d+.*released`)

### 3. Action Execution Modes

#### Mode A: Immediate
```
Trigger detected → Action executed immediately
Risk: High | Speed: Fast | Control: None
```

#### Mode B: Delayed with Cancel
```
Trigger detected →
  ↓
Post message: "🔄 Restarting icarus-server in 60s [❌ Cancel]"
  ↓
Wait 60 seconds (or until cancel clicked)
  ↓
Execute action
Risk: Medium | Speed: Medium | Control: User can cancel
```

#### Mode C: Confirmation Required
```
Trigger detected →
  ↓
Post message: "🔔 Icarus update detected: v2.3.0
              [✅ Restart Now] [❌ Ignore] [⏰ Remind 1h]"
  ↓
Wait for user response (timeout: 5 min)
  ↓
Execute if confirmed
Risk: Low | Speed: Slow | Control: Full user control
```

#### Mode D: Notification Only
```
Trigger detected →
  ↓
Post notification: "🔔 Update available for Icarus"
  ↓
No automatic action
Risk: None | Speed: N/A | Control: Full manual
```

## 🎨 Web UI Design

### Configuration Page: `/admin/auto-actions`

**Layout:**
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
│ ┌─────────────────────────────────────────────────┐ │
│ │ ❌ Plex Update Monitor             [Edit] [🗑️]  │ │
│ │ Monitors: #plex-announcements                   │ │
│ │ Action: Notification only                       │ │
│ │ Status: Disabled                                │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Add/Edit Auto-Action Form

**Sections:**
1. **Basic Info**
   - Name
   - Description
   - Enabled toggle

2. **Trigger Configuration**
   - Channel selector (dropdown)
   - Keywords (tag input)
   - Match mode (radio: ANY/ALL/REGEX)
   - Case sensitive toggle
   - Source restrictions (optional)

3. **Action Configuration**
   - Action type (dropdown)
   - Container selector (multi-select)
   - Execution mode (radio: Immediate/Delayed/Confirmation/Notification)
   - Mode-specific settings

4. **Safety Settings**
   - Cooldown (seconds input)
   - Daily limit (number input)
   - Only if running (toggle)

5. **Notifications**
   - Notification channels (multi-select)
   - Mention roles (tag input)
   - Notification events (checkboxes)

6. **Logging**
   - Log all matches (toggle)
   - Log channel (dropdown)

## 🛡️ Safety Mechanisms

### 1. Rate Limiting
```python
cooldown_tracker = {
    "auto_action_id": {
        "last_trigger": timestamp,
        "triggers_today": count,
        "daily_reset": date
    }
}
```

### 2. Source Validation
- Verify message is from allowed server
- Verify message is from allowed channel
- Verify message is from allowed user (if configured)

### 3. Container State Checks
- Verify container exists before action
- Verify container is running (if `only_if_running=true`)
- Handle missing containers gracefully

### 4. Error Handling
- Action failures logged and notified
- Cooldown not consumed on failure
- Retry logic for transient errors

### 5. Manual Override
- Admin can disable auto-action at any time
- Admin can cancel pending delayed actions
- Admin can reset cooldowns/daily limits

## 📊 Logging & Monitoring

### Event Log Format
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
  "action_details": {
    "type": "restart_container",
    "containers": ["icarus-server"],
    "mode": "delayed",
    "delay": 60,
    "cancelled": false
  },
  "result": "success",
  "error": null
}
```

### Dashboard Metrics
- Total triggers per auto-action
- Success/failure rates
- Average delay before action
- Cancellation rates
- Cooldown hits

## 🔧 Implementation Plan

### Phase 1: Core Infrastructure
1. **Config Schema** - Define JSON structure
2. **Config Service** - Load/save/validate auto-actions
3. **Trigger Detection** - on_message handler with keyword matching
4. **Action Executor** - Execute container actions

### Phase 2: Safety & Control
1. **Cooldown System** - Rate limiting logic
2. **Source Validation** - Server/channel/user restrictions
3. **Delayed Actions** - Timer + cancel button
4. **Confirmation Mode** - Interactive confirmation

### Phase 3: Web UI
1. **List View** - Show all auto-actions
2. **Add/Edit Form** - Configure auto-actions
3. **Status Dashboard** - Monitoring & logs
4. **Manual Controls** - Enable/disable/cancel

### Phase 4: Advanced Features
1. **Regex Support** - Advanced keyword matching
2. **Multiple Containers** - Batch actions
3. **Notification Customization** - Rich notifications
4. **Backup Integration** - Pre-action backups

## 🤔 Open Questions

### 1. Message History
**Q:** Should we scan message history on startup?
- **Pro:** Catch updates posted while bot was offline
- **Con:** Could trigger old updates on restart
- **Decision:** ?

### 2. Forwarded Messages
**Q:** Discord message forwards - how to detect original source?
- Message content includes original author?
- Embed detection?
- **Decision:** ?

### 3. Multiple Triggers
**Q:** If multiple auto-actions match same message?
- Execute all?
- Execute only first?
- Priority system?
- **Decision:** ?

### 4. Container Groups
**Q:** Should we support container groups for batch operations?
- "all-game-servers"
- "production-stack"
- **Decision:** ?

### 5. Webhook Support
**Q:** Should we support triggering via webhooks (not just Discord messages)?
- External monitoring tools
- GitHub releases
- **Decision:** ?

## 📝 Configuration Examples

### Example 1: Simple Auto-Restart
```json
{
  "id": "simple_restart",
  "enabled": true,
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

### Example 2: Delayed with Cancel
```json
{
  "id": "delayed_restart",
  "enabled": true,
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
  },
  "notifications": {
    "notify_on_trigger": true,
    "notification_channels": ["admin-channel"]
  }
}
```

### Example 3: Notification Only
```json
{
  "id": "notify_only",
  "enabled": true,
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

## 🎯 Next Steps

1. **Review this plan** - Feedback & adjustments
2. **Decide on open questions** - Message history, forwarded messages, etc.
3. **Prioritize features** - MVP vs. nice-to-have
4. **Create implementation timeline** - Phase by phase
5. **Start coding** - Begin with Phase 1

---

**Status:** 🟡 Planning Phase
**Last Updated:** 2025-11-22
**Feedback Needed:** Yes - waiting for user input
