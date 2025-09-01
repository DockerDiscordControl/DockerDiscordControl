# -*- coding: utf-8 -*-
"""
Bot Config Service - Manages Discord bot configuration
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class BotConfig:
    """Immutable bot configuration data structure."""
    bot_token: str
    guild_id: str
    language: str
    timezone: str
    heartbeat_channel_id: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: dict) -> 'BotConfig':
        """Create BotConfig from dictionary data."""
        return cls(
            bot_token=str(data.get('bot_token', '')),
            guild_id=str(data.get('guild_id', '')),
            language=str(data.get('language', 'de')),
            timezone=str(data.get('timezone', 'Europe/Berlin')),
            heartbeat_channel_id=data.get('heartbeat_channel_id')
        )
    
    def to_dict(self) -> dict:
        """Convert BotConfig to dictionary for storage."""
        return {
            'bot_token': self.bot_token,
            'guild_id': self.guild_id,
            'language': self.language,
            'timezone': self.timezone,
            'heartbeat_channel_id': self.heartbeat_channel_id
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[any] = None
    error: Optional[str] = None

class BotConfigService:
    """Clean service for managing bot configuration."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the bot config service."""
        if config_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            config_dir = base_dir / "config"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "bot_config.json"
    
    def get_config(self) -> ServiceResult:
        """Get bot configuration."""
        try:
            if not self.config_file.exists():
                default_config = self._get_default_config()
                return ServiceResult(success=True, data=default_config)
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            config = BotConfig.from_dict(data)
            return ServiceResult(success=True, data=config)
            
        except Exception as e:
            error_msg = f"Error loading bot config: {e}"
            return ServiceResult(success=False, error=error_msg)
    
    def save_config(self, config: BotConfig) -> ServiceResult:
        """Save bot configuration."""
        try:
            # Atomic write
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            temp_file.replace(self.config_file)
            
            return ServiceResult(success=True, data=config)
            
        except Exception as e:
            error_msg = f"Error saving bot config: {e}"
            return ServiceResult(success=False, error=error_msg)
    
    def _get_default_config(self) -> BotConfig:
        """Get default bot configuration."""
        return BotConfig(
            bot_token="",
            guild_id="",
            language="de",
            timezone="Europe/Berlin",
            heartbeat_channel_id=None
        )

# Singleton instance
_bot_config_service = None

def get_bot_config_service() -> BotConfigService:
    """Get the global bot config service instance."""
    global _bot_config_service
    if _bot_config_service is None:
        _bot_config_service = BotConfigService()
    return _bot_config_service