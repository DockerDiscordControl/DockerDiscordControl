# -*- coding: utf-8 -*-
"""
Spam Protection Manager - Manages rate limiting settings for Discord commands
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any
from utils.logging_utils import get_module_logger

logger = get_module_logger('spam_protection_manager')

class SpamProtectionManager:
    """Manages spam protection/rate limiting settings."""
    
    def __init__(self, config_dir: str = "config"):
        """Initialize the spam protection manager.
        
        Args:
            config_dir: Directory where spam_protection.json will be stored
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "spam_protection.json"
        logger.info(f"Spam protection config file: {self.config_file}")
    
    def get_default_settings(self) -> Dict[str, Any]:
        """Get default spam protection settings."""
        return {
            # Command cooldowns (in seconds)
            "command_cooldowns": {
                "control": 5,        # /control command
                "serverstatus": 30,  # /serverstatus and /ss commands
                "info": 5,           # /info command
                "info_edit": 10,     # /info_edit command
                "help": 3,           # /help command
                "ping": 3,           # /ping command
                "donate": 5,         # /donate command
                "donatebroadcast": 60, # /donatebroadcast command
                "task": 10,          # /task command (generic)
                "task_info": 5,      # /task_info command
                "task_once": 10,     # /task_once command
                "task_daily": 10,    # /task_daily command
                "task_weekly": 10,   # /task_weekly command
                "task_monthly": 10,  # /task_monthly command
                "task_yearly": 10,   # /task_yearly command
                "task_delete": 5,    # /task_delete command
                "task_delete_panel": 5,  # /task_delete_panel command
                "task_panel": 10,    # /task_panel command
                "command": 10,       # /command command (container control)
                "ddc": 5,           # /ddc command group
                "language": 30,      # /language command
                "forceupdate": 60,   # /forceupdate command
                "start": 10,         # /start command
                "stop": 10,          # /stop command
                "restart": 10        # /restart command
            },
            
            # Button interaction cooldowns (in seconds)
            "button_cooldowns": {
                "start": 10,         # Start button
                "stop": 10,          # Stop button
                "restart": 15,       # Restart button
                "info": 3,           # Info button
                "refresh": 5,        # Refresh button
                "logs": 10,          # Live Logs button
                "live_refresh": 3,   # Live Logs refresh button
                "auto_refresh": 5    # Auto-refresh toggle button
            },
            
            # Global settings
            "global_settings": {
                "enabled": True,                    # Enable/disable spam protection
                "max_commands_per_minute": 20,      # Max commands per user per minute
                "max_buttons_per_minute": 30,       # Max button clicks per user per minute
                "cooldown_message": True,           # Show cooldown message to users
                "log_violations": True              # Log rate limit violations
            }
        }
    
    def load_settings(self) -> Dict[str, Any]:
        """Load spam protection settings from file.
        
        Returns:
            Dictionary containing spam protection settings
        """
        default_settings = self.get_default_settings()
        
        if not self.config_file.exists():
            logger.info("Spam protection config not found, using defaults")
            # Save defaults to file
            self.save_settings(default_settings)
            return default_settings
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            # Merge with defaults to ensure all keys exist
            for key, default_value in default_settings.items():
                if key not in settings:
                    settings[key] = default_value
                elif isinstance(default_value, dict):
                    # Merge nested dictionaries
                    for sub_key, sub_value in default_value.items():
                        if sub_key not in settings[key]:
                            settings[key][sub_key] = sub_value
            
            logger.debug(f"Loaded spam protection settings: {settings}")
            return settings
            
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading spam protection config: {e}")
            return default_settings
    
    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """Save spam protection settings to file.
        
        Args:
            settings: Dictionary containing spam protection settings
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate settings
            validated_settings = self._validate_settings(settings)
            
            # Save to temporary file first (atomic operation)
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(validated_settings, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_file.rename(self.config_file)
            
            logger.info("Saved spam protection settings")
            return True
            
        except Exception as e:
            logger.error(f"Error saving spam protection settings: {e}")
            return False
    
    def _validate_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize spam protection settings."""
        validated = {}
        defaults = self.get_default_settings()
        
        # Validate command cooldowns
        validated['command_cooldowns'] = {}
        for cmd, cooldown in defaults['command_cooldowns'].items():
            if cmd in settings.get('command_cooldowns', {}):
                value = settings['command_cooldowns'][cmd]
                # Ensure it's a number between 0 and 300 seconds
                if isinstance(value, (int, float)) and 0 <= value <= 300:
                    validated['command_cooldowns'][cmd] = int(value)
                else:
                    validated['command_cooldowns'][cmd] = cooldown
            else:
                validated['command_cooldowns'][cmd] = cooldown
        
        # Validate button cooldowns
        validated['button_cooldowns'] = {}
        for btn, cooldown in defaults['button_cooldowns'].items():
            if btn in settings.get('button_cooldowns', {}):
                value = settings['button_cooldowns'][btn]
                if isinstance(value, (int, float)) and 0 <= value <= 300:
                    validated['button_cooldowns'][btn] = int(value)
                else:
                    validated['button_cooldowns'][btn] = cooldown
            else:
                validated['button_cooldowns'][btn] = cooldown
        
        # Validate global settings
        validated['global_settings'] = {}
        global_defaults = defaults['global_settings']
        global_settings = settings.get('global_settings', {})
        
        validated['global_settings']['enabled'] = bool(global_settings.get('enabled', True))
        validated['global_settings']['cooldown_message'] = bool(global_settings.get('cooldown_message', True))
        validated['global_settings']['log_violations'] = bool(global_settings.get('log_violations', True))
        
        # Validate numeric limits
        max_cmds = global_settings.get('max_commands_per_minute', 20)
        if isinstance(max_cmds, (int, float)) and 1 <= max_cmds <= 100:
            validated['global_settings']['max_commands_per_minute'] = int(max_cmds)
        else:
            validated['global_settings']['max_commands_per_minute'] = 20
            
        max_btns = global_settings.get('max_buttons_per_minute', 30)
        if isinstance(max_btns, (int, float)) and 1 <= max_btns <= 100:
            validated['global_settings']['max_buttons_per_minute'] = int(max_btns)
        else:
            validated['global_settings']['max_buttons_per_minute'] = 30
        
        return validated
    
    def get_command_cooldown(self, command_name: str) -> int:
        """Get cooldown for a specific command.
        
        Args:
            command_name: Name of the command
            
        Returns:
            Cooldown in seconds
        """
        settings = self.load_settings()
        return settings['command_cooldowns'].get(command_name, 5)
    
    def get_button_cooldown(self, button_name: str) -> int:
        """Get cooldown for a specific button.
        
        Args:
            button_name: Name of the button
            
        Returns:
            Cooldown in seconds
        """
        settings = self.load_settings()
        return settings['button_cooldowns'].get(button_name, 5)
    
    def is_enabled(self) -> bool:
        """Check if spam protection is enabled."""
        settings = self.load_settings()
        return settings['global_settings'].get('enabled', True)

# Global instance
_spam_protection_manager = None

def get_spam_protection_manager() -> SpamProtectionManager:
    """Get the global spam protection manager instance.
    
    Returns:
        SpamProtectionManager instance
    """
    global _spam_protection_manager
    if _spam_protection_manager is None:
        _spam_protection_manager = SpamProtectionManager()
    return _spam_protection_manager