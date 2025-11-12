# -*- coding: utf-8 -*-
"""
Unified Configuration Service - Single source of truth for all configuration
Replaces: config_loader.py, config_manager.py, unified_config_service.py

REFACTORED: Split into smaller services following Single Responsibility Principle
- ConfigMigrationService: Handles all migration operations
- ConfigValidationService: Handles validation and config extraction
- ConfigCacheService: Handles caching operations
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

# Import refactored services
from .config_migration_service import ConfigMigrationService
from .config_validation_service import ConfigValidationService
from .config_cache_service import ConfigCacheService

# Token encryption constants
_TOKEN_ENCRYPTION_SALT = b'ddc-salt-for-token-encryption-key-v1'
_PBKDF2_ITERATIONS = 260000

logger = logging.getLogger('ddc.config_service')

# SERVICE FIRST: Request/Result patterns
@dataclass(frozen=True)
class GetConfigRequest:
    """Request to get configuration."""
    force_reload: bool = False

@dataclass(frozen=True)
class GetConfigResult:
    """Result containing configuration data."""
    success: bool
    config: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

@dataclass(frozen=True)
class ValidateDonationKeyRequest:
    """Request to validate a donation key."""
    key: str

@dataclass(frozen=True)
class ValidateDonationKeyResult:
    """Result of donation key validation."""
    success: bool
    is_valid: bool = False
    error_message: Optional[str] = None

@dataclass
class GetEvolutionModeRequest:
    """Request to get evolution mode configuration."""
    pass

@dataclass
class GetEvolutionModeResult:
    """Result containing evolution mode configuration."""
    success: bool
    use_dynamic: bool = True
    difficulty_multiplier: float = 1.0
    error: Optional[str] = None

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

        # Modular directories
        self.channels_dir = self.config_dir / "channels"
        self.containers_dir = self.config_dir / "containers"

        # New modular config file paths
        self.main_config_file = self.config_dir / "config.json"
        self.auth_config_file = self.config_dir / "auth.json"
        self.heartbeat_config_file = self.config_dir / "heartbeat.json"
        self.web_ui_config_file = self.config_dir / "web_ui.json"
        self.docker_settings_file = self.config_dir / "docker_settings.json"

        # Legacy config file paths (for migration)
        self.bot_config_file = self.config_dir / "bot_config.json"
        self.docker_config_file = self.config_dir / "docker_config.json"
        self.web_config_file = self.config_dir / "web_config.json"
        self.channels_config_file = self.config_dir / "channels_config.json"

        # Save lock
        self._save_lock = Lock()

        # Initialize refactored services
        self._migration_service = ConfigMigrationService(
            self.config_dir,
            self.channels_dir,
            self.containers_dir
        )
        self._validation_service = ConfigValidationService()
        self._cache_service = ConfigCacheService()

        self._initialized = True

        # Initialize modular structure using migration service
        self._migration_service.ensure_modular_structure(
            self._load_json_file,
            self._save_json_file
        )
    
    
    # === Core Configuration Methods ===
    
    def get_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Get unified configuration from all config files.

        Args:
            force_reload: Force reload from disk, ignore cache

        Returns:
            Complete configuration dictionary
        """
        cache_key = 'unified'

        # Try to get from cache if not force reload
        if not force_reload:
            cached_config = self._cache_service.get_cached_config(cache_key, self.config_dir)
            if cached_config is not None:
                return cached_config

        # Check for v1.1.3D migration first
        self._migrate_legacy_config_if_needed()

        # Load all config files using new modular structure
        config = self._load_modular_config()

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

        # Cache the result using cache service
        self._cache_service.set_cached_config(cache_key, config, self.config_dir)

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
                # IMPORTANT: Do NOT save to legacy files anymore!
                # The system now uses ONLY modular config structure:
                # - Containers: config/containers/*.json (saved by ConfigurationSaveService)
                # - Channels: config/channels/*.json (saved by ChannelConfigService)
                # - Other settings: config/*.json (main_config, auth, etc.)

                # Legacy files (bot_config.json, docker_config.json, web_config.json, channels_config.json)
                # are NO LONGER USED and should NOT be created!

                logger.info("save_config called - using modular structure only (no legacy files)")

                # Invalidate cache using cache service
                self._cache_service.invalidate_cache()

                return ConfigServiceResult(
                    success=True,
                    message="Configuration saved successfully (modular structure)"
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

        # Check cache first using cache service
        cached_token = self._cache_service.get_cached_token(encrypted_token, password_hash)
        if cached_token:
            return cached_token

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

            # Cache successful decryption using cache service
            self._cache_service.set_cached_token(encrypted_token, password_hash, decrypted_token)

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
        if password_hash and not self._validation_service.looks_like_discord_token(token):
            try:
                decrypted = self.decrypt_token(token, password_hash)
                if decrypted and self._validation_service.looks_like_discord_token(decrypted):
                    return decrypted
            except Exception as e:
                logger.error(f"Token decryption failed: {e}")
                return None

        # Return plaintext token as-is if it looks like a Discord token
        return token
    
    def _migrate_legacy_config_if_needed(self) -> None:
        """
        Migrate v1.1.x config.json to v2.0 modular structure.
        Delegates to ConfigMigrationService.
        """
        self._migration_service.migrate_legacy_v1_config_if_needed(
            self._load_json_file,
            self._save_json_file,
            self._validation_service.extract_bot_config,
            self._validation_service.extract_docker_config,
            self._validation_service.extract_web_config,
            self._validation_service.extract_channels_config
        )
    
    
    # === Modular Config Loading ===
    
    def _load_modular_config(self) -> Dict[str, Any]:
        """Load configuration using modular structure (real or virtual)."""
        # Check if we have real modular structure
        if self._has_real_modular_structure():
            return self._load_real_modular_config()
        else:
            # Fall back to virtual modular structure
            return self._load_virtual_modular_config()
    
    def _has_real_modular_structure(self) -> bool:
        """Check if we have real modular file structure."""
        # After consolidation, we only use real modular structure if individual channel/container files exist
        # Main config files alone don't constitute real modular structure anymore
        return ((self.channels_dir.exists() and len(list(self.channels_dir.glob("*.json"))) > 0) or
                (self.containers_dir.exists() and len(list(self.containers_dir.glob("*.json"))) > 0))
    
    def _load_real_modular_config(self) -> Dict[str, Any]:
        """Load configuration from real modular file structure."""
        config = {}
        
        # 1. Load main system config
        if self.main_config_file.exists():
            main_config = self._load_json_file(self.main_config_file, {})
            config.update(main_config)
        
        # 2. Load auth config
        if self.auth_config_file.exists():
            auth_config = self._load_json_file(self.auth_config_file, {})
            config.update(auth_config)
        
        # 3. Load heartbeat config
        if self.heartbeat_config_file.exists():
            heartbeat_config = self._load_json_file(self.heartbeat_config_file, {})
            config.update(heartbeat_config)
        
        # 4. Load web UI config
        if self.web_ui_config_file.exists():
            web_ui_config = self._load_json_file(self.web_ui_config_file, {})
            config.update(web_ui_config)
        
        # 5. Load advanced settings (from web_config.json)
        web_config = self._load_json_file(self.web_config_file, {})
        config['advanced_settings'] = web_config.get('advanced_settings', {})
        
        # 6. Load Docker settings
        if self.docker_settings_file.exists():
            docker_settings = self._load_json_file(self.docker_settings_file, {})
            config.update(docker_settings)
        
        # 7. Load all containers from individual files
        servers = self._load_all_containers_from_files()
        config['servers'] = servers
        
        # 8. Load all channels from individual files
        channel_data = self._load_all_channels_from_files()
        config.update(channel_data)
        
        # 9. Load other existing configs
        self._load_existing_configs_virtual(config)
        
        logger.debug(f"Real modular config loaded: {len(servers)} servers, {len(channel_data.get('channel_permissions', {}))} channels")
        return config
    
    def _load_all_containers_from_files(self) -> list:
        """Load all container configurations from individual files."""
        servers = []

        if not self.containers_dir.exists():
            return servers

        for container_file in self.containers_dir.glob("*.json"):
            try:
                container_config = self._load_json_file(container_file, {})
                # ONLY include containers that are marked as active
                # This respects the "Active" checkbox in the Web UI
                if container_config.get('active', False):
                    servers.append(container_config)
                    logger.debug(f"Loading active container: {container_config.get('container_name', container_file.stem)}")
                else:
                    logger.debug(f"Skipping inactive container: {container_config.get('container_name', container_file.stem)}")
            except Exception as e:
                logger.error(f"Error loading container {container_file}: {e}")

        # Sort by order if available
        servers.sort(key=lambda x: x.get('order', 999))
        logger.info(f"Loaded {len(servers)} active containers for Discord")
        return servers
    
    def _load_all_channels_from_files(self) -> Dict[str, Any]:
        """Load all channel configurations from individual files."""
        channel_data = {
            'channel_permissions': {},
            'default_channel_permissions': {}
        }
        
        if not self.channels_dir.exists():
            return channel_data
        
        for channel_file in self.channels_dir.glob("*.json"):
            try:
                channel_config = self._load_json_file(channel_file, {})
                
                if channel_file.name == "default.json":
                    # Remove fields that don't belong in default
                    default_config = channel_config.copy()
                    default_config.pop('channel_id', None)
                    default_config.pop('name', None)
                    channel_data['default_channel_permissions'] = default_config
                else:
                    # Regular channel
                    channel_id = channel_config.get('channel_id', channel_file.stem)
                    channel_data['channel_permissions'][channel_id] = channel_config
                    
            except Exception as e:
                logger.error(f"Error loading channel {channel_file}: {e}")
        
        return channel_data
    
    def _load_virtual_modular_config(self) -> Dict[str, Any]:
        """Virtual modular config - uses existing files but structured as modular."""
        config = {}
        
        # Load from existing files using the new structure approach
        
        # 1. Bot config (contains: language, timezone, guild_id, bot_token, heartbeat)
        if self.bot_config_file.exists():
            bot_config = self._load_json_file(self.bot_config_file, {})
            
            # Extract system settings (virtual config.json)
            config.update({
                'language': bot_config.get('language', 'en'),
                'timezone': bot_config.get('timezone', 'UTC'),
                'guild_id': bot_config.get('guild_id')
            })
            
            # Extract auth settings (virtual auth.json)
            config.update({
                'bot_token': bot_config.get('bot_token')
            })
            
            # Extract heartbeat settings (virtual heartbeat.json)
            config.update({
                'heartbeat_channel_id': bot_config.get('heartbeat_channel_id')
            })
        
        # 2. Docker config (contains: servers + docker settings)
        if self.docker_config_file.exists():
            docker_config = self._load_json_file(self.docker_config_file, self._get_default_docker_config())
            
            # Extract containers (virtual containers/*.json)  
            config['servers'] = docker_config.get('servers', [])
            
            # Extract docker settings (virtual docker_settings.json)
            config.update({
                'docker_socket_path': docker_config.get('docker_socket_path', '/var/run/docker.sock'),
                'container_command_cooldown': docker_config.get('container_command_cooldown', 5),
                'docker_api_timeout': docker_config.get('docker_api_timeout', 30),
                'max_log_lines': docker_config.get('max_log_lines', 50)
            })
        
        # 3. Web config (contains: web UI + advanced settings)
        if self.web_config_file.exists():
            web_config = self._load_json_file(self.web_config_file, {})
            
            # Extract web UI settings (virtual web_ui.json)
            config.update({
                'web_ui_user': web_config.get('web_ui_user', 'admin'),
                'web_ui_password_hash': web_config.get('web_ui_password_hash'),
                'admin_enabled': web_config.get('admin_enabled', True),
                'session_timeout': web_config.get('session_timeout', 3600),
                'donation_disable_key': web_config.get('donation_disable_key', ''),
                'scheduler_debug_mode': web_config.get('scheduler_debug_mode', False)
            })
            
            # Extract advanced settings (from web_config.json)
            config['advanced_settings'] = web_config.get('advanced_settings', {})
        
        # 4. Channels config (contains: channel permissions + channel data)
        if self.channels_config_file.exists():
            channels_config = self._load_json_file(self.channels_config_file, {})

            # Extract channel data (virtual channels/*.json)
            config['channel_permissions'] = channels_config.get('channel_permissions', {})
            config['default_channel_permissions'] = channels_config.get('default_channel_permissions', {})
            config['channels'] = channels_config.get('channels', {})
            config['server_selection'] = channels_config.get('server_selection', {})
        
        # 5. Load other existing configs
        self._load_existing_configs_virtual(config)
        
        logger.debug("Virtual modular config loaded successfully")
        return config
    
    def _load_existing_configs_virtual(self, config: Dict[str, Any]) -> None:
        """Load existing configs for virtual modular structure."""
        # Load spam protection from channels_config.json
        channels_config = self._load_json_file(self.channels_config_file, {})
        config['spam_protection'] = channels_config.get('spam_protection', {})
        
        # Load server order
        server_order_file = self.config_dir / "server_order.json"
        if server_order_file.exists():
            server_order = self._load_json_file(server_order_file, {})
            config.update(server_order)
        else:
            config['server_order'] = []
        
        # Add missing fields with defaults (if not already loaded from channels_config.json)
        if 'channels' not in config:
            config['channels'] = {}
        if 'server_selection' not in config:
            config['server_selection'] = {}
    
    def _load_all_containers(self) -> list:
        """Load all container configurations from containers/ directory."""
        servers = []
        
        if not self.containers_dir.exists():
            return servers
        
        for container_file in self.containers_dir.glob("*.json"):
            try:
                container_config = self._load_json_file(container_file, {})
                servers.append(container_config)
            except Exception as e:
                logger.error(f"Error loading container {container_file}: {e}")
        
        # Sort by order if available
        servers.sort(key=lambda x: x.get('order', 999))
        return servers
    
    def _load_all_channels(self) -> Dict[str, Any]:
        """Load all channel configurations from channels/ directory."""
        channel_data = {
            'channel_permissions': {},
            'default_channel_permissions': {}
        }
        
        if not self.channels_dir.exists():
            return channel_data
        
        for channel_file in self.channels_dir.glob("*.json"):
            try:
                channel_config = self._load_json_file(channel_file, {})
                
                if channel_file.name == "default.json":
                    # Remove some fields that don't belong in default
                    default_config = channel_config.copy()
                    default_config.pop('channel_id', None)
                    default_config.pop('name', None)
                    channel_data['default_channel_permissions'] = default_config
                else:
                    # Regular channel
                    channel_id = channel_config.get('channel_id', channel_file.stem)
                    channel_data['channel_permissions'][channel_id] = channel_config
                    
            except Exception as e:
                logger.error(f"Error loading channel {channel_file}: {e}")
        
        return channel_data
    
    def _load_existing_configs(self, config: Dict[str, Any]) -> None:
        """Load existing configs that don't need migration."""
        # Load spam protection from channels_config.json
        channels_config = self._load_json_file(self.channels_config_file, {})
        config['spam_protection'] = channels_config.get('spam_protection', {})
        
        # Load server order
        server_order_file = self.config_dir / "server_order.json"
        if server_order_file.exists():
            server_order = self._load_json_file(server_order_file, {})
            config.update(server_order)
        
        # Load system tasks (uses tasks.json directly via scheduler service)
        # REMOVED: system_tasks.json consolidation - scheduler service manages tasks.json directly
    
    def _has_legacy_configs(self) -> bool:
        """Check if legacy config files exist."""
        return (self.bot_config_file.exists() or 
               self.docker_config_file.exists() or
               self.web_config_file.exists() or
               self.channels_config_file.exists())
    
    def _load_legacy_config(self) -> Dict[str, Any]:
        """Load configuration using legacy method (backward compatibility)."""
        config = {}

        # Bot configuration
        if self.bot_config_file.exists():
            bot_config = self._load_json_file(self.bot_config_file, self._validation_service.get_default_bot_config())
            config.update(bot_config)

        # Docker configuration
        if self.docker_config_file.exists():
            docker_config = self._load_json_file(self.docker_config_file, self._validation_service.get_default_docker_config())
            config.update(docker_config)

        # Web configuration
        if self.web_config_file.exists():
            web_config = self._load_json_file(self.web_config_file, self._validation_service.get_default_web_config())
            config.update(web_config)

        # Channels configuration
        if self.channels_config_file.exists():
            channels_config = self._load_json_file(self.channels_config_file, self._validation_service.get_default_channels_config())
            config.update(channels_config)

        return config
    
    

    # === SERVICE FIRST Methods ===

    def get_config_service(self, request: GetConfigRequest) -> GetConfigResult:
        """SERVICE FIRST: Get configuration with Request/Result pattern."""
        try:
            config = self.get_config(force_reload=request.force_reload)
            return GetConfigResult(
                success=True,
                config=config
            )
        except Exception as e:
            logger.error(f"Error getting config via service: {e}", exc_info=True)
            return GetConfigResult(
                success=False,
                error_message=str(e)
            )

    def validate_donation_key_service(self, request: ValidateDonationKeyRequest) -> ValidateDonationKeyResult:
        """SERVICE FIRST: Validate donation key with Request/Result pattern."""
        try:
            # Load current config to check for donation_disable_key
            config = self.get_config()
            stored_key = config.get('donation_disable_key', '').strip()

            if not stored_key:
                # No key set means donations are enabled (valid = False for disable key)
                is_valid = False
            else:
                # Check if provided key matches stored key
                is_valid = request.key.strip() == stored_key

            return ValidateDonationKeyResult(
                success=True,
                is_valid=is_valid
            )
        except Exception as e:
            logger.error(f"Error validating donation key via service: {e}", exc_info=True)
            return ValidateDonationKeyResult(
                success=False,
                error_message=str(e)
            )

    def get_evolution_mode_service(self, request: GetEvolutionModeRequest) -> GetEvolutionModeResult:
        """SERVICE FIRST: Get evolution mode configuration with Request/Result pattern."""
        try:
            # SERVICE FIRST: Use internal helper for consistent file loading
            config_path = Path("config/evolution_mode.json")

            # Default fallback
            default_config = {
                'use_dynamic': True,
                'difficulty_multiplier': 1.0
            }

            # Use internal _load_json_file for consistent error handling
            mode_config = self._load_json_file(config_path, default_config)

            return GetEvolutionModeResult(
                success=True,
                use_dynamic=mode_config.get('use_dynamic', True),
                difficulty_multiplier=mode_config.get('difficulty_multiplier', 1.0)
            )

        except Exception as e:
            logger.error(f"Error getting evolution mode via service: {e}", exc_info=True)
            return GetEvolutionModeResult(
                success=False,
                error=str(e),
                use_dynamic=True,  # Safe default
                difficulty_multiplier=1.0
            )

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

def _parse_servers_from_form(form_data: Dict[str, Any]) -> list:
    """
    Parse container/server configuration from web form data.

    Form fields:
    - selected_servers: list of selected container names
    - display_name_<container>: display name for container
    - allow_status_<container>, allow_start_<container>, etc.: allowed actions
    """
    servers = []

    # DEBUG: Log all form keys to see what we receive
    logger.info(f"[FORM_DEBUG] Form data keys: {list(form_data.keys())[:20]}")  # First 20 keys

    # DEBUG: Log checkbox-related keys specifically
    checkbox_keys = [k for k in form_data.keys() if 'allow_' in k or 'display_' in k]
    logger.info(f"[FORM_DEBUG] Checkbox/display keys: {checkbox_keys[:30]}")

    # DEBUG: Log actual checkbox values
    checkbox_count = 0
    for k in form_data.keys():
        if 'allow_' in k:
            logger.info(f"[FORM_DEBUG] {k} = {repr(form_data.get(k))}")
            checkbox_count += 1
    logger.info(f"[FORM_DEBUG] Total allow_ checkboxes found: {checkbox_count}")

    # Get list of selected containers
    selected_servers = form_data.getlist('selected_servers') if hasattr(form_data, 'getlist') else \
                      (form_data.get('selected_servers') if isinstance(form_data.get('selected_servers'), list) else \
                       [form_data.get('selected_servers')] if form_data.get('selected_servers') else [])

    # Handle the case where selected_servers comes as arrays of duplicates
    # e.g., ['dockerdiscordcontrol', 'dockerdiscordcontrol'] -> ['dockerdiscordcontrol']
    selected_servers_clean = []
    seen = set()
    for server in selected_servers:
        if server not in seen:
            selected_servers_clean.append(server)
            seen.add(server)
    selected_servers = selected_servers_clean

    logger.info(f"[FORM_DEBUG] Selected servers (Active checkboxes): {selected_servers}")

    # DO NOT automatically add containers based on allow_status or other checkboxes
    # ONLY containers with the "Active" checkbox (selected_servers) should be shown in Discord
    # The other checkboxes (Status, Start, Stop, Restart) only control what actions are allowed
    # for ACTIVE containers

    for container_name in selected_servers:
        if not container_name:
            continue

        # Extract display name
        display_name_key = f'display_name_{container_name}'
        display_name_raw = form_data.get(display_name_key, container_name)
        logger.debug(f"[FORM_DEBUG] Raw display_name for {container_name}: {repr(display_name_raw)}")

        # Handle different display_name formats - now as single string!
        display_name = container_name  # Default to container name

        # If it's an array, take first element
        if isinstance(display_name_raw, list) and len(display_name_raw) > 0:
            display_name_raw = display_name_raw[0]

        if isinstance(display_name_raw, str):
            # Clean up any stringified list representations
            if display_name_raw.startswith('[') and display_name_raw.endswith(']'):
                # It's a stringified list like "['Name1', 'Name2']"
                try:
                    import ast
                    parsed_list = ast.literal_eval(display_name_raw)
                    if isinstance(parsed_list, list) and len(parsed_list) > 0:
                        # Take the first element
                        display_name = str(parsed_list[0])
                    else:
                        # Couldn't parse, use raw value
                        display_name = display_name_raw.strip("[]'\"")
                except:
                    # Failed to parse, treat as regular string
                    display_name = display_name_raw.strip("[]'\"")
            else:
                # It's a regular string, use as-is
                display_name = display_name_raw.strip()

        # Ensure we have a valid display name
        if not display_name:
            display_name = container_name

        logger.debug(f"[FORM_DEBUG] Parsed display_name for {container_name}: {display_name}")

        # Extract allowed actions
        allowed_actions = []
        for action in ['status', 'start', 'stop', 'restart']:
            action_key = f'allow_{action}_{container_name}'
            # HTML checkboxes send "on" when checked, or don't exist when unchecked
            # Also handle '1' for compatibility
            value = form_data.get(action_key)
            logger.debug(f"[FORM_DEBUG] Checking {action_key}: value={repr(value)}")

            # Handle arrays (when value comes as ['1', '1'])
            if isinstance(value, list):
                if len(value) > 0:
                    value = value[0]  # Take first element

            # Now check the actual value
            if value in ['1', 'on', True, 'true', 'True']:
                allowed_actions.append(action)
                logger.info(f"[FORM_DEBUG] ✓ Added action {action} for {container_name} (value={repr(value)})")
            elif value == '0':
                logger.debug(f"[FORM_DEBUG] ✗ Action {action} for {container_name} is disabled (value='0')")

        # Extract order value
        order_key = f'order_{container_name}'
        order_value = form_data.get(order_key, 999)
        try:
            order = int(order_value) if order_value else 999
        except (ValueError, TypeError):
            order = 999

        # Build server config
        server_config = {
            'docker_name': container_name,
            'name': container_name,
            'container_name': container_name,
            'display_name': display_name,  # Now a single string!
            'allowed_actions': allowed_actions,
            'allow_detailed_status': True,  # Default to True
            'order': order
        }

        servers.append(server_config)
        logger.info(f"[FORM_DEBUG] Parsed server: {container_name} - actions: {allowed_actions}, order: {order}")

    logger.info(f"[FORM_DEBUG] Total servers parsed: {len(servers)}")
    return servers

def _parse_channel_permissions_from_form(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse channel permissions from the new two-table format.
    Status channels: status_channel_* fields
    Control channels: control_channel_* fields
    """
    channel_permissions = {}

    # Process Status Channels
    status_channel_count = 1
    while True:
        channel_id_key = f'status_channel_id_{status_channel_count}'
        channel_id = form_data.get(channel_id_key, '').strip() if isinstance(form_data.get(channel_id_key), str) else str(form_data.get(channel_id_key, '')).strip()

        if not channel_id:
            # Check if there are more (non-sequential)
            found_more = False
            for i in range(status_channel_count + 1, status_channel_count + 10):
                if form_data.get(f'status_channel_id_{i}'):
                    status_channel_count = i
                    found_more = True
                    break
            if not found_more:
                break
        else:
            # Build channel config for status channel
            channel_config = {
                'name': form_data.get(f'status_channel_name_{status_channel_count}', '').strip() if isinstance(form_data.get(f'status_channel_name_{status_channel_count}'), str) else '',
                'commands': {
                    'serverstatus': True,  # Always enabled for status channels
                    'ss': True,  # Alias for serverstatus
                    'control': False,  # Never enabled for status channels
                    'schedule': False,  # Will be checked against admin users
                    'info': False  # Will be checked against admin users
                },
                'post_initial': form_data.get(f'status_post_initial_{status_channel_count}') in ['1', 'on', True],
                'enable_auto_refresh': form_data.get(f'status_enable_auto_refresh_{status_channel_count}') in ['1', 'on', True],
                'update_interval_minutes': int(form_data.get(f'status_update_interval_minutes_{status_channel_count}', 1) or 1),
                'recreate_messages_on_inactivity': form_data.get(f'status_recreate_messages_{status_channel_count}') in ['1', 'on', True],
                'inactivity_timeout_minutes': int(form_data.get(f'status_inactivity_timeout_{status_channel_count}', 1) or 1)
            }
            channel_permissions[channel_id] = channel_config

        status_channel_count += 1
        if status_channel_count > 50:  # Safety limit
            break

    # Process Control Channels
    control_channel_count = 1
    while True:
        channel_id_key = f'control_channel_id_{control_channel_count}'
        channel_id = form_data.get(channel_id_key, '').strip() if isinstance(form_data.get(channel_id_key), str) else str(form_data.get(channel_id_key, '')).strip()

        if not channel_id:
            # Check if there are more (non-sequential)
            found_more = False
            for i in range(control_channel_count + 1, control_channel_count + 10):
                if form_data.get(f'control_channel_id_{i}'):
                    control_channel_count = i
                    found_more = True
                    break
            if not found_more:
                break
        else:
            # Build channel config for control channel
            channel_config = {
                'name': form_data.get(f'control_channel_name_{control_channel_count}', '').strip() if isinstance(form_data.get(f'control_channel_name_{control_channel_count}'), str) else '',
                'commands': {
                    'serverstatus': True,  # Enabled for control channels
                    'ss': True,  # Alias
                    'control': True,  # Always enabled for control channels
                    'schedule': True,  # Always enabled for control channels
                    'info': True  # Always enabled for control channels
                },
                'post_initial': form_data.get(f'control_post_initial_{control_channel_count}') in ['1', 'on', True],
                'enable_auto_refresh': form_data.get(f'control_enable_auto_refresh_{control_channel_count}') in ['1', 'on', True],
                'update_interval_minutes': int(form_data.get(f'control_update_interval_minutes_{control_channel_count}', 1) or 1),
                'recreate_messages_on_inactivity': form_data.get(f'control_recreate_messages_{control_channel_count}') in ['1', 'on', True],
                'inactivity_timeout_minutes': int(form_data.get(f'control_inactivity_timeout_{control_channel_count}', 1) or 1)
            }
            channel_permissions[channel_id] = channel_config

        control_channel_count += 1
        if control_channel_count > 50:  # Safety limit
            break

    logger.info(f"Parsed {len(channel_permissions)} channel configurations from form")
    return channel_permissions

def process_config_form(form_data: Dict[str, Any], current_config: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Legacy compatibility: Process web form configuration."""
    try:
        # Merge form data with current config
        updated_config = current_config.copy()

        # Parse servers from form data
        servers = _parse_servers_from_form(form_data)
        logger.info(f"[PROCESS_DEBUG] _parse_servers_from_form returned {len(servers)} servers")
        if servers:
            updated_config['servers'] = servers
            logger.info(f"[PROCESS_DEBUG] Added {len(servers)} servers to updated_config")
            # Log first server for debugging
            if servers:
                logger.info(f"[PROCESS_DEBUG] First server: {servers[0].get('docker_name')} with actions: {servers[0].get('allowed_actions')}")
        else:
            logger.warning("[PROCESS_DEBUG] No servers parsed from form data!")

        # Parse channel permissions from the new two-table format
        channel_permissions = _parse_channel_permissions_from_form(form_data)
        if channel_permissions:
            updated_config['channel_permissions'] = channel_permissions
            logger.info(f"[PROCESS_DEBUG] Added {len(channel_permissions)} channel permissions to updated_config")

            # IMPORTANT: Also save to ChannelConfigService for consistency
            try:
                from services.config.channel_config_service import get_channel_config_service
                channel_service = get_channel_config_service()
                channel_service.save_all_channels(channel_permissions)
                logger.info(f"[PROCESS_DEBUG] Saved {len(channel_permissions)} channels via ChannelConfigService")
            except Exception as e:
                logger.error(f"Error saving channels via ChannelConfigService: {e}")

        # Process each form field
        for key, value in form_data.items():
            # Skip server-related fields (already processed above)
            if key in ['selected_servers'] or key.startswith('display_name_') or \
               key.startswith('allow_status_') or key.startswith('allow_start_') or \
               key.startswith('allow_stop_') or key.startswith('allow_restart_'):
                continue

            # Skip channel-related fields (already processed above)
            if key.startswith('status_channel_') or key.startswith('control_channel_') or \
               key.startswith('status_') or key.startswith('control_') or \
               key.startswith('old_status_channel_') or key.startswith('old_control_channel_'):
                continue

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

        # Debug: Log if servers are in the updated config
        if 'servers' in updated_config:
            logger.info(f"[PROCESS_DEBUG] Returning updated_config with {len(updated_config.get('servers', []))} servers")
        else:
            logger.warning("[PROCESS_DEBUG] Returning updated_config WITHOUT servers key!")

        return updated_config, result.success, result.message or "Configuration saved"

    except Exception as e:
        logger.error(f"Error processing config form: {e}")
        return current_config, False, str(e)