# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Minimal Mech State Manager - Simple JSON persistence for Discord bot state
"""
import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MechStateManager:
    """Minimal state manager for Discord bot persistence"""
    
    def __init__(self, state_file: str = "config/mech_state.json"):
        self.state_file = state_file
        self.state_cache: Dict[str, Any] = {}
        self._ensure_state_file()
    
    def _ensure_state_file(self):
        """Ensure state file exists"""
        if not os.path.exists(self.state_file):
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            self.save_state({})
    
    def load_state(self) -> Dict[str, Any]:
        """Load state from file"""
        try:
            with open(self.state_file, 'r') as f:
                self.state_cache = json.load(f)
            return self.state_cache
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(f"Could not load state from {self.state_file}, using empty state")
            return {}
    
    def save_state(self, state: Dict[str, Any]):
        """Save state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            self.state_cache = state
        except (IOError, OSError) as e:
            # File I/O errors (file write)
            logger.error(f"File I/O error saving state: {e}", exc_info=True)
    
    def get_state(self, key: str, default=None):
        """Get specific state value"""
        return self.state_cache.get(key, default)
    
    def set_state(self, key: str, value: Any):
        """Set specific state value and save"""
        self.state_cache[key] = value
        self.save_state(self.state_cache)
    
    def set_expanded_state(self, channel_id: str, expanded: bool):
        """Set expanded state for a channel"""
        if 'mech_expanded_states' not in self.state_cache:
            self.state_cache['mech_expanded_states'] = {}
        self.state_cache['mech_expanded_states'][str(channel_id)] = expanded
        self.save_state(self.state_cache)
    
    def get_expanded_state(self, channel_id: str) -> bool:
        """Get expanded state for a channel"""
        return self.state_cache.get('mech_expanded_states', {}).get(str(channel_id), False)
    
    def set_last_glvl(self, channel_id: str, glvl: int):
        """Set last glvl for a channel"""
        if 'last_glvl_per_channel' not in self.state_cache:
            self.state_cache['last_glvl_per_channel'] = {}
        self.state_cache['last_glvl_per_channel'][str(channel_id)] = glvl
        self.save_state(self.state_cache)
    
    def get_last_glvl(self, channel_id: str) -> int:
        """Get last glvl for a channel"""
        return self.state_cache.get('last_glvl_per_channel', {}).get(str(channel_id), 0)
    
    def should_force_recreate(self, channel_id: str) -> bool:
        """Check if force recreate should be triggered (rate limited)"""
        import time
        current_time = time.time()
        last_recreate = self.state_cache.get('last_force_recreate', {}).get(str(channel_id), 0)
        
        # Rate limit: 30 seconds between force recreates
        return current_time - last_recreate > 30
    
    def mark_force_recreate(self, channel_id: str):
        """Mark that force recreate was triggered"""
        import time
        if 'last_force_recreate' not in self.state_cache:
            self.state_cache['last_force_recreate'] = {}
        self.state_cache['last_force_recreate'][str(channel_id)] = time.time()
        self.save_state(self.state_cache)

# Singleton instance
_mech_state_manager = None

def get_mech_state_manager() -> MechStateManager:
    """Get singleton MechStateManager instance"""
    global _mech_state_manager
    if _mech_state_manager is None:
        _mech_state_manager = MechStateManager()
    return _mech_state_manager
