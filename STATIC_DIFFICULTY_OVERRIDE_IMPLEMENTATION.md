# Static Difficulty Override Implementation

## Overview

The "Static Difficulty Override" feature allows users to choose between:
- **Dynamic Difficulty** (Override OFF): Costs adjust based on Discord community size
- **Static Difficulty** (Override ON): Custom multiplier applied to all costs

## Architecture

### Configuration Storage
- **File**: `config/evolution_mode.json`
- **Fields**:
  - `use_dynamic`: `true` (dynamic mode) / `false` (static mode)
  - `difficulty_multiplier`: Float value (0.5 - 2.4)
  - `last_updated`: Timestamp

### Web UI Control
- **Location**: Advanced Settings Modal → Donation System Control → Mech Evolution Difficulty
- **Toggle**: "Static Difficulty Override"
  - **OFF**: Dynamic evolution costs based on community size (min 1.0×)
  - **ON**: Static custom difficulty from slider/buttons
- **Slider**: Evolution Cost Multiplier (0.5× to 2.4×)
- **Quick Buttons**: Easy (0.5×), Normal (1.0×), Hard (2.0×)

### Cost Calculation

The core calculation happens in `services/mech/progress_service.py`:

```python
def requirement_for_level_and_bin(level: int, b: int) -> int:
    """
    Calculate total requirement respecting Static Difficulty Override setting.

    - Override OFF (use_dynamic=true): Cost = base + dynamic
    - Override ON (use_dynamic=false): Cost = (base + dynamic) × multiplier
    """
```

## Implementation Details

### Modified Files

#### 1. `services/mech/progress_service.py`
**Function**: `requirement_for_level_and_bin(level: int, b: int) -> int`

**Changes**:
- Added ConfigService integration to check evolution mode
- Conditional logic based on `use_dynamic` flag:
  ```python
  if use_dynamic:
      # Dynamic mode: Ignore multiplier
      total = base_cost + dynamic_cost
  else:
      # Static mode: Apply multiplier
      total = int((base_cost + dynamic_cost) * multiplier)
  ```
- Enhanced debug logging to show which mode is active
- Graceful fallback to dynamic mode on errors

### Cost Calculation Examples

**Configuration**:
- Base Cost (Level 1): $10.00
- Dynamic Cost (Bin 1, 1-person channel): $4.00
- Subtotal: $14.00

**Results**:
| Mode | Multiplier | Calculation | Result |
|------|-----------|-------------|--------|
| Dynamic (Override OFF) | 2.0× | $10 + $4 | $14.00 |
| Static (Override ON) | 0.5× | ($10 + $4) × 0.5 | $7.00 |
| Static (Override ON) | 1.0× | ($10 + $4) × 1.0 | $14.00 |
| Static (Override ON) | 2.0× | ($10 + $4) × 2.0 | $28.00 |
| Static (Override ON) | 2.4× | ($10 + $4) × 2.4 | $33.60 |

## Testing

### Test Script
**File**: `test_static_override.py`

**Tests**:
1. ✅ Dynamic mode ignores multiplier (pure community-based costs)
2. ✅ Static mode with 0.5× multiplier (Easy)
3. ✅ Static mode with 2.0× multiplier (Hard)
4. ✅ Static mode with 2.4× multiplier (Very Hard)

**Results**: All tests passed successfully.

## User Flow

### Setting Dynamic Mode (Override OFF)
1. Open Advanced Settings in Web UI
2. Find "Mech Evolution Difficulty" section
3. Toggle "Static Difficulty Override" to **OFF**
4. Costs will now adjust based on Discord community size
5. Multiplier slider is disabled and reset to 1.0×

### Setting Static Mode (Override ON)
1. Open Advanced Settings in Web UI
2. Find "Mech Evolution Difficulty" section
3. Toggle "Static Difficulty Override" to **ON**
4. Adjust slider or click preset buttons (Easy/Normal/Hard)
5. Costs will now use custom multiplier
6. Changes save immediately via API

## API Endpoints

### Get Evolution Mode
**Endpoint**: `GET /api/mech/difficulty`

**Response**:
```json
{
  "success": true,
  "difficulty_multiplier": 1.0,
  "manual_override": false,
  "is_auto": true,
  "current_level": 1,
  "next_level_cost": 14
}
```

### Set Evolution Mode
**Endpoint**: `POST /api/mech/difficulty`

**Request**:
```json
{
  "difficulty_multiplier": 2.0,
  "manual_override": true
}
```

**Response**:
```json
{
  "success": true,
  "message": "Evolution set to static mode with 2.0x difficulty"
}
```

## Integration Points

### Services
- **ConfigService**: Manages `evolution_mode.json` via `get_evolution_mode_service()`
- **MechWebService**: Handles Web UI API requests for difficulty settings
- **ProgressService**: Implements cost calculation with override logic

### Frontend
- **_advanced_settings_modal.html**: UI controls and JavaScript handlers
- **Toggle Handler**: `saveMechOverrideToggle()` - Saves mode changes immediately
- **Slider Handler**: `onSliderChange()` - Auto-enables override when slider moves
- **Preset Buttons**: `setDifficulty(value)` - Quick difficulty selection

## Backward Compatibility

### Fallback Behavior
If ConfigService fails or `evolution_mode.json` is missing:
- System defaults to **dynamic mode** (override OFF)
- No multiplier applied
- Warning logged but operation continues

### Legacy Support
Old `mech_difficulty_multiplier` config field (if exists) is ignored.
System exclusively uses `config/evolution_mode.json`.

## Event Sourcing Compliance

✅ **Compliant**: This feature respects Event Sourcing principles:
- Cost calculation is deterministic based on config state
- No events are modified retroactively
- Snapshot rebuilds use current evolution mode setting
- Mode changes trigger recalculation of next level requirements

## Performance Impact

**Minimal**:
- ConfigService call is cached per request
- Single file read from `evolution_mode.json`
- No database queries required
- Fallback prevents blocking on errors

## Future Enhancements

Potential improvements:
1. Per-level multiplier overrides
2. Community size threshold adjustments
3. Dynamic multiplier schedules (time-based)
4. Discord bot commands for difficulty control
5. Achievement-based difficulty unlocks

## Debugging

### Check Current Mode
```bash
cat config/evolution_mode.json
```

### Test Cost Calculation
```bash
python3 test_static_override.py
```

### View Debug Logs
```bash
# Look for lines containing "Requirement for Level"
grep "Requirement for Level" logs/ddc.log
```

## Summary

The Static Difficulty Override feature successfully integrates with the Hybrid Cost System, allowing users to choose between:
- **Dynamic difficulty**: Automatic scaling based on community size
- **Static difficulty**: Manual control via multiplier slider

The implementation maintains Event Sourcing compliance, includes comprehensive error handling, and has been thoroughly tested.
