# SERVICE FIRST Compliance - Action Plan

## Quick Reference

**Overall Compliance**: 78% (GOOD)
**Critical Issues**: 3 (must fix immediately)
**Medium Issues**: 2 (should fix soon)
**Low Issues**: 1 (can defer)

---

## CRITICAL ISSUES - Fix Immediately

### Issue #1: Direct JSON File Access in MechService
**Priority**: HIGH  
**Complexity**: MEDIUM  
**Risk**: LOW (non-breaking if implemented correctly)  
**Time Estimate**: 2-3 hours

#### Problem
- `mech_service._get_evolution_mode()` reads `evolution_mode.json` directly (lines 873-885)
- `mech_service._load_achieved_levels_json()` reads `achieved_levels.json` directly (lines 887-909)  
- `mech_service._save_level_achievement()` writes to JSON directly (lines 926-954)

#### Root Cause
These functions were added before the service-first architecture was fully established.

#### Solution
Create `EvolutionModeService` and `LevelAchievementService` to abstract away config access.

#### Implementation Steps

**Step 1**: Create services/mech/evolution_mode_service.py
```python
# -*- coding: utf-8 -*-
"""Evolution Mode Service - Manages dynamic vs static evolution mode."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class EvolutionModeInfo:
    """Information about current evolution mode."""
    use_dynamic: bool
    difficulty_multiplier: float

@dataclass
class EvolutionModeRequest:
    """Request to get evolution mode."""
    pass

@dataclass
class EvolutionModeResult:
    """Result of evolution mode operation."""
    success: bool
    mode_info: Optional[EvolutionModeInfo] = None
    error: Optional[str] = None

class EvolutionModeService:
    """Service for managing evolution mode (dynamic vs static)."""
    
    def __init__(self, config_path: str = "config/evolution_mode.json"):
        self.config_path = Path(config_path)
        # Use ConfigService for file I/O (SERVICE FIRST)
        from services.config.config_service import get_config_service
        self.config_service = get_config_service()
    
    def get_evolution_mode(self) -> EvolutionModeResult:
        """Get current evolution mode (dynamic or static)."""
        try:
            # Use ConfigService instead of direct file access
            config = self.config_service._load_json_file(
                self.config_path,
                self._get_default_config()
            )
            
            mode_info = EvolutionModeInfo(
                use_dynamic=config.get('use_dynamic', True),
                difficulty_multiplier=config.get('difficulty_multiplier', 1.0)
            )
            
            return EvolutionModeResult(success=True, mode_info=mode_info)
        except Exception as e:
            logger.error(f"Error getting evolution mode: {e}")
            return EvolutionModeResult(
                success=False,
                error=str(e)
            )
    
    def set_evolution_mode(self, use_dynamic: bool, difficulty: float = 1.0) -> EvolutionModeResult:
        """Set evolution mode."""
        try:
            config = {
                'use_dynamic': use_dynamic,
                'difficulty_multiplier': difficulty,
                'last_updated': str(__import__('datetime').datetime.now().isoformat())
            }
            
            # Use ConfigService instead of direct file access
            self.config_service._save_json_file(self.config_path, config)
            
            mode_info = EvolutionModeInfo(
                use_dynamic=use_dynamic,
                difficulty_multiplier=difficulty
            )
            
            logger.info(f"Evolution mode changed: dynamic={use_dynamic}, difficulty={difficulty}")
            return EvolutionModeResult(success=True, mode_info=mode_info)
        except Exception as e:
            logger.error(f"Error setting evolution mode: {e}")
            return EvolutionModeResult(
                success=False,
                error=str(e)
            )
    
    def is_dynamic_mode(self) -> bool:
        """Check if currently in dynamic mode."""
        result = self.get_evolution_mode()
        if result.success and result.mode_info:
            return result.mode_info.use_dynamic
        return True  # Default to dynamic
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default evolution mode config."""
        return {
            'use_dynamic': True,
            'difficulty_multiplier': 1.0
        }

# Singleton instance
_evolution_mode_service_instance = None

def get_evolution_mode_service() -> EvolutionModeService:
    """Get singleton EvolutionModeService instance."""
    global _evolution_mode_service_instance
    if _evolution_mode_service_instance is None:
        _evolution_mode_service_instance = EvolutionModeService()
    return _evolution_mode_service_instance
```

