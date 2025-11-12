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
        # self.advanced_settings_file = self.config_dir / "advanced_settings.json"  # REMOVED: Use web_config.json instead
        self.web_ui_config_file = self.config_dir / "web_ui.json"
        self.docker_settings_file = self.config_dir / "docker_settings.json"
        # Removed: system_tasks.json is duplicate of tasks.json (used by scheduler service)
        
        # Legacy config file paths (for migration)
        self.bot_config_file = self.config_dir / "bot_config.json"
        self.docker_config_file = self.config_dir / "docker_config.json" 
        self.web_config_file = self.config_dir / "web_config.json"
        self.channels_config_file = self.config_dir / "channels_config.json"
        
        # Legacy v1.1.x config file for migration
        self.legacy_config_file = self.config_dir / "config.json"
        # Alternative location for very old versions
        self.legacy_alt_config = self.config_dir / "config_v1.json"
        
        # Cache and locks
        self._config_cache = {}
        self._cache_timestamps = {}
        self._save_lock = Lock()
        self._cache_lock = Lock()

        # Token encryption cache
        self._token_cache = None
        self._token_cache_hash = None
        
        self._initialized = True
        
        # Initialize modular structure
        self._ensure_modular_structure()
    
    def _ensure_modular_structure(self) -> None:
        """Ensure modular structure exists - perform real migration if needed."""
        try:
            # Check if we need to perform real modular migration
            if self._needs_real_modular_migration():
                logger.info("🔄 Performing automatic modular migration on startup...")
                self._perform_real_modular_migration()
            else:
                logger.debug("Modular structure already exists or no migration needed")
                
        except Exception as e:
            logger.error(f"Error ensuring modular structure: {e}")
            # Fall back to virtual structure if real migration fails
            logger.info("Falling back to virtual modular structure")
    
    def _needs_real_modular_migration(self) -> bool:
        """Check if real modular migration is needed."""
        # Check if we have legacy files but no real modular structure
        has_legacy = (self.channels_config_file.exists() or 
                     self.docker_config_file.exists() or
                     self.bot_config_file.exists())
        
        has_real_modular = (self.channels_dir.exists() and 
                           len(list(self.channels_dir.glob("*.json"))) > 0) or \
                          (self.containers_dir.exists() and 
                           len(list(self.containers_dir.glob("*.json"))) > 0) or \
                          self.main_config_file.exists()
        
        return has_legacy and not has_real_modular
    
    def _perform_real_modular_migration(self) -> None:
        """Perform the real modular migration automatically."""
        try:
            logger.info("🚀 Starting automatic modular config migration...")
            
            # Create backup first
            self._create_migration_backup()
            
            # Create modular directories
            self._create_modular_directories()
            
            # Migrate all configs
            if self.channels_config_file.exists():
                self._migrate_channels_to_files()
                
            if self.docker_config_file.exists():
                self._migrate_containers_to_files()
                
            if self.bot_config_file.exists():
                self._migrate_system_configs_to_files()
                
            if self.web_config_file.exists():
                self._migrate_web_configs_to_files()
                
            # Handle system tasks
            self._migrate_system_tasks()
            
            logger.info("✅ Automatic modular migration completed successfully!")
            logger.info("📁 New structure: channels/, containers/, and modular config files")
            
            # Clean up old JSON files after successful migration
            self._cleanup_legacy_files_after_migration()
            
        except Exception as e:
            logger.error(f"❌ Error during automatic migration: {e}")
            raise
    
    def _create_migration_backup(self) -> None:
        """Create backup of existing config files before migration."""
        import shutil
        from datetime import datetime
        
        backup_dir = self.config_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(exist_ok=True)
        
        # Backup all JSON files
        for json_file in self.config_dir.glob("*.json"):
            if json_file.is_file():
                shutil.copy2(json_file, backup_dir)
        
        logger.info(f"📦 Created backup in: {backup_dir.name}")
    
    def _cleanup_legacy_files_after_migration(self) -> None:
        """Clean up old JSON files after successful migration."""
        try:
            # List of legacy config files to remove after migration
            legacy_files_to_remove = [
                'bot_config.json',
                'docker_config.json', 
                'web_config.json',
                'channels_config.json',
                # 'advanced_settings.json',  # REMOVED: Data is in web_config.json
                'heartbeat.json'
            ]
            
            removed_files = []
            for filename in legacy_files_to_remove:
                file_path = self.config_dir / filename
                if file_path.exists():
                    try:
                        file_path.unlink()  # Delete the file
                        removed_files.append(filename)
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Could not remove {filename}: {e}")
            
            if removed_files:
                logger.info(f"🧹 Cleaned up legacy files: {', '.join(removed_files)}")
                logger.info("   Old JSON files have been automatically removed after successful migration")
            else:
                logger.debug("No legacy files found to clean up")
                
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")
            # Don't fail the migration if cleanup fails
    
    def _create_modular_directories(self) -> None:
        """Create the modular directory structure."""
        self.channels_dir.mkdir(exist_ok=True, parents=True)
        self.containers_dir.mkdir(exist_ok=True, parents=True)
        logger.info("📁 Created modular directories: channels/, containers/")
    
    def _migrate_channels_to_files(self) -> None:
        """Migrate channels_config.json to individual channel files."""
        try:
            channels_data = self._load_json_file(self.channels_config_file, {})
            channel_permissions = channels_data.get("channel_permissions", {})
            
            for channel_id, channel_config in channel_permissions.items():
                channel_file = self.channels_dir / f"{channel_id}.json"
                channel_config["channel_id"] = channel_id
                self._save_json_file(channel_file, channel_config)
                logger.info(f"✅ Migrated channel: {channel_config.get('name', channel_id)}")
            
            # Create default channel config
            default_config = {
                "name": "Default Channel Settings",
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
            
            default_file = self.channels_dir / "default.json"
            self._save_json_file(default_file, default_config)
            
            logger.info(f"✅ Migrated {len(channel_permissions)} channels + default config")
            
        except Exception as e:
            logger.error(f"Error migrating channels to files: {e}")
            raise
    
    def _migrate_containers_to_files(self) -> None:
        """Migrate docker_config.json to individual container files."""
        try:
            docker_data = self._load_json_file(self.docker_config_file, {})
            servers = docker_data.get("servers", [])
            
            for server in servers:
                container_name = server.get("docker_name", server.get("name", "unknown"))
                container_file = self.containers_dir / f"{container_name}.json"
                self._save_json_file(container_file, server)
                logger.info(f"✅ Migrated container: {container_name}")
            
            # Create docker_settings.json with system settings
            docker_settings = {
                "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
                "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
                "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
                "max_log_lines": docker_data.get("max_log_lines", 50)
            }
            
            self._save_json_file(self.docker_settings_file, docker_settings)
            
            logger.info(f"✅ Migrated {len(servers)} containers + docker settings")
            
        except Exception as e:
            logger.error(f"Error migrating containers to files: {e}")
            raise
    
    def _migrate_system_configs_to_files(self) -> None:
        """Migrate bot_config.json to modular system configs."""
        try:
            bot_data = self._load_json_file(self.bot_config_file, {})
            
            # Create main config.json
            main_config = {
                "language": bot_data.get("language", "en"),
                "timezone": bot_data.get("timezone", "UTC"),
                "guild_id": bot_data.get("guild_id"),
                "system_logs": {
                    "level": "INFO",
                    "max_file_size_mb": 10,
                    "backup_count": 5,
                    "enable_debug": False
                }
            }
            self._save_json_file(self.main_config_file, main_config)
            
            # Create heartbeat.json
            heartbeat_config = {
                "heartbeat_channel_id": bot_data.get("heartbeat_channel_id"),
                "enabled": bot_data.get("heartbeat_channel_id") is not None,
                "interval_minutes": 30,
                "message_template": "🤖 DDC Heartbeat - All systems operational"
            }
            self._save_json_file(self.heartbeat_config_file, heartbeat_config)
            
            # Create auth.json
            auth_config = {
                "bot_token": bot_data.get("bot_token"),
                "encryption_enabled": True
            }
            self._save_json_file(self.auth_config_file, auth_config)
            
            logger.info("✅ Migrated system configs (config.json, heartbeat.json, auth.json)")
            
        except Exception as e:
            logger.error(f"Error migrating system configs to files: {e}")
            raise
    
    def _migrate_web_configs_to_files(self) -> None:
        """Migrate web_config.json to modular web configs."""
        try:
            web_data = self._load_json_file(self.web_config_file, {})
            
            # Note: advanced_settings are kept in web_config.json (no separate file)
            # advanced_settings = web_data.get("advanced_settings", {})
            # self._save_json_file(self.advanced_settings_file, advanced_settings)  # REMOVED
            
            # Create clean web_ui.json (without advanced_settings)
            web_ui_config = {
                "web_ui_user": web_data.get("web_ui_user", "admin"),
                "web_ui_password_hash": web_data.get("web_ui_password_hash"),
                "admin_enabled": web_data.get("admin_enabled", True),
                "session_timeout": web_data.get("session_timeout", 3600),
                "donation_disable_key": web_data.get("donation_disable_key", ""),
                "scheduler_debug_mode": web_data.get("scheduler_debug_mode", False)
            }
            self._save_json_file(self.web_ui_config_file, web_ui_config)
            
            logger.info("✅ Migrated web configs (web_ui.json) - advanced_settings kept in web_config.json")
            
        except Exception as e:
            logger.error(f"Error migrating web configs to files: {e}")
            raise
    
    def _migrate_system_tasks(self) -> None:
        """Handle system_tasks.json migration."""
        # REMOVED: system_tasks.json was duplicate of tasks.json - scheduler service uses tasks.json directly
        pass
    
    def _migrate_to_modular_structure(self) -> None:
        """Migrate legacy config files to new modular structure."""
        try:
            logger.info("🔄 Starting migration to modular config structure...")
            
            # Migrate channels
            if self.channels_config_file.exists():
                self._migrate_channels_to_modular()
                
            # Migrate containers 
            if self.docker_config_file.exists():
                self._migrate_containers_to_modular()
                
            # Migrate other config files
            if self.bot_config_file.exists():
                self._migrate_system_configs_to_modular()
                
            if self.web_config_file.exists():
                self._migrate_web_configs_to_modular()
                
            logger.info("✅ Modular migration completed successfully!")
            
        except Exception as e:
            logger.error(f"Error during modular migration: {e}")
            raise
    
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
                # IMPORTANT: Do NOT save to legacy files anymore!
                # The system now uses ONLY modular config structure:
                # - Containers: config/containers/*.json (saved by ConfigurationSaveService)
                # - Channels: config/channels/*.json (saved by ChannelConfigService)
                # - Other settings: config/*.json (main_config, auth, etc.)

                # Legacy files (bot_config.json, docker_config.json, web_config.json, channels_config.json)
                # are NO LONGER USED and should NOT be created!

                logger.info("save_config called - using modular structure only (no legacy files)")

                # Invalidate cache to force reload from modular files
                self._invalidate_cache()

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
    
    def _migrate_legacy_config_if_needed(self) -> None:
        """
        Migrate v1.1.x config.json to v2.0 modular structure.
        Handles both v1.1.3D and earlier versions.
        Only performs migration if needed, safe to call multiple times.
        """
        # Check both possible legacy config locations
        legacy_file = None
        if self.legacy_config_file.exists() and self.legacy_config_file.name == "config.json":
            # Check if it's the old monolithic config (not the new modular config.json)
            try:
                with open(self.legacy_config_file, 'r', encoding='utf-8') as f:
                    test_data = json.load(f)
                    # Old config has servers, new one doesn't
                    if 'servers' in test_data or 'docker_name' in test_data:
                        legacy_file = self.legacy_config_file
            except:
                pass
        elif self.legacy_alt_config.exists():
            legacy_file = self.legacy_alt_config
            
        if not legacy_file:
            return  # No migration needed
        
        logger.info(f"Found legacy v1.1.x config at {legacy_file.name} - performing automatic migration to v2.0")
        
        try:
            # Load legacy config
            with open(legacy_file, 'r', encoding='utf-8') as f:
                legacy_config = json.load(f)
            
            logger.info(f"Migrating v1.1.3D configuration with {len(legacy_config)} settings")
            
            # Split into modular files
            bot_config = self._extract_bot_config(legacy_config)
            docker_config = self._extract_docker_config(legacy_config)  
            web_config = self._extract_web_config(legacy_config)
            channels_config = self._extract_channels_config(legacy_config)
            
            # Only save if we have data for each section
            if bot_config and any(v for v in bot_config.values() if v is not None):
                self._save_json_file(self.bot_config_file, bot_config)
            
            if docker_config:
                self._save_json_file(self.docker_config_file, docker_config)
            
            if web_config and any(v for v in web_config.values() if v is not None):
                self._save_json_file(self.web_config_file, web_config)
            
            if channels_config:
                self._save_json_file(self.channels_config_file, channels_config)
            
            # Create backup of legacy config
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = self.config_dir / f"{legacy_file.name}.v1.1.x.backup_{timestamp}"
            legacy_file.rename(backup_file)
            
            logger.info("✅ v1.1.3D → v2.0 migration completed successfully!")
            logger.info(f"   - Legacy config backed up to: {backup_file.name}")
            logger.info(f"   - Created modular config files: bot_config.json, docker_config.json, web_config.json, channels_config.json")
            
            # Clean up old JSON files after successful migration
            self._cleanup_legacy_files_after_migration()
            
            # Handle password migration for first-time setup
            if legacy_config.get('web_ui_password_hash'):
                logger.info("   - Web UI password migrated successfully")
            else:
                logger.warning("   - No web UI password found in legacy config")
                logger.warning("   - Use /setup or set DDC_ADMIN_PASSWORD for first login")
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            logger.error("Manual migration may be required")
            # Don't fail completely, just log the error
    
    def _invalidate_cache(self) -> None:
        """Clear all caches."""
        with self._cache_lock:
            self._config_cache.clear()
            self._cache_timestamps.clear()
            self._token_cache = None
            self._token_cache_hash = None
    
    # === Configuration Extraction Methods ===
    
    def _extract_bot_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract bot-specific configuration with type safety."""
        try:
            return {
                'bot_token': str(config.get('bot_token', '')) if config.get('bot_token') else None,
                'bot_token_encrypted': str(config.get('bot_token_encrypted', '')) if config.get('bot_token_encrypted') else None,
                'guild_id': str(config.get('guild_id', '')) if config.get('guild_id') else None,
                'language': str(config.get('language', 'en')),
                'timezone': str(config.get('timezone', 'UTC')),
                'heartbeat_channel_id': str(config.get('heartbeat_channel_id', '')) if config.get('heartbeat_channel_id') else None
            }
        except (TypeError, ValueError) as e:
            logger.warning(f"Type conversion error in bot config: {e}")
            return self._get_default_bot_config()
    
    def _extract_docker_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Docker-specific configuration."""
        return {
            'docker_socket_path': config.get('docker_socket_path', '/var/run/docker.sock'),
            'container_command_cooldown': config.get('container_command_cooldown', 5),
            'docker_api_timeout': config.get('docker_api_timeout', 30),
            'max_log_lines': config.get('max_log_lines', 50),
            'servers': list(config.get('servers', [])) if isinstance(config.get('servers'), list) else []
        }
    
    def _extract_web_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract web UI configuration with type safety."""
        try:
            return {
                'web_ui_password_hash': str(config.get('web_ui_password_hash', '')) if isinstance(config.get('web_ui_password_hash'), str) else None,
                'web_ui_user': str(config.get('web_ui_user', 'admin')),
                'admin_enabled': bool(config.get('admin_enabled', True)),
                'session_timeout': int(config.get('session_timeout', 3600)) if isinstance(config.get('session_timeout'), (int, str)) else 3600,
                'donation_disable_key': str(config.get('donation_disable_key', '')),
                'advanced_settings': dict(config.get('advanced_settings', {})) if isinstance(config.get('advanced_settings'), dict) else {}
            }
        except (TypeError, ValueError) as e:
            logger.warning(f"Type conversion error in web config: {e}")
            return self._get_default_web_config()
    
    def _extract_channels_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Discord channels configuration with type safety."""
        try:
            return {
                'channels': dict(config.get('channels', {})) if isinstance(config.get('channels'), dict) else {},
                'server_selection': dict(config.get('server_selection', {})) if isinstance(config.get('server_selection'), dict) else {},
                'server_order': list(config.get('server_order', [])) if isinstance(config.get('server_order'), list) else [],
                'servers': list(config.get('servers', [])) if isinstance(config.get('servers'), list) else [],
                'channel_permissions': dict(config.get('channel_permissions', {})) if isinstance(config.get('channel_permissions'), dict) else {},
                'default_channel_permissions': dict(config.get('default_channel_permissions', self._get_default_channels_config()['default_channel_permissions'])) if isinstance(config.get('default_channel_permissions'), dict) else self._get_default_channels_config()['default_channel_permissions'],
                'spam_protection': dict(config.get('spam_protection', {})) if isinstance(config.get('spam_protection'), dict) else {}
            }
        except (TypeError, ValueError) as e:
            logger.warning(f"Type conversion error in channels config: {e}")
            return self._get_default_channels_config()
    
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
            bot_config = self._load_json_file(self.bot_config_file, self._get_default_bot_config())
            config.update(bot_config)
        
        # Docker configuration  
        if self.docker_config_file.exists():
            docker_config = self._load_json_file(self.docker_config_file, self._get_default_docker_config())
            config.update(docker_config)
        
        # Web configuration
        if self.web_config_file.exists():
            web_config = self._load_json_file(self.web_config_file, self._get_default_web_config())
            config.update(web_config)
        
        # Channels configuration  
        if self.channels_config_file.exists():
            channels_config = self._load_json_file(self.channels_config_file, self._get_default_channels_config())
            config.update(channels_config)
        
        return config
    
    # === Modular Migration Methods ===
    
    def _migrate_channels_to_modular(self) -> None:
        """Migrate channels_config.json to individual channel files."""
        try:
            channels_data = self._load_json_file(self.channels_config_file, {})
            channel_permissions = channels_data.get("channel_permissions", {})
            
            for channel_id, channel_config in channel_permissions.items():
                channel_file = self.channels_dir / f"{channel_id}.json"
                channel_config["channel_id"] = channel_id
                self._save_json_file(channel_file, channel_config)
                logger.info(f"✅ Migrated channel: {channel_config.get('name', channel_id)}")
            
            # Create default channel config
            default_config = {
                "name": "Default Channel Settings",
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
            
            default_file = self.channels_dir / "default.json"
            self._save_json_file(default_file, default_config)
            
            logger.info(f"✅ Migrated {len(channel_permissions)} channels + default config")
            
        except Exception as e:
            logger.error(f"Error migrating channels: {e}")
            raise
    
    def _migrate_containers_to_modular(self) -> None:
        """Migrate docker_config.json to individual container files."""
        try:
            docker_data = self._load_json_file(self.docker_config_file, {})
            servers = docker_data.get("servers", [])
            
            for server in servers:
                container_name = server.get("docker_name", server.get("name", "unknown"))
                container_file = self.containers_dir / f"{container_name}.json"
                self._save_json_file(container_file, server)
                logger.info(f"✅ Migrated container: {container_name}")
            
            # Create docker_settings.json with system settings
            docker_settings = {
                "docker_socket_path": docker_data.get("docker_socket_path", "/var/run/docker.sock"),
                "container_command_cooldown": docker_data.get("container_command_cooldown", 5),
                "docker_api_timeout": docker_data.get("docker_api_timeout", 30),
                "max_log_lines": docker_data.get("max_log_lines", 50)
            }
            
            self._save_json_file(self.docker_settings_file, docker_settings)
            
            logger.info(f"✅ Migrated {len(servers)} containers + docker settings")
            
        except Exception as e:
            logger.error(f"Error migrating containers: {e}")
            raise
    
    def _migrate_system_configs_to_modular(self) -> None:
        """Migrate bot_config.json to modular system configs."""
        try:
            bot_data = self._load_json_file(self.bot_config_file, {})
            
            # Create main config.json
            main_config = {
                "language": bot_data.get("language", "en"),
                "timezone": bot_data.get("timezone", "UTC"),
                "guild_id": bot_data.get("guild_id"),
                "system_logs": {
                    "level": "INFO",
                    "max_file_size_mb": 10,
                    "backup_count": 5,
                    "enable_debug": False
                }
            }
            self._save_json_file(self.main_config_file, main_config)
            
            # Create heartbeat.json
            heartbeat_config = {
                "heartbeat_channel_id": bot_data.get("heartbeat_channel_id"),
                "enabled": bot_data.get("heartbeat_channel_id") is not None,
                "interval_minutes": 30,
                "message_template": "🤖 DDC Heartbeat - All systems operational"
            }
            self._save_json_file(self.heartbeat_config_file, heartbeat_config)
            
            # Create auth.json
            auth_config = {
                "bot_token": bot_data.get("bot_token"),
                "encryption_enabled": True
            }
            self._save_json_file(self.auth_config_file, auth_config)
            
            logger.info("✅ Migrated system configs (config.json, heartbeat.json, auth.json)")
            
        except Exception as e:
            logger.error(f"Error migrating system configs: {e}")
            raise
    
    def _migrate_web_configs_to_modular(self) -> None:
        """Migrate web_config.json to modular web configs."""
        try:
            web_data = self._load_json_file(self.web_config_file, {})
            
            # Note: advanced_settings are kept in web_config.json (no separate file)
            # advanced_settings = web_data.get("advanced_settings", {})
            # self._save_json_file(self.advanced_settings_file, advanced_settings)  # REMOVED
            
            # Create clean web_ui.json (without advanced_settings)
            web_ui_config = {
                "web_ui_user": web_data.get("web_ui_user", "admin"),
                "web_ui_password_hash": web_data.get("web_ui_password_hash"),
                "admin_enabled": web_data.get("admin_enabled", True),
                "session_timeout": web_data.get("session_timeout", 3600),
                "donation_disable_key": web_data.get("donation_disable_key", ""),
                "scheduler_debug_mode": web_data.get("scheduler_debug_mode", False)
            }
            self._save_json_file(self.web_ui_config_file, web_ui_config)
            
            logger.info("✅ Migrated web configs (web_ui.json) - advanced_settings kept in web_config.json")
            
        except Exception as e:
            logger.error(f"Error migrating web configs: {e}")
            raise
    
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
            'max_log_lines': 50,
            'servers': []
        }
    
    def _get_default_web_config(self) -> Dict[str, Any]:
        """Get default web UI configuration."""
        return {
            'web_ui_password_hash': None,
            'web_ui_user': 'admin',
            'admin_enabled': True,
            'session_timeout': 3600,
            'donation_disable_key': '',
            'advanced_settings': {}
        }
    
    def _get_default_channels_config(self) -> Dict[str, Any]:
        """Get default channels configuration."""
        return {
            'channels': {},
            'server_selection': {},
            'server_order': [],
            'channel_permissions': {},
            'spam_protection': {},
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