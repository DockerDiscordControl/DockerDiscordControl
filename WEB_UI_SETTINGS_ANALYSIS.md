# Web UI Settings Structure Analysis - Refresh & Recreate Functionality

## Critical Findings for SERVICE FIRST Implementation

### 1. Configuration File Structure

**File**: `/config/channels_config.json`

#### Channel Permissions Structure:
```json
{
  "channel_permissions": {
    "CHANNEL_ID": {
      "name": "Channel Name",
      "commands": {
        "serverstatus": true,
        "command": false,
        "control": false,
        "schedule": false
      },
      "post_initial": true,
      "update_interval_minutes": 5,
      "inactivity_timeout_minutes": 10,
      "enable_auto_refresh": true,
      "recreate_messages_on_inactivity": true,
      "channel_id": "CHANNEL_ID"
    }
  },
  "default_channel_permissions": {
    "commands": {
      "serverstatus": true,
      "command": false,
      "control": false,
      "schedule": false
    },
    "post_initial": false,
    "update_interval_minutes": 10,
    "inactivity_timeout_minutes": 10,
    "enable_auto_refresh": true,
    "recreate_messages_on_inactivity": true
  }
}
```

### 2. Exact Setting Keys

#### Refresh Settings (Auto-Update Configuration):
- **Key**: `enable_auto_refresh` (boolean)
  - Type: bool
  - Default: true
  - Meaning: Enable/disable automatic status message updates
  
- **Key**: `update_interval_minutes` (integer)
  - Type: int
  - Default: 10 (can be 1-based minutes)
  - Minimum: 1 minute
  - Meaning: How often to refresh status messages (in minutes)

#### Recreate Settings (Inactivity-based Recreation):
- **Key**: `recreate_messages_on_inactivity` (boolean)
  - Type: bool
  - Default: true
  - Meaning: Enable/disable message recreation after inactivity period
  
- **Key**: `inactivity_timeout_minutes` (integer)
  - Type: int
  - Default: 10
  - Minimum: 1 minute
  - Meaning: How long to wait before recreating messages (in minutes)

### 3. Hierarchy: default_permissions vs channel_permissions

**CRITICAL**: The status_overview_service.py shows the correct lookup pattern:

```python
# From services/discord/status_overview_service.py, line 216-219
channel_permissions = global_config.get('channel_permissions', {})
default_perms = global_config.get('default_permissions', {})  # NOTE: Bug here!
channel_config = channel_permissions.get(str(channel_id), default_perms)
```

**ACTUAL CONFIG KEY**: The actual config uses `default_channel_permissions`, NOT `default_permissions`

**Correct Lookup Pattern** (what SHOULD be used):
1. Get channel-specific settings from `channel_permissions[channel_id]`
2. For missing keys, fall back to `default_channel_permissions`
3. If key exists in channel config, use it; otherwise use default

**FALLBACK CHAIN**:
```
channel_permissions[channel_id][key] 
  → default_channel_permissions[key] 
    → Hardcoded defaults
```

### 4. Web UI HTML Form Structure

**Template File**: `/app/templates/_permissions_table.html`

Form field naming convention (per row index):
```
enable_auto_refresh_N           → Channel-specific refresh toggle
update_interval_minutes_N       → Channel-specific refresh interval
recreate_messages_on_inactivity_N → Channel-specific recreate toggle
inactivity_timeout_minutes_N    → Channel-specific inactivity timeout
```

Where N = 1-based row index in the channel permissions table.

### 5. Form Data Processing Flow

**Step 1: HTML Form** (`_permissions_table.html`)
- Displays both channel-specific and default settings
- Uses row index (1, 2, 3...) for form field names
- Example: `enable_auto_refresh_1`, `update_interval_minutes_1`

**Step 2: JavaScript** (`_scripts.html`, lines 1436-1459)
```javascript
const settingsMap = {
    'post_initial': 'post_initial',
    'enable_auto_refresh': 'enable_auto_refresh', 
    'recreate_messages_on_inactivity': 'recreate_messages_on_inactivity'
};

const numericSettings = ['update_interval_minutes', 'inactivity_timeout_minutes'];
```

Converts form fields to FormData for POST request.

**Step 3: Flask Route** (`/save_config_api`)
- Receives form data as dict(flat=False)
- Passes to `ConfigurationSaveService`

**Step 4: ConfigurationSaveService** (`services/web/configuration_save_service.py`)
- Cleans form data
- Calls `process_config_form()`

**Step 5: process_config_form()** (`services/config/config_service.py`)
- Passes cleaned form data directly to `save_config()`
- Note: Does NOT explicitly convert form fields to channel_permissions structure
- This is a CRITICAL FINDING - form processing may be incomplete!

### 6. ConfigService Default Configuration

**Source**: `services/config/config_service.py`, `_get_default_channels_config()`, line 1226

Default values when NO custom configuration exists:
```python
{
    'channels': {},
    'server_selection': {},
    'server_order': [],
    'channel_permissions': {},
    'spam_protection': {},
    'default_channel_permissions': {
        "commands": {
            "serverstatus": True,
            "command": False,
            "control": False,
            "schedule": False
        },
        "post_initial": False,
        "update_interval_minutes": 10,
        "inactivity_timeout_minutes": 10,
        "enable_auto_refresh": True,
        "recreate_messages_on_inactivity": True
    }
}
```

### 7. How Status Overview Service Uses Settings

**Source**: `services/discord/status_overview_service.py`

**StatusOverviewUpdateConfig dataclass** (lines 28-33):
```python
@dataclass
class StatusOverviewUpdateConfig:
    enable_auto_refresh: bool = True
    update_interval_minutes: int = 5
    recreate_messages_on_inactivity: bool = True
    inactivity_timeout_minutes: int = 10
```

