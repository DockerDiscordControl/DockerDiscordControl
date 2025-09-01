# -*- coding: utf-8 -*-
"""
Unified Configuration Service - Single source of truth for all configuration
Replaces: config_loader.py, config_manager.py, unified_config_service.py
"""

import os
import json
import base64
import hashlib
import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from threading import Lock
from dataclasses import dataclass, asdict
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from werkzeug.security import generate_password_hash, check_password_hash

# Token encryption constants
_TOKEN_ENCRYPTION_SALT = b'ddc-salt-for-token-encryption-key-v1'
_PBKDF2_ITERATIONS = 260000

logger = logging.getLogger('ddc.config_service')

@dataclass
class ConfigServiceResult:
    """Standard result wrapper for config operations."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None

class ConfigService:
    """
    Unified configuration service - single source of truth for all DDC configuration.
    
    Features:
    - Handles all config files (bot, docker, web, channels)
    - Token encryption/decryption
    - Thread-safe operations
    - Caching with invalidation
    - Legacy compatibility
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ConfigService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        # Directory setup
        self.project_root = Path(__file__).parent.parent.parent
        self.config_dir = self.project_root / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Config file paths
        self.bot_config_file = self.config_dir / "bot_config.json"
        self.docker_config_file = self.config_dir / "docker_config.json" 
        self.web_config_file = self.config_dir / "web_config.json"
        self.channels_config_file = self.config_dir / "channels_config.json"
        
        # Cache and locks
        self._config_cache = {}
        self._cache_timestamps = {}
        self._cache_lock = Lock()
        self._save_lock = Lock()
        
        # Token encryption cache
        self._token_cache = None
        self._token_cache_hash = None
        
        self._initialized = True
    
    # === Core Configuration Methods ===
    
    def get_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Get unified configuration from all config files.
        
        Args:
            force_reload: Force reload from disk, ignore cache
            
        Returns:
            Complete configuration dictionary
        """
        with self._cache_lock:
            cache_key = 'unified'
            current_time = os.path.getmtime(self.config_dir) if self.config_dir.exists() else 0
            
            if (not force_reload and 
                cache_key in self._config_cache and 
                self._cache_timestamps.get(cache_key, 0) >= current_time):
                return self._config_cache[cache_key].copy()
            
            # Load all config files
            config = {}
            
            # Bot configuration
            bot_config = self._load_json_file(self.bot_config_file, self._get_default_bot_config())
            config.update(bot_config)
            
            # Docker configuration  
            docker_config = self._load_json_file(self.docker_config_file, self._get_default_docker_config())
            config.update(docker_config)
            
            # Web configuration
            web_config = self._load_json_file(self.web_config_file, self._get_default_web_config())
            config.update(web_config)
            
            # Channels configuration
            channels_config = self._load_json_file(self.channels_config_file, self._get_default_channels_config())
            config.update(channels_config)
            
            # Decrypt bot token if needed
            if 'bot_token' in config and config['bot_token']:
                logger.debug(f"Attempting to decrypt token: {config['bot_token'][:10]}...")
                decrypted_token = self._decrypt_token_if_needed(config['bot_token'], 
                                                              config.get('web_ui_password_hash'))
                if decrypted_token:
                    logger.info("Successfully decrypted token for usage")
                    config['bot_token_decrypted_for_usage'] = decrypted_token
                else:
                    logger.error("Token decryption failed in get_config()")
            
            # Cache the result
            self._config_cache[cache_key] = config.copy()
            self._cache_timestamps[cache_key] = current_time
            
            return config
    
    def save_config(self, config: Dict[str, Any]) -> ConfigServiceResult:
        """
        Save configuration to appropriate files.
        
        Args:
            config: Configuration dictionary to save
            
        Returns:
            ConfigServiceResult with success status
        """
        with self._save_lock:
            try:
                # Split config into domain-specific files
                bot_config = self._extract_bot_config(config)
                docker_config = self._extract_docker_config(config)
                web_config = self._extract_web_config(config)
                channels_config = self._extract_channels_config(config)
                
                # Save each config file
                self._save_json_file(self.bot_config_file, bot_config)
                self._save_json_file(self.docker_config_file, docker_config)
                self._save_json_file(self.web_config_file, web_config)
                self._save_json_file(self.channels_config_file, channels_config)
                
                # Invalidate cache
                self._invalidate_cache()
                
                return ConfigServiceResult(
                    success=True,
                    message="Configuration saved successfully"
                )
                
            except Exception as e:
                logger.error(f"Error saving configuration: {e}")
                return ConfigServiceResult(
                    success=False,
                    error=str(e)
                )
    
    # === Token Encryption Methods ===
    
    def encrypt_token(self, plaintext_token: str, password_hash: str) -> Optional[str]:
        """Encrypt a Discord bot token using password hash."""
        if not plaintext_token or not password_hash:
            return None
            
        try:
            # Derive encryption key from password hash
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=_TOKEN_ENCRYPTION_SALT,
                iterations=_PBKDF2_ITERATIONS,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password_hash.encode()))
            
            # Encrypt the token
            fernet = Fernet(key)
            encrypted_bytes = fernet.encrypt(plaintext_token.encode())
            return base64.urlsafe_b64encode(encrypted_bytes).decode()
            
        except Exception as e:
            logger.error(f"Token encryption failed: {e}")
            return None
    
    def decrypt_token(self, encrypted_token: str, password_hash: str) -> Optional[str]:
        """Decrypt a Discord bot token using password hash."""
        if not encrypted_token or not password_hash:
            return None
            
        # Check cache first
        cache_key = hashlib.sha256(f"{encrypted_token}{password_hash}".encode()).hexdigest()
        if self._token_cache_hash == cache_key and self._token_cache:
            return self._token_cache
            
        try:
            # Derive decryption key - using same method as old config_manager
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=_TOKEN_ENCRYPTION_SALT,
                iterations=_PBKDF2_ITERATIONS,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password_hash.encode('utf-8')))
            
            # Decrypt the token - use same method as old config_manager
            fernet = Fernet(key)
            decrypted_token_bytes = fernet.decrypt(encrypted_token.encode('utf-8'))
            decrypted_token = decrypted_token_bytes.decode('utf-8')
            
            # Cache successful decryption
            self._token_cache = decrypted_token
            self._token_cache_hash = cache_key
            
            return decrypted_token
            
        except InvalidToken:
            logger.warning("Failed to decrypt token: Invalid token or key (password change?)")
            return None
        except Exception as e:
            logger.error(f"Token decryption failed: {e}")
            return None
    
    # === Private Helper Methods ===
    
    def _load_json_file(self, file_path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """Load JSON file with fallback to defaults."""
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    result = default.copy()
                    result.update(data)
                    return result
            return default.copy()
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return default.copy()
    
    def _save_json_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Save data to JSON file."""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _decrypt_token_if_needed(self, token: str, password_hash: Optional[str]) -> Optional[str]:
        """Decrypt token if it's encrypted, otherwise return as-is."""
        if not token:
            return None
            
        # Check if token is encrypted (starts with base64 pattern or looks like encrypted data)
        # Discord tokens start with specific patterns, encrypted tokens don't
        if password_hash and not self._looks_like_discord_token(token):
            try:
                decrypted = self.decrypt_token(token, password_hash)
                if decrypted and self._looks_like_discord_token(decrypted):
                    return decrypted
            except Exception as e:
                logger.error(f"Token decryption failed: {e}")
                return None
        
        # Return plaintext token as-is if it looks like a Discord token
        return token
    
    def _looks_like_discord_token(self, token: str) -> bool:
        """Check if a token looks like a valid Discord bot token."""
        if not token or len(token) < 50:
            return False
        # Discord bot tokens typically start with certain patterns and contain dots
        # Bot tokens: start with MTA, MTI, etc. (base64 encoded user ID)
        # App tokens: Usually 64+ chars with specific patterns
        return ('.' in token and len(token) > 50) or token.startswith(('MTA', 'MTI', 'MTM', 'MTQ', 'MTU'))
    
    def _invalidate_cache(self) -> None:
        """Clear all caches."""
        with self._cache_lock:
            self._config_cache.clear()
            self._cache_timestamps.clear()
            self._token_cache = None
            self._token_cache_hash = None
    
    # === Configuration Extraction Methods ===
    
    def _extract_bot_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract bot-specific configuration."""
        return {
            'bot_token': config.get('bot_token'),
            'guild_id': config.get('guild_id'),
            'language': config.get('language', 'en'),
            'timezone': config.get('timezone', 'UTC'),
            'heartbeat_channel_id': config.get('heartbeat_channel_id')
        }
    
    def _extract_docker_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Docker-specific configuration."""
        return {
            'docker_socket_path': config.get('docker_socket_path', '/var/run/docker.sock'),
            'container_command_cooldown': config.get('container_command_cooldown', 5),
            'docker_api_timeout': config.get('docker_api_timeout', 30),
            'max_log_lines': config.get('max_log_lines', 50)
        }
    
    def _extract_web_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract web UI configuration."""
        return {
            'web_ui_password_hash': config.get('web_ui_password_hash'),
            'admin_enabled': config.get('admin_enabled', True),
            'session_timeout': config.get('session_timeout', 3600),
            'donation_disable_key': config.get('donation_disable_key', '')
        }
    
    def _extract_channels_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Discord channels configuration."""
        return {
            'channels': config.get('channels', {}),
            'server_selection': config.get('server_selection', {}),
            'server_order': config.get('server_order', []),
            'channel_permissions': config.get('channel_permissions', {}),
            'default_channel_permissions': config.get('default_channel_permissions', 
                                                    self._get_default_channels_config()['default_channel_permissions'])
        }
    
    # === Default Configuration Methods ===
    
    def _get_default_bot_config(self) -> Dict[str, Any]:
        """Get default bot configuration."""
        return {
            'bot_token': None,
            'guild_id': None,
            'language': 'en', 
            'timezone': 'UTC',
            'heartbeat_channel_id': None
        }
    
    def _get_default_docker_config(self) -> Dict[str, Any]:
        """Get default Docker configuration."""
        return {
            'docker_socket_path': '/var/run/docker.sock',
            'container_command_cooldown': 5,
            'docker_api_timeout': 30,
            'max_log_lines': 50
        }
    
    def _get_default_web_config(self) -> Dict[str, Any]:
        """Get default web UI configuration."""
        return {
            'web_ui_password_hash': None,
            'admin_enabled': True,
            'session_timeout': 3600,
            'donation_disable_key': ''
        }
    
    def _get_default_channels_config(self) -> Dict[str, Any]:
        """Get default channels configuration."""
        return {
            'channels': {},
            'server_selection': {},
            'server_order': [],
            'default_channel_permissions': {
                "commands": {
                    "serverstatus": True,
                    "command": False,
                    "control": False,
                    "schedule": False
                },
                "post_initial": False,
                "update_interval_minutes": 10,
                "inactivity_timeout_minutes": 10,
                "enable_auto_refresh": True,
                "recreate_messages_on_inactivity": True
            }
        }