**Step 2**: Create services/mech/level_achievement_service.py
```python
# -*- coding: utf-8 -*-
"""Level Achievement Service - Manages persistent level achievements."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

@dataclass
class LevelAchievementInfo:
    """Information about a level achievement."""
    level: int
    cost_paid: int
    achieved_at: str
    locked: bool = True

@dataclass
class AchievementRequest:
    """Request for achievement operation."""
    pass

@dataclass
class AchievementResult:
    """Result of achievement operation."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class LevelAchievementService:
    """Service for managing persistent level achievements."""
    
    def __init__(self, config_path: str = "config/achieved_levels.json"):
        self.config_path = Path(config_path)
        # Use ConfigService for file I/O (SERVICE FIRST)
        from services.config.config_service import get_config_service
        self.config_service = get_config_service()
    
    def get_current_level(self) -> int:
        """Get current/highest achieved level."""
        try:
            data = self.config_service._load_json_file(
                self.config_path,
                self._get_default_data()
            )
            return data.get('current_level', 1)
        except Exception as e:
            logger.warning(f"Error getting current level: {e}")
            return 1
    
    def save_achievement(self, level: int, total_donated: int, cost_paid: int) -> AchievementResult:
        """Save a new level achievement."""
        try:
            # Load existing data
            data = self.config_service._load_json_file(
                self.config_path,
                self._get_default_data()
            )
            
            # Update achievement
            data['achieved_levels'][str(level)] = {
                'level': level,
                'cost_paid': cost_paid,
                'achieved_at': str(__import__('datetime').datetime.now().isoformat()),
                'locked': True
            }
            
            # Update current level
            data['current_level'] = level
            data['last_updated'] = str(__import__('datetime').datetime.now().isoformat())
            
            # Save using ConfigService
            self.config_service._save_json_file(self.config_path, data)
            
            logger.info(f"Level {level} achievement saved (cost: ${cost_paid})")
            return AchievementResult(success=True, data=data)
        except Exception as e:
            logger.error(f"Error saving achievement: {e}")
            return AchievementResult(success=False, error=str(e))
    
    def get_achievements(self) -> Dict[int, LevelAchievementInfo]:
        """Get all achievements."""
        try:
            data = self.config_service._load_json_file(
                self.config_path,
                self._get_default_data()
            )
            
            achievements = {}
            for level_str, info in data.get('achieved_levels', {}).items():
                level_int = int(level_str)
                achievements[level_int] = LevelAchievementInfo(
                    level=level_int,
                    cost_paid=info.get('cost_paid', 0),
                    achieved_at=info.get('achieved_at', ''),
                    locked=info.get('locked', True)
                )
            return achievements
        except Exception as e:
            logger.error(f"Error getting achievements: {e}")
            return {}
    
    def _get_default_data(self) -> Dict[str, Any]:
        """Get default achievement data."""
        return {
            "current_level": 1,
            "achieved_levels": {
                "1": {
                    "level": 1,
                    "cost_paid": 0,
                    "achieved_at": str(__import__('datetime').datetime.now().isoformat()),
                    "locked": True
                }
            },
            "last_updated": str(__import__('datetime').datetime.now().isoformat())
        }

# Singleton instance
_level_achievement_service_instance = None

def get_level_achievement_service() -> LevelAchievementService:
    """Get singleton LevelAchievementService instance."""
    global _level_achievement_service_instance
    if _level_achievement_service_instance is None:
        _level_achievement_service_instance = LevelAchievementService()
    return _level_achievement_service_instance
```

**Step 3**: Update mech_service.py to use new services
- Replace `_get_evolution_mode()` calls with `get_evolution_mode_service().get_evolution_mode()`
- Replace `_load_achieved_levels_json()` calls with `get_level_achievement_service().get_achievements()`
- Replace `_save_level_achievement()` calls with `get_level_achievement_service().save_achievement()`

**Step 4**: Add to services/mech/__init__.py
```python
from .evolution_mode_service import get_evolution_mode_service
from .level_achievement_service import get_level_achievement_service

__all__ = [
    ...existing...,
    'get_evolution_mode_service',
    'get_level_achievement_service'
]
```

---

### Issue #2: Code Duplication in Speed Calculations  
**Priority**: HIGH  
**Complexity**: LOW  
**Risk**: LOW (local change)  
**Time Estimate**: 1 hour

#### Problem
`speed_levels.py` has identical speed calculation logic in two functions:
- `get_speed_info()` (lines 130-191)
- `get_combined_mech_status()` (lines 279-316)

#### Root Cause
Functions were developed independently and logic was not extracted.

#### Solution
Extract common calculation logic into a single internal function.

#### Implementation Steps

