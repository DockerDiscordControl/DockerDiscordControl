# Web UI Settings - Quick Reference Guide

## Configuration File Location
**Path**: `/config/channels_config.json`

## The 4 Critical Settings Keys

### 1. REFRESH SETTINGS

#### `enable_auto_refresh` 
- **Type**: boolean (true/false)
- **Default**: true
- **Meaning**: Enable automatic periodic updates of status messages
- **Used by**: StatusOverviewService.make_update_decision()

#### `update_interval_minutes`
- **Type**: integer (minutes)
- **Default**: 10
- **Range**: 1 to 999
- **Meaning**: How often to update status (when enable_auto_refresh is true)
- **Used by**: StatusOverviewService to calculate timedelta

### 2. RECREATE SETTINGS

#### `recreate_messages_on_inactivity`
- **Type**: boolean (true/false)
- **Default**: true
- **Meaning**: Recreate (delete and repost) messages after channel inactivity
- **Used by**: StatusOverviewService._should_recreate_message()

#### `inactivity_timeout_minutes`
- **Type**: integer (minutes)
- **Default**: 10
- **Range**: 1 to 999
- **Meaning**: How long to wait without activity before recreating messages
- **Used by**: Channel cleanup logic

## Where These Settings Live

### In Configuration JSON:

**Per-Channel Settings**:
```json
"channel_permissions": {
  "1234567890": {
    "enable_auto_refresh": true,
    "update_interval_minutes": 5,
    "recreate_messages_on_inactivity": true,
    "inactivity_timeout_minutes": 10
  }
}
```

**Default Settings** (used for channels without specific config):
```json
"default_channel_permissions": {
  "enable_auto_refresh": true,
  "update_interval_minutes": 10,
  "recreate_messages_on_inactivity": true,
  "inactivity_timeout_minutes": 10
}
```

## How to Read These Settings in Your Service

```python
from services.config.config_service import load_config

config = load_config()

# Get the dicts
channel_perms = config.get('channel_permissions', {})
defaults = config.get('default_channel_permissions', {})

# For a specific channel
channel_id = "1234567890"
channel_config = channel_perms.get(channel_id, {})

# Read with fallback chain
enable_refresh = channel_config.get('enable_auto_refresh', 
                                    defaults.get('enable_auto_refresh', True))
update_interval = channel_config.get('update_interval_minutes',
                                     defaults.get('update_interval_minutes', 10))
recreate_enabled = channel_config.get('recreate_messages_on_inactivity',
                                      defaults.get('recreate_messages_on_inactivity', True))
inactivity_timeout = channel_config.get('inactivity_timeout_minutes',
                                        defaults.get('inactivity_timeout_minutes', 10))
```

## StatusOverviewUpdateConfig Data Class

Located in: `/services/discord/status_overview_service.py` (lines 27-33)

```python
@dataclass
class StatusOverviewUpdateConfig:
    enable_auto_refresh: bool = True
    update_interval_minutes: int = 5
    recreate_messages_on_inactivity: bool = True
    inactivity_timeout_minutes: int = 10
```

Use this as your return/response type when building response objects.

## How Settings Flow to StatusOverviewService

1. **ConfigurationPageService** loads config
2. **Web UI form** displays these settings in `_permissions_table.html`
3. User saves configuration via Web UI
4. **ConfigurationSaveService** processes the save
5. **StatusOverviewService** reads the updated settings
6. **make_update_decision()** uses the settings to decide update strategy

## Key Decision Logic

```python
from services.discord.status_overview_service import get_status_overview_service

service = get_status_overview_service()

decision = service.make_update_decision(
    channel_id=12345,
    global_config=config,
    last_update_time=datetime.now(timezone.utc),
    reason="periodic_check",
    force_refresh=False,
    force_recreate=False
)

# decision.should_update -> bool
# decision.should_recreate -> bool  
# decision.reason -> str (explains why)
# decision.skip_reason -> Optional[str]
# decision.next_check_time -> Optional[datetime]
```

## Decision Logic Flow

1. **If force_refresh=True**: Always update (manual command)
2. **If enable_auto_refresh=False**: Never update (disabled in Web UI)
3. **If time since last update < update_interval_minutes**: Skip update
4. **Check if recreate needed**: Based on inactivity_timeout_minutes
5. **Final decision**: Update if interval passed OR recreate needed

## Common Configuration Scenarios

### Aggressive Refresh (Update every 1 minute, recreate every 5 minutes)
```json
{
  "enable_auto_refresh": true,
  "update_interval_minutes": 1,
  "recreate_messages_on_inactivity": true,
  "inactivity_timeout_minutes": 5
}
```

### Normal Refresh (Update every 5 minutes, recreate every 10 minutes)
```json
{
  "enable_auto_refresh": true,
  "update_interval_minutes": 5,
  "recreate_messages_on_inactivity": true,
  "inactivity_timeout_minutes": 10
}
```

### Conservative (Update every 10 minutes, no recreate)
```json
{
  "enable_auto_refresh": true,
  "update_interval_minutes": 10,
  "recreate_messages_on_inactivity": false,
  "inactivity_timeout_minutes": 10
}
```

### Disabled (No automatic updates)
```json
{
  "enable_auto_refresh": false,
  "update_interval_minutes": 10,
  "recreate_messages_on_inactivity": false,
  "inactivity_timeout_minutes": 10
}
```

## Important Notes

### GOTCHA #1: Configuration Key Name
The code should use `default_channel_permissions` NOT `default_permissions`
- Many code locations incorrectly use `default_permissions`
- The actual config file key is `default_channel_permissions`

### GOTCHA #2: Form Field Naming
Form fields are indexed: `enable_auto_refresh_1`, `update_interval_minutes_1`, etc.
- These need to be converted to the nested structure before saving
- Check that ConfigurationSaveService does this conversion properly

### GOTCHA #3: Type Conversions
- Form data arrives as strings ("1", "0", "5")
- Must convert to appropriate types (bool, int) when processing
- JavaScript template already handles this for display

## Files to Reference

1. **Configuration**: `/config/channels_config.json`
2. **Service Logic**: `/services/discord/status_overview_service.py`
3. **Form HTML**: `/app/templates/_permissions_table.html`
4. **Form JS**: `/app/templates/_scripts.html` (lines 1436-1459, 1078-1081)
5. **Config Service**: `/services/config/config_service.py`
6. **Save Service**: `/services/web/configuration_save_service.py`
7. **Page Service**: `/services/web/configuration_page_service.py`

## Testing Your Implementation

To verify settings are read correctly:

```python
from services.discord.status_overview_service import log_channel_update_decision

# This will log full decision details including config used
log_channel_update_decision(
    channel_id=1283494245235294258,
    global_config=config,
    last_update_time=datetime.now(timezone.utc),
    reason="test_check"
)
```

Check logs for output like:
```
STATUS_OVERVIEW_DECISION for channel 1283494245235294258:
  Config: {'channel_id': ..., 'enable_auto_refresh': True, 'update_interval_minutes': 5, ...}
  Decision: should_update=True, should_recreate=False
  Reason: update_decided_interval_reached_...
```