# === Global Service Instance ===

_config_service_instance = None

def get_config_service() -> ConfigService:
    """Get the global configuration service instance."""
    global _config_service_instance
    if _config_service_instance is None:
        _config_service_instance = ConfigService()
    return _config_service_instance

# === Legacy Compatibility Functions ===

def load_config() -> Dict[str, Any]:
    """Legacy compatibility: Load unified configuration."""
    return get_config_service().get_config()

def save_config(config: Dict[str, Any]) -> bool:
    """Legacy compatibility: Save configuration."""
    result = get_config_service().save_config(config)
    return result.success

def process_config_form(form_data: Dict[str, Any], current_config: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Legacy compatibility: Process web form configuration."""
    try:
        # Merge form data with current config
        updated_config = current_config.copy()
        
        # Process each form field
        for key, value in form_data.items():
            if key == 'donation_disable_key':
                # Special handling for donation key
                if isinstance(value, str):
                    value = value.strip()
                    if value:
                        # Validate the key
                        from services.donation.donation_utils import validate_donation_key
                        if validate_donation_key(value):
                            updated_config[key] = value
                        # Invalid keys are silently ignored (not saved)
                    else:
                        # Empty key means remove it (reactivate donations)
                        updated_config.pop(key, None)
                continue
            
            # Handle other form fields
            if isinstance(value, str):
                value = value.strip()
            updated_config[key] = value
        
        # Save the configuration
        result = get_config_service().save_config(updated_config)
        
        return updated_config, result.success, result.message or "Configuration saved"
        
    except Exception as e:
        logger.error(f"Error processing config form: {e}")
        return current_config, False, str(e)