**Loading Channel Config** (`_get_channel_update_config()`, lines 202-242):
```python
# Get channel permissions from config
channel_permissions = global_config.get('channel_permissions', {})
default_perms = global_config.get('default_permissions', {})  # BUG!
channel_config = channel_permissions.get(str(channel_id), default_perms)

# Create config object with fallbacks
config = StatusOverviewUpdateConfig(
    enable_auto_refresh=channel_config.get('enable_auto_refresh',
                                         default_perms.get('enable_auto_refresh', True)),
    update_interval_minutes=channel_config.get('update_interval_minutes',
                                              default_perms.get('update_interval_minutes', 5)),
    recreate_messages_on_inactivity=channel_config.get('recreate_messages_on_inactivity',
                                                      default_perms.get('recreate_messages_on_inactivity', True)),
    inactivity_timeout_minutes=channel_config.get('inactivity_timeout_minutes',
                                                 default_perms.get('inactivity_timeout_minutes', 10))
)
```

**BUG IDENTIFIED**: Uses `default_permissions` but config has `default_channel_permissions`!

### 8. Configuration Page Service

**Source**: `services/web/configuration_page_service.py`

**Provides to Template** (line 471):
```python
'DEFAULT_CONFIG': {
    'default_channel_permissions': config_service._get_default_channels_config()['default_channel_permissions']
}
```

This is correctly passed to template as `DEFAULT_CONFIG['default_channel_permissions']`.

### 9. Web UI Template Variables

**In Jinja2 template** (`_permissions_table.html`, line 24):
```jinja2
{% set defaults = config.get('default_channel_permissions', DEFAULT_CONFIG['default_channel_permissions']) %}
```

Template uses TWO variables:
1. `config['default_channel_permissions']` - from loaded config
2. `DEFAULT_CONFIG['default_channel_permissions']` - from service defaults (fallback)

### 10. Form Input Constraints

From HTML template (`_permissions_table.html`):
- `update_interval_minutes`: type="number", min="1"
- `inactivity_timeout_minutes`: type="number", min="1"
- Enabled/disabled state controlled by checkboxes:
  - Minutes inputs disabled when refresh/recreate checkboxes are unchecked

### 11. Current Config Example (From Repository)

**File**: `/config/channels_config.json`

Channel 1 (Status Kanal):
```json
{
  "name": "Status Kanal",
  "enable_auto_refresh": true,
  "update_interval_minutes": 5,
  "recreate_messages_on_inactivity": true,
  "inactivity_timeout_minutes": 10
}
```

Channel 2 (Kontroll Kanal):
```json
{
  "name": "Kontroll Kanal",
  "enable_auto_refresh": true,
  "update_interval_minutes": 1,
  "recreate_messages_on_inactivity": true,
  "inactivity_timeout_minutes": 10
}
```

### 12. Key Implementation Notes for SERVICE FIRST

#### For Reading Settings:
1. Load global_config using ConfigService
2. Get channel_permissions dict from config
3. Get default_channel_permissions dict from config (NOT default_permissions)
4. Look up channel_id in channel_permissions
5. For each setting, use: `channel_specific.get(key, default_perms.get(key, hardcoded_default))`

#### For Saving Settings:
1. Form data comes as flat dict with keys like: `enable_auto_refresh_1`, `update_interval_minutes_1`
2. Need to convert these to nested structure under channel_permissions[channel_id]
3. Also update default_channel_permissions for default values
4. Save via ConfigService.save_config()

#### Critical Bug to Fix:
- StatusOverviewService uses `default_permissions` but should use `default_channel_permissions`
- Line 217 in status_overview_service.py needs fix

### 13. Integration Points

**Services that use these settings**:
1. `StatusOverviewService` - Decides when to update status messages
2. `docker_control.py` - May use settings for individual server updates
3. Configuration UI - Displays and manages these settings
4. Channel cleanup service - May use inactivity timeout

**Key Decision Method**:
```python
service.make_update_decision(
    channel_id=channel_id,
    global_config=config,
    last_update_time=last_update_datetime,
    force_refresh=False,
    force_recreate=False
)
```

Returns `UpdateDecision` with:
- `should_update`: bool
- `should_recreate`: bool
- `reason`: str
- `next_check_time`: datetime
- `skip_reason`: Optional[str]

## Summary for SERVICE FIRST Implementation

### What YOUR SERVICE Must Do:

1. **Read Settings Correctly**:
   ```python
   config = load_config()
   channel_perms = config.get('channel_permissions', {})
   default_perms = config.get('default_channel_permissions', {})  # NOT default_permissions!
   ```

2. **Build Response Objects** with fallback chain:
   - Use channel-specific value if it exists
   - Fall back to default_channel_permissions
   - Fall back to hardcoded defaults

3. **Expected Config Structure**:
   - Path: `/config/channels_config.json`
   - Top-level keys: `channel_permissions`, `default_channel_permissions`, `commands`, etc.
   - Channel-level keys: `enable_auto_refresh`, `update_interval_minutes`, `recreate_messages_on_inactivity`, `inactivity_timeout_minutes`

4. **Default Values**:
   - `enable_auto_refresh`: True
   - `update_interval_minutes`: 10
   - `recreate_messages_on_inactivity`: True
   - `inactivity_timeout_minutes`: 10

5. **Known Issues**:
   - StatusOverviewService has bug using `default_permissions` instead of `default_channel_permissions`
   - Form processing may not properly convert form fields to channel_permissions structure
