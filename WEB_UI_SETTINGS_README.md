# Web UI Settings Documentation - Complete Index

## Overview
This directory contains comprehensive documentation of the Web UI settings structure for refresh and recreate functionality in DockerDiscordControl. These documents will help you correctly implement SERVICE FIRST patterns when reading and managing these settings.

## The 4 Critical Settings

1. **enable_auto_refresh** (bool) - Enable/disable automatic status message updates
2. **update_interval_minutes** (int) - How often to update status (1-999 minutes)
3. **recreate_messages_on_inactivity** (bool) - Enable/disable message recreation after inactivity
4. **inactivity_timeout_minutes** (int) - How long to wait before recreating (1-999 minutes)

## Documentation Files

### 1. WEB_UI_SETTINGS_QUICK_REFERENCE.md
**Start here for quick lookups**
- The 4 critical settings explained
- Where settings live in JSON structure
- How to read settings in your code
- Common configuration scenarios
- Testing instructions

**Use when**: You need quick answers about setting keys, defaults, or code examples.

### 2. WEB_UI_SETTINGS_ANALYSIS.md
**Complete technical analysis**
- Configuration file structure (JSON format)
- Exact setting keys and types
- Hierarchy: default_channel_permissions vs channel_permissions
- Web UI HTML form structure
- Form data processing flow (all 5 steps)
- How StatusOverviewService uses settings
- Critical bugs identified
- Service integration points

**Use when**: You need to understand the complete picture or debug issues.

### 3. WEB_UI_SETTINGS_CODE_LOCATIONS.md
**Detailed code reference**
- Exact file paths for all related code
- Line numbers for key methods
- Data flow diagram
- Known issues with locations
- Testing/debug commands with grep

**Use when**: You need to find specific code or understand integration points.

## Quick Start for Your SERVICE FIRST Implementation

### Step 1: Read Settings Correctly
```python
from services.config.config_service import load_config

config = load_config()
channel_perms = config.get('channel_permissions', {})
defaults = config.get('default_channel_permissions', {})

# For a specific channel
channel_id = "1234567890"
channel_config = channel_perms.get(channel_id, {})

# Read with fallback chain
enable_refresh = channel_config.get('enable_auto_refresh', 
                                    defaults.get('enable_auto_refresh', True))
```

### Step 2: Understand the Data Structure
- **Config File**: `/config/channels_config.json`
- **Channel Settings**: Nested under `channel_permissions[channel_id]`
- **Default Settings**: Flat structure under `default_channel_permissions`
- **Fallback**: Use channel-specific → defaults → hardcoded

### Step 3: Use the Existing Service
StatusOverviewService already implements the core logic:

```python
from services.discord.status_overview_service import get_status_overview_service

service = get_status_overview_service()
decision = service.make_update_decision(
    channel_id=12345,
    global_config=config,
    last_update_time=datetime.now(timezone.utc)
)

# decision.should_update -> bool
# decision.should_recreate -> bool
# decision.reason -> why it decided this way
```

### Step 4: Know the Bug to Avoid
StatusOverviewService has a bug on line 217:
```python
# WRONG:
default_perms = global_config.get('default_permissions', {})

# CORRECT:
default_perms = global_config.get('default_channel_permissions', {})
```

## Architecture Overview

### Configuration Hierarchy
```
/config/channels_config.json
├── channel_permissions          (Per-channel settings)
│   ├── "1234567890"            (Channel ID)
│   │   ├── enable_auto_refresh
│   │   ├── update_interval_minutes
│   │   ├── recreate_messages_on_inactivity
│   │   └── inactivity_timeout_minutes
│   └── "9876543210"
│       └── ... (same structure)
└── default_channel_permissions  (Default settings for all channels)
    ├── enable_auto_refresh
    ├── update_interval_minutes
    ├── recreate_messages_on_inactivity
    └── inactivity_timeout_minutes
```

