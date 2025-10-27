# -*- coding: utf-8 -*-
"""
Spam Protection Service - Clean service architecture for rate limiting and spam protection
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional
from utils.logging_utils import get_module_logger

logger = get_module_logger('spam_protection_service')

@dataclass(frozen=True)
class SpamProtectionConfig:
    """Immutable spam protection configuration data structure."""
    command_cooldowns: Dict[str, int]
    button_cooldowns: Dict[str, int]
    global_enabled: bool
    max_commands_per_minute: int
    max_buttons_per_minute: int
    cooldown_message: bool
    log_violations: bool
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SpamProtectionConfig':
        """Create SpamProtectionConfig from dictionary data."""
        return cls(
            command_cooldowns=dict(data.get('command_cooldowns', {})),
            button_cooldowns=dict(data.get('button_cooldowns', {})),
            global_enabled=bool(data.get('global_settings', {}).get('enabled', True)),
            max_commands_per_minute=int(data.get('global_settings', {}).get('max_commands_per_minute', 20)),
            max_buttons_per_minute=int(data.get('global_settings', {}).get('max_buttons_per_minute', 30)),
            cooldown_message=bool(data.get('global_settings', {}).get('cooldown_message', True)),
            log_violations=bool(data.get('global_settings', {}).get('log_violations', True))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert SpamProtectionConfig to dictionary for storage."""
        return {
            'command_cooldowns': self.command_cooldowns,
            'button_cooldowns': self.button_cooldowns,
            'global_settings': {
                'enabled': self.global_enabled,
                'max_commands_per_minute': self.max_commands_per_minute,
                'max_buttons_per_minute': self.max_buttons_per_minute,
                'cooldown_message': self.cooldown_message,
                'log_violations': self.log_violations
            }
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class SpamProtectionService:
    """Clean service for managing spam protection and rate limiting."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the spam protection service.
        
        Args:
            config_dir: Directory to store config files. Defaults to config/
        """
        if config_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            config_dir = base_dir / "config"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Updated: Use channels_config.json as single source for spam protection
        self.config_file = self.config_dir / "channels_config.json"
        
        # In-memory cooldown tracking
        self._user_cooldowns: Dict[str, float] = {}
        
        logger.info(f"Spam protection service initialized: {self.config_dir}")
    
    def get_config(self) -> ServiceResult:
        """Get spam protection configuration from channels_config.json.

        Returns:
            ServiceResult with SpamProtectionConfig data or error
        """
        try:
            if not self.config_file.exists():
                # Return default config
                default_config = self._get_default_config()
                return ServiceResult(success=True, data=default_config)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                channels_data = json.load(f)

            # Extract spam_protection section from channels_config.json
            spam_data = channels_data.get('spam_protection', {})
            config = SpamProtectionConfig.from_dict(spam_data)
            return ServiceResult(success=True, data=config)
            
        except Exception as e:
            error_msg = f"Error loading spam protection config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def save_config(self, config: SpamProtectionConfig) -> ServiceResult:
        """Save spam protection configuration to channels_config.json.

        Args:
            config: SpamProtectionConfig to save

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            # Load existing channels_config.json
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    channels_data = json.load(f)
            else:
                channels_data = {}

            # Update spam_protection section
            channels_data['spam_protection'] = config.to_dict()

            # Atomic write
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(channels_data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.config_file)

            logger.info("Saved spam protection configuration to channels_config.json")
            return ServiceResult(success=True, data=config)
            
        except Exception as e:
            error_msg = f"Error saving spam protection config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def is_enabled(self) -> bool:
        """Check if spam protection is enabled."""
        config_result = self.get_config()
        if config_result.success:
            return config_result.data.global_enabled
        return True  # Default to enabled if config can't be loaded
    
    def get_command_cooldown(self, command_name: str) -> int:
        """Get cooldown for a specific command."""
        config_result = self.get_config()
        if config_result.success:
            return config_result.data.command_cooldowns.get(command_name, 5)
        return 5
    
    def get_button_cooldown(self, button_name: str) -> int:
        """Get cooldown for a specific button."""
        config_result = self.get_config()
        if config_result.success:
            # Check for exact match first
            if button_name in config_result.data.button_cooldowns:
                return config_result.data.button_cooldowns[button_name]

            # Check for Mech button patterns (e.g., mech_donate_123456 -> mech_donate)
            if button_name.startswith('mech_'):
                parts = button_name.split('_')
                if len(parts) >= 2:
                    # Try patterns like mech_expand_channelid -> mech_expand
                    pattern = f"{parts[0]}_{parts[1]}"
                    if pattern in config_result.data.button_cooldowns:
                        return config_result.data.button_cooldowns[pattern]

            # Default cooldown
            return 5
        return 5
    
    def load_settings(self) -> ServiceResult:
        """Reload spam protection settings from config file.
        
        This method provides compatibility with the old manager interface.
        The service automatically loads settings on each access, so this just
        forces a config reload and returns the result.
        
        Returns:
            ServiceResult indicating success or failure
        """
        return self.get_config()
    
    def is_on_cooldown(self, user_id: int, action_type: str) -> bool:
        """Check if user is on cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Type of action (command or button name)

        Returns:
            True if user is on cooldown, False otherwise
        """
        if not self.is_enabled():
            return False

        cooldown_key = f"{user_id}:{action_type}"
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        current_time = time.time()

        # Get appropriate cooldown duration
        # Check if it's a command first
        if action_type in ['serverstatus', 'ss', 'control', 'info', 'help', 'ping', 'donate', 'command', 'language', 'forceupdate', 'start', 'stop', 'restart']:
            cooldown_duration = self.get_command_cooldown(action_type)
        else:
            # It's a button (including Mech buttons)
            cooldown_duration = self.get_button_cooldown(action_type)

        return (current_time - last_used) < cooldown_duration
    
    def get_remaining_cooldown(self, user_id: int, action_type: str) -> float:
        """Get remaining cooldown time for user action.

        Args:
            user_id: Discord user ID
            action_type: Type of action (command or button name)

        Returns:
            Remaining cooldown time in seconds
        """
        if not self.is_enabled():
            return 0.0

        cooldown_key = f"{user_id}:{action_type}"
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        current_time = time.time()

        # Get appropriate cooldown duration
        # Check if it's a command first
        if action_type in ['serverstatus', 'ss', 'control', 'info', 'help', 'ping', 'donate', 'command', 'language', 'forceupdate', 'start', 'stop', 'restart']:
            cooldown_duration = self.get_command_cooldown(action_type)
        else:
            # It's a button (including Mech buttons)
            cooldown_duration = self.get_button_cooldown(action_type)

        remaining = cooldown_duration - (current_time - last_used)
        return max(0.0, remaining)
    
    def add_user_cooldown(self, user_id: int, action_type: str) -> None:
        """Add user to cooldown for specific action.
        
        Args:
            user_id: Discord user ID
            action_type: Type of action (command or button name)
        """
        if not self.is_enabled():
            return
        
        cooldown_key = f"{user_id}:{action_type}"
        self._user_cooldowns[cooldown_key] = time.time()
        
        # Clean old cooldowns (older than 5 minutes)
        current_time = time.time()
        old_keys = [key for key, timestamp in self._user_cooldowns.items() 
                   if current_time - timestamp > 300]
        for key in old_keys:
            del self._user_cooldowns[key]
    
    def _get_default_config(self) -> SpamProtectionConfig:
        """Get default spam protection configuration."""
        return SpamProtectionConfig(
            command_cooldowns={
                "control": 5,
                "serverstatus": 30,
                "info": 5,
                "info_edit": 10,
                "help": 3,
                "ping": 3,
                "donate": 5,
                "donatebroadcast": 60,
                "command": 5,
                "language": 30,
                "forceupdate": 60,
                "start": 10,
                "stop": 10,
                "restart": 15
            },
            button_cooldowns={
                "start": 10,
                "stop": 10,
                "restart": 20,
                "info": 3,
                "refresh": 5,
                "logs": 10,
                "live_refresh": 5,
                "auto_refresh": 5,
                "mech_expand": 3,
                "mech_collapse": 2,
                "mech_donate": 10,
                "mech_history": 5,
                "mech_display": 3,
                "mech_story": 5,
                "mech_music": 8
            },
            global_enabled=True,
            max_commands_per_minute=20,
            max_buttons_per_minute=35,
            cooldown_message=True,
            log_violations=True
        )

# Singleton instance
_spam_protection_service = None

def get_spam_protection_service() -> SpamProtectionService:
    """Get the global spam protection service instance.
    
    Returns:
        SpamProtectionService instance
    """
    global _spam_protection_service
    if _spam_protection_service is None:
        _spam_protection_service = SpamProtectionService()
    return _spam_protection_service