# DDC Hot-Reload Implementation Plan

## Ziel
Nach dem Speichern von Konfigurationsänderungen soll kein Container-Neustart mehr nötig sein (außer für Bot Token und Guild ID).

---

## Phase 1: Live Config für Bot (Größter Impact)

### Problem
Der Bot hält eine statische Kopie der Konfiguration:
```python
# cogs/docker_control.py
class DockerControlCog(commands.Cog):
    def __init__(self, bot, config, runtime):
        self.config = config  # Snapshot - wird nie aktualisiert!
```

### Lösung: Config-Property statt Snapshot

**Änderungen in `cogs/docker_control.py`:**
```python
class DockerControlCog(commands.Cog):
    def __init__(self, bot, config, runtime):
        self._initial_config = config  # Nur für Startup
        self.bot = bot
        self.runtime = runtime

    @property
    def config(self):
        """Live config - always fresh from ConfigService."""
        from services.config.config_service import get_config_service
        return get_config_service().get_config()
```

**Betroffene Dateien:**
- `cogs/docker_control.py` - Hauptcog
- `cogs/control_ui.py` - UI Components
- `cogs/status_handlers.py` - Status Updates
- `cogs/control_helpers.py` - Helper Functions
- `cogs/scheduler_commands.py` - Scheduled Tasks

### Was damit hot-reloadbar wird:
- ✅ Container-Auswahl (welche Container aktiv sind)
- ✅ Container-Reihenfolge
- ✅ Container Display-Namen
- ✅ Allowed Actions pro Container
- ✅ Channel Permissions (welche Commands in welchen Channels)
- ✅ Admin Users Liste

---

## Phase 2: Web UI Passwort Hot-Reload

### Problem
Das Passwort wird beim Flask-Start geladen und gecacht.

### Lösung: Auth-Decorator mit Live-Check

**Änderungen in `app/auth.py`:**
```python
def check_password(username, password):
    """Check password - always fresh from config."""
    from services.config.config_service import get_config_service
    config = get_config_service().get_config()
    stored_hash = config.get('web_ui_password_hash', '')
    return check_password_hash(stored_hash, password)
```

### Was damit hot-reloadbar wird:
- ✅ Web UI Passwort

---

## Phase 3: Event-System für Reload-Benachrichtigung (Optional)

### Konzept
Ein Event-System das den Bot über Config-Änderungen informiert.

**Neuer Service: `services/infrastructure/config_reload_service.py`:**
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

**Bot-Registration in `cogs/docker_control.py`:**
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

## Phase 4: UI-Anpassungen

### Restart-Alert entfernen für hot-reloadbare Settings

**Änderungen in Templates:**

1. `_server_selection.html` - Entferne `requires-restart` von:
   - Container Selection Checkboxes
   - Move Up/Down Buttons

2. `_channel_settings.html` - Behalte `requires-restart` nur für Guild ID

3. `_auth_settings.html` - Entferne `requires-restart` von Web UI Password

### Neues Feedback-System

Statt "Neustart erforderlich" zeigen wir:
- ✅ "Änderungen wurden übernommen" (grün)
- ⚠️ "Bot Token/Guild ID erfordern Neustart" (nur wenn diese geändert wurden)

---

## Technische Details

### Thread-Safety
Die ConfigService verwendet bereits Thread-Locks:
```python
# services/config/config_service.py
self._lock = threading.Lock()
```

### Performance
- Config wird gecacht mit mtime-Check
- Nur bei Dateiänderung wird neu geladen
- Kein Performance-Impact bei jedem Command

### Caching-Strategie
```python
def get_config(self, force_reload=False):
    if not force_reload and self._cache_service.is_cache_valid():
        return self._cache_service.get_cached_config()
    # ... reload from disk
```

---

## Implementierungsreihenfolge

### Step 1: Config-Property in DockerControlCog
- [ ] `cogs/docker_control.py` - Property statt Attribut
- [ ] Testen: Container-Änderungen ohne Restart

### Step 2: Weitere Cogs anpassen
- [ ] `cogs/control_ui.py`
- [ ] `cogs/status_handlers.py`
- [ ] `cogs/control_helpers.py`
- [ ] `cogs/scheduler_commands.py`

### Step 3: Web UI Password
- [ ] `app/auth.py` - Live Password Check

### Step 4: UI Templates
- [ ] `requires-restart` Klassen entfernen
- [ ] Neues Feedback-System

### Step 5: Testing
- [ ] Container hinzufügen/entfernen ohne Restart
- [ ] Channel Permissions ändern ohne Restart
- [ ] Admin Users ändern ohne Restart
- [ ] Web UI Passwort ändern ohne Restart

---

## Was NICHT hot-reloadbar sein kann

| Setting | Technischer Grund |
|---------|-------------------|
| **Bot Token** | Discord WebSocket Session muss neu aufgebaut werden. Erfordert `bot.close()` und `bot.run(new_token)` |
| **Guild ID** | Slash Commands sind guild-spezifisch registriert. Erfordert `bot.tree.sync(guild=new_guild)` was nur beim Start sauber funktioniert |

Diese Settings behalten die `requires-restart` Klasse.

---

## Risiken & Mitigationen

### Risiko: Race Conditions
**Mitigation:** ConfigService verwendet bereits Thread-Locks

### Risiko: Inkonsistente Zustände
**Mitigation:** Config wird atomar geladen, nicht partiell

### Risiko: Memory Leaks bei Listeners
**Mitigation:** WeakRef für Event-Listeners verwenden

---

## Geschätzter Aufwand

| Phase | Aufwand | Impact |
|-------|---------|--------|
| Phase 1 | 2-3 Stunden | Hoch - Container & Channels |
| Phase 2 | 30 Min | Mittel - Web UI Password |
| Phase 3 | 1-2 Stunden | Optional - Saubere Architektur |
| Phase 4 | 30 Min | UI Polish |

**Empfehlung:** Phase 1 + 2 + 4 implementieren, Phase 3 optional später.
