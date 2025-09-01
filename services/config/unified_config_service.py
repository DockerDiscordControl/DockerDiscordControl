# -*- coding: utf-8 -*-
"""
Unified Config Service - Simple config service without logging dependencies
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

from .bot_config_service import get_bot_config_service, BotConfig
from .docker_config_service import get_docker_config_service, DockerConfig

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[any] = None
    error: Optional[str] = None

class UnifiedConfigService:
    """Simplified unified config service for legacy compatibility."""
    
    def __init__(self):
        """Initialize without logging to avoid circular dependency."""
        self.config_dir = Path(__file__).parent.parent.parent / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Legacy config files
        self.bot_config_file = self.config_dir / "bot_config.json"
        self.docker_config_file = self.config_dir / "docker_config.json"
        self.channels_config_file = self.config_dir / "channels_config.json"
        self.web_config_file = self.config_dir / "web_config.json"
        
        self._config_cache = None
        self._cache_timestamp = 0
    
    def get_legacy_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """Get configuration in legacy format."""
        try:
            # Simple file-based loading without complex caching
            config = {}
            
            # Load bot config
            if self.bot_config_file.exists():
                with open(self.bot_config_file, 'r', encoding='utf-8') as f:
                    config.update(json.load(f))
            
            # Load docker config  
            if self.docker_config_file.exists():
                with open(self.docker_config_file, 'r', encoding='utf-8') as f:
                    docker_data = json.load(f)
                    config.update(docker_data)
            
            # Load channels config
            if self.channels_config_file.exists():
                with open(self.channels_config_file, 'r', encoding='utf-8') as f:
                    channels_data = json.load(f)
                    config.update(channels_data)
            
            # Load web config
            if self.web_config_file.exists():
                with open(self.web_config_file, 'r', encoding='utf-8') as f:
                    web_data = json.load(f) 
                    config.update(web_data)
            
            # Ensure required keys exist with defaults
            config.setdefault('language', 'de')
            config.setdefault('timezone', 'Europe/Berlin')
            config.setdefault('servers', [])
            config.setdefault('channel_permissions', {})
            config.setdefault('scheduler_debug_mode', False)
            
            return config
            
        except Exception as e:
            print(f"Error loading unified config: {e}")
            return self._get_fallback_config()
    
    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """Save configuration by splitting into domain files."""
        try:
            success_count = 0
            
            # Save bot config
            bot_data = {
                'bot_token': config_data.get('bot_token', ''),
                'guild_id': config_data.get('guild_id', ''),
                'language': config_data.get('language', 'de'),
                'timezone': config_data.get('timezone', 'Europe/Berlin'),
                'heartbeat_channel_id': config_data.get('heartbeat_channel_id')
            }
            if self._save_json_file(self.bot_config_file, bot_data):
                success_count += 1
            
            # Save docker config
            docker_data = {
                'servers': config_data.get('servers', [])
            }
            if self._save_json_file(self.docker_config_file, docker_data):
                success_count += 1
            
            # Save channels config
            channels_data = {
                'channel_permissions': config_data.get('channel_permissions', {})
            }
            if self._save_json_file(self.channels_config_file, channels_data):
                success_count += 1
            
            # Save web config
            web_data = {
                'web_ui_user': config_data.get('web_ui_user', 'admin'),
                'web_ui_password_hash': config_data.get('web_ui_password_hash', ''),
                'scheduler_debug_mode': config_data.get('scheduler_debug_mode', False),
                'advanced_settings': config_data.get('advanced_settings', {})
            }
            if self._save_json_file(self.web_config_file, web_data):
                success_count += 1
            
            return success_count > 0
            
        except Exception as e:
            print(f"Error saving unified config: {e}")
            return False
    
    def get_server_config(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific server."""
        config = self.get_legacy_config()
        servers = config.get('servers', [])
        
        for server in servers:
            if server.get('name') == server_name:
                return server
        
        return None
    
    def update_server_config(self, server_name: str, new_config_data: Dict[str, Any]) -> bool:
        """Update configuration for a specific server."""
        config = self.get_legacy_config()
        servers = config.get('servers', [])
        
        # Find and update server
        for i, server in enumerate(servers):
            if server.get('name') == server_name:
                servers[i] = {**server, **new_config_data}
                config['servers'] = servers
                return self.save_config(config)
        
        return False
    
    def _save_json_file(self, file_path: Path, data: Dict[str, Any]) -> bool:
        """Save JSON data to file atomically."""
        try:
            temp_file = file_path.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_file.replace(file_path)
            return True
        except Exception:
            return False
    
    def _get_fallback_config(self) -> Dict[str, Any]:
        """Get fallback configuration when loading fails."""
        return {
            "bot_token": "",
            "guild_id": "",
            "language": "de",
            "timezone": "Europe/Berlin",
            "servers": [],
            "channel_permissions": {},
            "web_ui_user": "admin",
            "web_ui_password_hash": "",
            "scheduler_debug_mode": False,
            "advanced_settings": {}
        }

# Singleton instance
_unified_config_service = None

def get_unified_config_service() -> UnifiedConfigService:
    """Get the global unified config service instance."""
    global _unified_config_service
    if _unified_config_service is None:
        _unified_config_service = UnifiedConfigService()
    return _unified_config_service