**Step 1**: Add helper function to speed_levels.py
```python
def _calculate_speed_level_from_power(power_amount: float, max_power: int) -> int:
    """
    Single source of truth for speed level calculation.
    
    Args:
        power_amount: Current power amount
        max_power: Maximum power for current evolution level
    
    Returns:
        Speed level (0-101)
    """
    if power_amount <= 0:
        return 0
    
    # Calculate power ratio (capped at 1.0)
    power_ratio = min(1.0, power_amount / max_power)
    
    # Scale to 0-100 range
    return max(1, min(100, int(power_ratio * 100)))
```

**Step 2**: Replace both locations with call to new function
```python
# In get_speed_info():
level = _calculate_speed_level_from_power(donation_amount, max_power_for_level)

# In get_combined_mech_status():
speed_level = _calculate_speed_level_from_power(Power_amount, max_power_for_level)
```

**Step 3**: Keep both public functions unchanged (they call the new helper)

---

### Issue #3: Logging Bug in MechService
**Priority**: HIGH  
**Complexity**: TRIVIAL  
**Risk**: NONE  
**Time Estimate**: 5 minutes

#### Problem
Line 1055 in mech_service.py uses `self.logger` but it doesn't exist:
```python
self.logger.warning(f"MechDecayService failed...")  # self has no logger attribute!
```

#### Solution
Replace with module-level logger:
```python
logger.warning(f"MechDecayService failed...")
```

---

## MEDIUM PRIORITY ISSUES - Fix Soon

### Issue #4: Extract Speed Status Formatting
**Priority**: MEDIUM  
**Complexity**: MEDIUM  
**Risk**: LOW  
**Time Estimate**: 1-2 hours

#### Current State
Speed/status formatting logic is scattered:
- `speed_levels.get_speed_info()`
- `speed_levels.get_combined_mech_status()`
- Cogs that call these functions

#### Solution
Create `MechStatusFormattingService` to consolidate all formatting.

---

### Issue #5: Weak Compatibility Service Abstraction
**Priority**: MEDIUM  
**Complexity**: MEDIUM  
**Risk**: MEDIUM  
**Time Estimate**: 1-2 hours

#### Current State
`mech_compatibility_service.get_store_data()` exposes internal data structure:
```python
store_data = compat_service.get_store_data()  # Returns raw JSON structure
raw_donations = store_data.get('donations', [])
```

#### Solution
Add proper abstraction methods:
```python
def get_donations(self, limit: int = None) -> List[DonationRecord]
def get_donation_stats(self) -> DonationStats
def search_donations(self, query: str) -> List[DonationRecord]
```

---

## SUMMARY OF CHANGES

### Files to Create (3 new services)
1. `services/mech/evolution_mode_service.py`
2. `services/mech/level_achievement_service.py`
3. `services/mech/mech_status_formatting_service.py` (Phase 2)

### Files to Modify (2-3 files)
1. `services/mech/mech_service.py` (remove direct JSON access, add service calls)
2. `services/mech/speed_levels.py` (extract duplicate logic)
3. `services/mech/__init__.py` (export new services)

### Files to Review (no changes needed)
- `services/config/config_service.py` ✓ Already compliant
- `services/donation/unified_donation_service.py` ✓ Already compliant
- `app/blueprints/main_routes.py` ✓ Already compliant
- `services/discord/status_overview_service.py` ✓ Already compliant

---

## TESTING CHECKLIST

After implementing fixes:

- [ ] MechService works with new EvolutionModeService
- [ ] MechService works with new LevelAchievementService
- [ ] Speed level calculation gives same results (test both functions)
- [ ] Evolution mode switching works correctly
- [ ] Level achievements persist correctly
- [ ] No new import errors or circular imports
- [ ] Web UI mech status displays correctly
- [ ] Discord bot status updates work
- [ ] All existing tests still pass
- [ ] No performance regression

---

## DEPLOYMENT PLAN

### Phase 1: Implementation (1-2 hours)
1. Create EvolutionModeService
2. Create LevelAchievementService
3. Update MechService to use new services
4. Fix speed_levels.py duplication
5. Fix logging bug

### Phase 2: Testing (1 hour)
1. Unit test new services
2. Integration test with MechService
3. End-to-end test with Web UI
4. Discord bot testing

### Phase 3: Deployment (< 15 minutes)
1. Commit changes with clear messages
2. Create pull request
3. Code review
4. Merge to main
5. Deploy to Unraid

---

## ROLLBACK PLAN

If issues arise:

1. The changes are non-breaking (services add new methods, don't remove old ones)
2. Can quickly revert by reverting the three commits
3. Config files remain unchanged (no migration needed)
4. All functionality continues to work during rollback