### Service Flow
```
ConfigurationPageService
    ↓ (loads config)
Web UI (_permissions_table.html)
    ↓ (displays settings)
JavaScript (_scripts.html)
    ↓ (collects form data)
Flask Route (/save_config_api)
    ↓ (receives form data)
ConfigurationSaveService
    ↓ (processes save)
ConfigService.save_config()
    ↓ (writes to file)
/config/channels_config.json
    ↓ (next reload)
StatusOverviewService
    ↓ (reads settings)
make_update_decision()
    ↓ (decides update strategy)
Application Logic
```

## Default Values

When no configuration exists or is not set:
- `enable_auto_refresh`: **true**
- `update_interval_minutes`: **10**
- `recreate_messages_on_inactivity`: **true**
- `inactivity_timeout_minutes`: **10**

## Current Configuration Example

From the repository's actual `/config/channels_config.json`:

**Channel 1 (Status Kanal)**:
- Refresh: Enabled, every 5 minutes
- Recreate: Enabled, after 10 minutes inactivity

**Channel 2 (Kontroll Kanal)**:
- Refresh: Enabled, every 1 minute (aggressive)
- Recreate: Enabled, after 10 minutes inactivity

## Key Files Reference

| File | Purpose | Key Section |
|------|---------|-------------|
| `/config/channels_config.json` | Configuration storage | channel_permissions, default_channel_permissions |
| `/services/discord/status_overview_service.py` | Decision logic | make_update_decision(), _get_channel_update_config() |
| `/app/templates/_permissions_table.html` | Web UI form | Form fields, displays settings |
| `/app/templates/_scripts.html` | Form handling | Lines 1436-1459 (setting processing) |
| `/services/config/config_service.py` | Config management | _get_default_channels_config(), process_config_form() |
| `/services/web/configuration_save_service.py` | Save orchestration | save_configuration(), _process_configuration() |
| `/services/web/configuration_page_service.py` | Page preparation | prepare_page_data(), _assemble_template_data() |

## Common Tasks

### View Current Configuration
```bash
cat /config/channels_config.json | python -m json.tool
```

### Debug Setting Lookup
```python
from services.discord.status_overview_service import log_channel_update_decision

log_channel_update_decision(
    channel_id=1283494245235294258,
    global_config=config,
    reason="debug"
)
```

### Test Your Service Implementation
```python
from services.config.config_service import load_config

config = load_config()
print("Channel Permissions:", config.get('channel_permissions'))
print("Defaults:", config.get('default_channel_permissions'))
```

## Known Issues & TODOs

### Issue 1: Wrong Config Key
- **File**: `/services/discord/status_overview_service.py`, line 217
- **Problem**: Uses `default_permissions` but should use `default_channel_permissions`
- **Status**: Needs fixing
- **Impact**: Fallback to defaults may not work correctly

### Issue 2: Form Processing Incomplete
- **File**: Form submission to config save
- **Problem**: Form fields like `enable_auto_refresh_1` may not be converted to channel_permissions structure
- **Status**: Need to verify form processing logic
- **Impact**: Settings from Web UI may not save correctly to nested structure

### Issue 3: Type Conversions
- **File**: Form processing
- **Problem**: String form data ("1", "0", "5") needs conversion to bool/int
- **Status**: Need to verify form processor handles this
- **Impact**: Settings may be stored as strings instead of proper types

## Next Steps

1. **Read QUICK_REFERENCE.md** for basic understanding
2. **Review ANALYSIS.md** for complete technical details
3. **Check CODE_LOCATIONS.md** for exact file references
4. **Implement your SERVICE FIRST** using the patterns shown
5. **Test using the debugging commands** provided
6. **Fix the known issues** documented above

## Questions?

Refer to the specific documentation files:
- "How do I read these settings?" → QUICK_REFERENCE.md
- "What's the complete structure?" → ANALYSIS.md
- "Where is this code?" → CODE_LOCATIONS.md
- "What's wrong with the current code?" → CODE_LOCATIONS.md (Known Issues section)

## Version Information

- **Created**: October 26, 2025
- **For**: SERVICE FIRST Implementation
- **Target**: Refresh/Recreate Functionality
- **Config Version**: channels_config.json format

---

**CRITICAL REMEMBER**: The config key is `default_channel_permissions`, NOT `default_permissions`!
