# Web UI Settings - Code Locations Reference

## Configuration Files

### Main Configuration File
**Path**: `/config/channels_config.json`
**Keys**:
- `channel_permissions` - Per-channel settings indexed by channel ID
- `default_channel_permissions` - Default settings for channels without specific config

## Service Classes

### StatusOverviewService
**File**: `/services/discord/status_overview_service.py`

**Key Components**:
1. **StatusOverviewUpdateConfig dataclass** (lines 27-33)
   - Holds configuration: enable_auto_refresh, update_interval_minutes, recreate_messages_on_inactivity, inactivity_timeout_minutes

2. **make_update_decision()** method (lines 62-150)
   - Main decision logic for determining updates
   - Uses all 4 settings to decide whether to update/recreate

3. **_get_channel_update_config()** method (lines 202-242)
   - Loads channel configuration from global_config
   - **BUG**: Uses `default_permissions` instead of `default_channel_permissions` (line 217)
   - Should be: `default_perms = global_config.get('default_channel_permissions', {})`

4. **_should_recreate_message()** method (lines 152-187)
   - Determines if message should be recreated
   - Uses `recreate_messages_on_inactivity` setting

5. **_calculate_next_check_time()** method (lines 189-200)
   - Calculates next check based on `update_interval_minutes`

6. **get_channel_config_summary()** method (lines 244-266)
   - Returns summary of channel config for debugging

### ConfigService
**File**: `/services/config/config_service.py`

**Key Methods**:
1. **_get_default_channels_config()** (lines 1226-1247)
   - Returns default configuration structure
   - Defines hardcoded defaults for all settings

2. **load_config()** (legacy function, line 1304+)
   - Loads unified configuration

3. **save_config()** (method)
   - Saves configuration to file

4. **process_config_form()** (legacy function)
   - Converts form data to config format
   - **POTENTIAL ISSUE**: May not properly convert form fields to channel_permissions structure

### ConfigurationSaveService
**File**: `/services/web/configuration_save_service.py`

**Key Methods**:
1. **save_configuration()** (lines 45-101)
   - Main save entry point
   - Orchestrates the entire save process

2. **_clean_form_data()** (lines 126-134)
   - Converts single-item lists to values

3. **_process_configuration()** (lines 136-146)
   - Calls process_config_form() to process form data

4. **_save_configuration_files()** (lines 201-236)
   - Saves main configuration and container info

### ConfigurationPageService
**File**: `/services/web/configuration_page_service.py`

**Key Methods**:
1. **prepare_page_data()** (lines 53-114)
   - Prepares all data for configuration template

2. **_assemble_template_data()** (lines 458-489)
   - Assembles final template data including DEFAULT_CONFIG
   - Provides default_channel_permissions to template (line 471)

## Web UI Templates

### Channel Permissions Table
**File**: `/app/templates/_permissions_table.html`

**Key Elements**:
- Lines 1-22: Table header with descriptions of each column
- Line 15: "Refresh" column header (enable_auto_refresh)
- Line 16: "Minutes" column header (update_interval_minutes)
- Line 17: "Recreate" column header (recreate_messages_on_inactivity)
- Line 18: "Minutes" column header (inactivity_timeout_minutes)
- Line 24: Template gets defaults: `config.get('default_channel_permissions', DEFAULT_CONFIG['default_channel_permissions'])`
- Lines 64-68: Refresh toggle and interval input (empty row template)
- Lines 71-75: Recreate toggle and timeout input (empty row template)
- Lines 122-126: Refresh toggle and interval input (existing channels loop)
- Lines 129-133: Recreate toggle and timeout input (existing channels loop)

**Form Field Naming Convention**:
```
enable_auto_refresh_{N}              # Checkbox for refresh toggle
update_interval_minutes_{N}          # Number input for refresh interval
recreate_messages_on_inactivity_{N}  # Checkbox for recreate toggle
inactivity_timeout_minutes_{N}       # Number input for timeout
```
Where N = 1-based row index

### JavaScript Form Handling
**File**: `/app/templates/_scripts.html`

**Key Sections**:
- Lines 1436-1459: Processing of channel settings during form submission
  - Lines 1437-1441: Settings map definition
  - Lines 1452-1459: Numeric settings processing
  
- Lines 1078-1081: Dynamic row creation for new channels
  - Uses same form field names with dynamic index
  - Uses defaults from template data

- Lines 1403-1463: Full channel row processing
  - Extracts all channel data including refresh/recreate settings
  - Adds to FormData for POST request

**Form Data Structure Posted**:
```
enable_auto_refresh_1: "1" or "0"
update_interval_minutes_1: "5"
recreate_messages_on_inactivity_1: "1" or "0"
inactivity_timeout_minutes_1: "10"
```

## Flask Routes

### Configuration Page Route
**File**: `/app/blueprints/main_routes.py`

**Route**: `@main_bp.route('/', methods=['GET'])`
**Handler**: `config_page()` (lines 98-133)
- Uses ConfigurationPageService to prepare page data
- Provides DEFAULT_CONFIG with default_channel_permissions to template

### Save Configuration Route
**File**: `/app/blueprints/main_routes.py`

