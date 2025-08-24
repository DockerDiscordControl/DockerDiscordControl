"""
Mech State Manager - Persists Mech system state across bot restarts
"""
import json
import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class MechStateManager:
    """Manages persistent state for the Mech system"""
    
    def __init__(self, state_file: str = "config/mech_state.json"):
        self.state_file = state_file
        self.state_cache: Dict[str, Any] = {}
        self._ensure_state_file()
        self.load_state()
    
    def _ensure_state_file(self):
        """Ensure state file exists"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            if not os.path.exists(self.state_file):
                self._save_state({
                    "last_glvl_per_channel": {},
                    "mech_expanded_states": {},
                    "last_force_recreate": {},
                    "last_update": None
                })
                logger.info(f"Created new mech state file: {self.state_file}")
        except Exception as e:
            logger.error(f"Error ensuring state file: {e}")
    
    def _save_state(self, state: Dict[str, Any]):
        """Save state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving mech state: {e}")
    
    def load_state(self) -> Dict[str, Any]:
        """Load state from file"""
        try:
            with open(self.state_file, 'r') as f:
                self.state_cache = json.load(f)
                logger.debug(f"Loaded mech state with {len(self.state_cache.get('last_glvl_per_channel', {}))} Glvl entries")
                return self.state_cache
        except Exception as e:
            logger.error(f"Error loading mech state: {e}")
            self.state_cache = {
                "last_glvl_per_channel": {},
                "mech_expanded_states": {},
                "last_force_recreate": {},
                "last_update": None
            }
            return self.state_cache
    
    def get_last_glvl(self, channel_id: int) -> Optional[int]:
        """Get last known Glvl for a channel"""
        return self.state_cache.get("last_glvl_per_channel", {}).get(str(channel_id))
    
    def set_last_glvl(self, channel_id: int, glvl: int):
        """Set last known Glvl for a channel"""
        if "last_glvl_per_channel" not in self.state_cache:
            self.state_cache["last_glvl_per_channel"] = {}
        
        self.state_cache["last_glvl_per_channel"][str(channel_id)] = glvl
        self.state_cache["last_update"] = datetime.now().isoformat()
        self._save_state(self.state_cache)
        logger.debug(f"Saved Glvl {glvl} for channel {channel_id}")
    
    def get_expanded_state(self, channel_id: int) -> bool:
        """Get expanded state for a channel"""
        return self.state_cache.get("mech_expanded_states", {}).get(str(channel_id), False)
    
    def set_expanded_state(self, channel_id: int, expanded: bool):
        """Set expanded state for a channel"""
        if "mech_expanded_states" not in self.state_cache:
            self.state_cache["mech_expanded_states"] = {}
        
        self.state_cache["mech_expanded_states"][str(channel_id)] = expanded
        self.state_cache["last_update"] = datetime.now().isoformat()
        self._save_state(self.state_cache)
        logger.debug(f"Saved expanded state {expanded} for channel {channel_id}")
    
    def should_force_recreate(self, channel_id: int, check_rate_limit: bool = True) -> bool:
        """Check if force_recreate is allowed (rate limiting)"""
        if not check_rate_limit:
            return True
        
        last_recreate = self.state_cache.get("last_force_recreate", {}).get(str(channel_id))
        if not last_recreate:
            return True
        
        try:
            from datetime import datetime, timedelta
            last_time = datetime.fromisoformat(last_recreate)
            # Allow force_recreate every 30 seconds minimum
            if datetime.now() - last_time > timedelta(seconds=30):
                return True
            else:
                logger.debug(f"Rate limiting force_recreate for channel {channel_id}")
                return False
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return True
    
    def mark_force_recreate(self, channel_id: int):
        """Mark that a force_recreate happened"""
        if "last_force_recreate" not in self.state_cache:
            self.state_cache["last_force_recreate"] = {}
        
        self.state_cache["last_force_recreate"][str(channel_id)] = datetime.now().isoformat()
        self._save_state(self.state_cache)
    
    def clear_channel_state(self, channel_id: int):
        """Clear all state for a specific channel"""
        changed = False
        
        channel_str = str(channel_id)
        if channel_str in self.state_cache.get("last_glvl_per_channel", {}):
            del self.state_cache["last_glvl_per_channel"][channel_str]
            changed = True
        
        if channel_str in self.state_cache.get("mech_expanded_states", {}):
            del self.state_cache["mech_expanded_states"][channel_str]
            changed = True
        
        if channel_str in self.state_cache.get("last_force_recreate", {}):
            del self.state_cache["last_force_recreate"][channel_str]
            changed = True
        
        if changed:
            self.state_cache["last_update"] = datetime.now().isoformat()
            self._save_state(self.state_cache)
            logger.info(f"Cleared all mech state for channel {channel_id}")

# Singleton instance
_mech_state_manager: Optional[MechStateManager] = None

def get_mech_state_manager() -> MechStateManager:
    """Get or create the singleton MechStateManager instance"""
    global _mech_state_manager
    if _mech_state_manager is None:
        _mech_state_manager = MechStateManager()
    return _mech_state_manager