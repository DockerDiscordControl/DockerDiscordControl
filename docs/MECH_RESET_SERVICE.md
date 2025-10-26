# Mech Reset Service - Documentation

The Mech Reset Service provides easy methods to reset the Mech system to Level 1 for testing and development purposes.

## 🚀 Quick Usage

### Option 1: Simple Python Script
```bash
python3 reset_mech.py
```

### Option 2: Direct Service Call
```python
from services.mech.mech_reset_service import quick_mech_reset

result = quick_mech_reset()
print(result.message)
```

### Option 3: Web UI API Endpoint
```bash
# POST request to reset Mech
curl -X POST http://localhost:5001/api/mech/reset

# GET request to check status
curl http://localhost:5001/api/mech/status
```

## 📋 Service Methods

### `MechResetService` Class

#### `full_reset()` → `ResetResult`
Performs a complete reset to Level 1:
- Clears all donations
- Resets achieved levels to Level 1 only
- Resets mech state
- Resets evolution mode to defaults

#### `clear_all_donations()` → `ResetResult`
Clears all donations from `mech_donations.json`

#### `reset_achieved_levels()` → `ResetResult`
Resets `achieved_levels.json` to Level 1 only

#### `reset_mech_state()` → `ResetResult`
Resets `mech_state.json` to Level 1 state

#### `reset_evolution_mode()` → `ResetResult`
Resets `evolution_mode.json` to default settings

#### `get_current_status()` → `Dict[str, Any]`
Returns current Mech system status:
- `donations_count`: Number of donations
- `current_level`: Current achieved level
- `achieved_levels_count`: Number of achieved levels
- `channels_tracked`: Number of Discord channels tracked
- `glvl_values`: Array of galaxy level values per channel

## 🌐 Web UI Endpoints

### `POST /api/mech/reset`
**Auth Required**: Yes
**Description**: Reset Mech system to Level 1

**Response**:
```json
{
  "success": true,
  "message": "✅ Complete Mech reset to Level 1 successful!",
  "previous_status": {
    "donations_count": 5,
    "current_level": 3,
    "achieved_levels_count": 3
  },
  "operations": [
    "Donations: All donations cleared",
    "Achieved Levels: Achieved levels reset to Level 1",
    "Mech State: Mech state reset to Level 1",
    "Evolution Mode: Evolution mode reset to defaults"
  ],
  "timestamp": "2025-10-26T10:30:00.000000"
}
```

### `GET /api/mech/status`
**Auth Required**: Yes
**Description**: Get current Mech system status

**Response**:
```json
{
  "success": true,
  "status": {
    "donations_count": 0,
    "current_level": 1,
    "achieved_levels_count": 1,
    "channels_tracked": 1,
    "glvl_values": [1]
  },
  "timestamp": "2025-10-26T10:30:00.000000"
}
```

## 📁 Files Modified

The service modifies these config files:

- `config/mech_donations.json` - Cleared to empty donations array
- `config/achieved_levels.json` - Reset to Level 1 only
- `config/mech_state.json` - Reset glvl values to 1
- `config/evolution_mode.json` - Reset to default settings

## 🔍 Example Usage

### Complete Reset Example:
```python
from services.mech.mech_reset_service import get_mech_reset_service

# Get service
service = get_mech_reset_service()

# Check current status
status = service.get_current_status()
print(f"Current Level: {status['current_level']}")

# Perform full reset
result = service.full_reset()

if result.success:
    print("✅ Reset successful!")
    for operation in result.details['operations']:
        print(f"  - {operation}")
else:
    print(f"❌ Reset failed: {result.message}")
```

### Status Check Example:
```python
from services.mech.mech_reset_service import get_mech_reset_service

service = get_mech_reset_service()
status = service.get_current_status()

print("📊 Mech Status:")
print(f"  Level: {status['current_level']}")
print(f"  Donations: {status['donations_count']}")
print(f"  Channels: {status['channels_tracked']}")
```

## 🛡️ Safety Features

- **Atomic Operations**: All file writes use temporary files and atomic renames
- **Error Handling**: Comprehensive error handling with detailed messages
- **Logging**: All operations are logged for debugging
- **Action Logging**: Web UI operations are logged to user action log
- **Status Preservation**: Channel IDs and structure are preserved during reset

## 🎯 Use Cases

Perfect for:
- **Development Testing**: Quick reset between test runs
- **Demo Preparation**: Reset to clean state for presentations
- **Bug Reproduction**: Start from known Level 1 state
- **Feature Testing**: Test evolution progression from beginning

## ⚠️ Important Notes

- This service is intended for **development and testing** only
- All donation data will be **permanently lost** during reset
- Level achievements will be reset to **Level 1 only**
- The service preserves Discord channel structure but resets progress
- Web UI endpoints require authentication