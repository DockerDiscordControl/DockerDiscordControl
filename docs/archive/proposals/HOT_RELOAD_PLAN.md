# DDC Hot-Reload Implementation Plan

## Goal
After saving configuration changes, a container restart should no longer be necessary (except for the Bot Token and Guild ID).

---

## Phase 1: Live Config for the Bot (biggest impact)

### Problem
The bot holds a static copy of the configuration:
```python
# cogs/docker_control.py
class DockerControlCog(commands.Cog):
    def __init__(self, bot, config, runtime):
        self.config = config  # Snapshot - never updated!
```

### Solution: config property instead of a snapshot

**Changes in `cogs/docker_control.py`:**
```python
class DockerControlCog(commands.Cog):
    def __init__(self, bot, config, runtime):
        self._initial_config = config  # Only for startup
        self.bot = bot
        self.runtime = runtime

    @property
    def config(self):
        """Live config - always fresh from ConfigService."""
        from services.config.config_service import get_config_service
        return get_config_service().get_config()
```

**Affected files:**
- `cogs/docker_control.py` - main cog
- `cogs/control_ui.py` - UI components
- `cogs/status_handlers.py` - status updates
- `cogs/control_helpers.py` - helper functions
- `cogs/scheduler_commands.py` - scheduled tasks

### What becomes hot-reloadable with this:
- ✅ Container selection (which containers are active)
- ✅ Container order
- ✅ Container display names
- ✅ Allowed actions per container
- ✅ Channel permissions (which commands in which channels)
- ✅ Admin users list

---

## Phase 2: Web UI Password Hot-Reload

### Problem
The password is loaded and cached when Flask starts.

### Solution: auth decorator with a live check

**Changes in `app/auth.py`:**
```python
def check_password(username, password):
    """Check password - always fresh from config."""
    from services.config.config_service import get_config_service
    config = get_config_service().get_config()
    stored_hash = config.get('web_ui_password_hash', '')
    return check_password_hash(stored_hash, password)
```

### What becomes hot-reloadable with this:
- ✅ Web UI password

---

## Phase 3: Event System for Reload Notification (Optional)

### Concept
An event system that informs the bot about config changes.

**New service: `services/infrastructure/config_reload_service.py`:**
```python
class ConfigReloadService:
    """Service to handle configuration reload events."""

    _listeners = []

    @classmethod
    def register_listener(cls, callback):
        """Register a callback for config changes."""
        cls._listeners.append(callback)

    @classmethod
    def notify_config_changed(cls, changed_sections: list):
        """Notify all listeners about config changes."""
        for listener in cls._listeners:
            try:
                listener(changed_sections)
            except Exception as e:
                logger.error(f"Error in config reload listener: {e}")
```

**Integration in `configuration_save_service.py`:**
```python
def save_configuration(self, ...):
    # ... existing save logic ...

    # Notify listeners about changes
    from services.infrastructure.config_reload_service import ConfigReloadService
    ConfigReloadService.notify_config_changed(['servers', 'channel_permissions'])
```

**Bot registration in `cogs/docker_control.py`:**
```python
def __init__(self, bot, config, runtime):
    # Register for config change notifications
    ConfigReloadService.register_listener(self._on_config_changed)

def _on_config_changed(self, changed_sections):
    """Handle configuration changes."""
    logger.info(f"Config changed: {changed_sections}")
    # Optional: Trigger status message updates, etc.
```

---

## Phase 4: UI Adjustments

### Remove the restart alert for hot-reloadable settings

**Changes in templates:**

1. `_server_selection.html` - remove `requires-restart` from:
   - Container selection checkboxes
   - Move Up/Down buttons

2. `_channel_settings.html` - keep `requires-restart` only for Guild ID

3. `_auth_settings.html` - remove `requires-restart` from Web UI Password

### New feedback system

Instead of "Restart required" we show:
- ✅ "Changes have been applied" (green)
- ⚠️ "Bot Token/Guild ID require a restart" (only if these were changed)

---

## Technical Details

### Thread-Safety
The ConfigService already uses thread locks:
```python
# services/config/config_service.py
self._lock = threading.Lock()
```

### Performance
- Config is cached with an mtime check
- It is reloaded only when the file changes
- No performance impact on every command

### Caching strategy
```python
def get_config(self, force_reload=False):
    if not force_reload and self._cache_service.is_cache_valid():
        return self._cache_service.get_cached_config()
    # ... reload from disk
```

---

## Implementation order

### Step 1: Config property in DockerControlCog
- [ ] `cogs/docker_control.py` - property instead of attribute
- [ ] Test: container changes without restart

### Step 2: Adapt further cogs
- [ ] `cogs/control_ui.py`
- [ ] `cogs/status_handlers.py`
- [ ] `cogs/control_helpers.py`
- [ ] `cogs/scheduler_commands.py`

### Step 3: Web UI Password
- [ ] `app/auth.py` - live password check

### Step 4: UI Templates
- [ ] Remove `requires-restart` classes
- [ ] New feedback system

### Step 5: Testing
- [ ] Add/remove containers without restart
- [ ] Change channel permissions without restart
- [ ] Change admin users without restart
- [ ] Change the Web UI password without restart

---

## What CANNOT be hot-reloadable

| Setting | Technical reason |
|---------|-------------------|
| **Bot Token** | The Discord WebSocket session must be rebuilt. Requires `bot.close()` and `bot.run(new_token)` |
| **Guild ID** | Slash commands are registered per guild. Requires `bot.tree.sync(guild=new_guild)`, which only works cleanly at startup |

These settings keep the `requires-restart` class.

---

## Risks & Mitigations

### Risk: Race conditions
**Mitigation:** ConfigService already uses thread locks

### Risk: Inconsistent states
**Mitigation:** Config is loaded atomically, not partially

### Risk: Memory leaks with listeners
**Mitigation:** Use WeakRef for event listeners

---

## Estimated effort

| Phase | Effort | Impact |
|-------|---------|--------|
| Phase 1 | 2-3 hours | High - containers & channels |
| Phase 2 | 30 min | Medium - Web UI Password |
| Phase 3 | 1-2 hours | Optional - clean architecture |
| Phase 4 | 30 min | UI polish |

**Recommendation:** Implement Phase 1 + 2 + 4, Phase 3 optionally later.