**Route**: `@main_bp.route('/save_config_api', methods=['POST'])`
**Handler**: `save_config_api()` (lines 135-198)
- Receives form data from Web UI
- Uses ConfigurationSaveService to process save
- Returns JSON response for AJAX requests

## Data Flow Diagram

```
Web UI Form (_permissions_table.html)
    ↓
JavaScript Form Handler (_scripts.html, lines 1436-1459)
    ↓
FormData with indexed fields (enable_auto_refresh_1, etc.)
    ↓
Flask Route: /save_config_api (main_routes.py, lines 135-198)
    ↓
ConfigurationSaveService.save_configuration() (lines 45-101)
    ↓
_clean_form_data() (lines 126-134)
    ↓
process_config_form() (config_service.py)
    ↓
save_config() (ConfigService)
    ↓
/config/channels_config.json updated
    ↓
On Next Load: load_config() reads updated values
    ↓
StatusOverviewService reads settings from global_config
    ↓
make_update_decision() uses settings to determine behavior
```

## Setting Value Flows

### Reading Flow:
1. ConfigService.load_config() reads from `/config/channels_config.json`
2. Config is stored in memory with keys:
   - `channel_permissions[channel_id]` - Channel-specific settings
   - `default_channel_permissions` - Default settings
3. StatusOverviewService._get_channel_update_config() reads these values
4. Creates StatusOverviewUpdateConfig dataclass with all 4 settings

### Saving Flow:
1. Web UI form displays current values from `config['channel_permissions']` and defaults
2. User modifies values in form
3. JavaScript collects form values into FormData (with indexed names)
4. Flask receives form data as dict
5. ConfigurationSaveService processes it
6. Converts to config structure (IMPLEMENTATION TODO)
7. ConfigService.save_config() writes to JSON file

## Key Integration Points

### Where Settings Are Used:
1. **StatusOverviewService.make_update_decision()** - Lines 62-150
   - Checks enable_auto_refresh (line 97)
   - Uses update_interval_minutes (line 111)
   - Calls _should_recreate_message() (line 121)

2. **StatusOverviewService._should_recreate_message()** - Lines 152-187
   - Checks recreate_messages_on_inactivity (line 171)
   - Checks mech state requirements

3. **docker_control.py** - May use settings for individual server updates
   - Location: `/cogs/docker_control.py` (from git status)

4. **Channel cleanup service** - May use inactivity_timeout_minutes
   - Location: `/services/discord/channel_cleanup_service.py`

## Testing/Debug Points

### Manual Configuration Load:
```python
from services.config.config_service import load_config
from services.discord.status_overview_service import get_status_overview_service, log_channel_update_decision

config = load_config()
print(config.get('channel_permissions'))
print(config.get('default_channel_permissions'))

# Test decision logic
channel_id = 1283494245235294258
log_channel_update_decision(
    channel_id=channel_id,
    global_config=config,
    reason="test"
)
```

### Check Current Config Values:
```bash
# View actual config file
cat /config/channels_config.json | python -m json.tool | grep -A 15 "enable_auto_refresh"
```

### Verify Settings in Web UI:
1. Go to Web UI config page (http://localhost:5001/)
2. Look at "Command Permissions" table
3. Check "Refresh" and "Recreate" columns for each channel
4. Note the "Minutes" values in adjacent columns

## Known Issues to Address

### Issue 1: Wrong Config Key in StatusOverviewService
**Location**: `/services/discord/status_overview_service.py`, line 217
**Problem**: Uses `default_permissions` but config has `default_channel_permissions`
**Fix**: Change to `global_config.get('default_channel_permissions', {})`

### Issue 2: Form Processing May Be Incomplete
**Location**: `/services/web/configuration_save_service.py` or `/services/config/config_service.py`
**Problem**: Form fields (enable_auto_refresh_1, etc.) may not be properly converted to channel_permissions structure
**Evidence**: process_config_form() appears to pass data directly to save_config() without conversion
**TODO**: Verify form processing logic and implement proper field-to-structure conversion

### Issue 3: Type Conversions
**Location**: Form processing
**Problem**: Form data arrives as strings but should be converted to bool/int
**Expected**: enable_auto_refresh should be bool, update_interval_minutes should be int
**Check**: Verify form processor handles type conversions correctly

## References in Codebase

### Mentions of Settings Keys:
```bash
# Find all mentions of enable_auto_refresh
grep -r "enable_auto_refresh" /Volumes/appdata/dockerdiscordcontrol/ --include="*.py" --include="*.html"

# Find all mentions of update_interval_minutes
grep -r "update_interval_minutes" /Volumes/appdata/dockerdiscordcontrol/ --include="*.py" --include="*.html"

# Find all mentions of recreate_messages_on_inactivity
grep -r "recreate_messages_on_inactivity" /Volumes/appdata/dockerdiscordcontrol/ --include="*.py" --include="*.html"

# Find all mentions of inactivity_timeout_minutes
grep -r "inactivity_timeout_minutes" /Volumes/appdata/dockerdiscordcontrol/ --include="*.py" --include="*.html"
```

