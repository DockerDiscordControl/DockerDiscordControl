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
from .config_loader_service import ConfigLoaderService
from .config_form_parser_service import ConfigFormParserService

# Import custom exceptions
from services.exceptions import (
    ConfigServiceError, ConfigLoadError, ConfigSaveError,
    TokenEncryptionError, ConfigCacheError, ConfigMigrationError
)

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
        self._loader_service = ConfigLoaderService(
            self.config_dir,
            self.channels_dir,
            self.containers_dir,
            self.main_config_file,
            self.auth_config_file,
            self.heartbeat_config_file,
            self.web_ui_config_file,
            self.docker_settings_file,
            self.bot_config_file,
            self.docker_config_file,
            self.web_config_file,
            self.channels_config_file,
            self._load_json_file,
            self._validation_service
        )

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

        # Load all config files using loader service
        config = self._loader_service.load_modular_config()

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
                try:
                    self._cache_service.invalidate_cache()
                except Exception as cache_error:
                    # Cache invalidation failure is not critical
                    logger.warning(f"Cache invalidation failed (non-critical): {cache_error}")
                    raise ConfigCacheError(
                        "Failed to invalidate config cache",
                        error_code="CACHE_INVALIDATION_FAILED",
                        details={'original_error': str(cache_error)}
                    )

                return ConfigServiceResult(
                    success=True,
                    message="Configuration saved successfully (modular structure)"
                )

            except ConfigCacheError:
                # Re-raise cache errors
                raise
            except Exception as e:
                logger.error(f"Error saving configuration: {e}", exc_info=True)
                raise ConfigSaveError(
                    f"Configuration save failed: {str(e)}",
                    error_code="CONFIG_SAVE_FAILED",
                    details={'config_keys': list(config.keys()) if config else []}
                )
    
    # === Token Encryption Methods ===
    
    def encrypt_token(self, plaintext_token: str, password_hash: str) -> Optional[str]:
        """Encrypt a Discord bot token using password hash."""
        if not plaintext_token or not password_hash:
            logger.warning("encrypt_token called with empty token or password")
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

        except ValueError as e:
            logger.error(f"Token encryption failed - invalid input: {e}", exc_info=True)
            raise TokenEncryptionError(
                "Token encryption failed due to invalid input",
                error_code="ENCRYPTION_INVALID_INPUT",
                details={'error': str(e)}
            )
        except Exception as e:
            logger.error(f"Token encryption failed: {e}", exc_info=True)
            raise TokenEncryptionError(
                f"Token encryption failed: {str(e)}",
                error_code="ENCRYPTION_FAILED",
                details={'error_type': type(e).__name__}
            )
    
    def decrypt_token(self, encrypted_token: str, password_hash: str) -> Optional[str]:
        """Decrypt a Discord bot token using password hash."""
        if not encrypted_token or not password_hash:
            logger.warning("decrypt_token called with empty token or password")
            return None

        # Check cache first using cache service
        try:
            cached_token = self._cache_service.get_cached_token(encrypted_token, password_hash)
            if cached_token:
                logger.debug("Token retrieved from cache")
                return cached_token
        except Exception as cache_error:
            # Cache errors are non-critical, continue with decryption
            logger.warning(f"Token cache lookup failed (non-critical): {cache_error}")

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
            try:
                self._cache_service.set_cached_token(encrypted_token, password_hash, decrypted_token)
            except Exception as cache_error:
                # Cache errors are non-critical
                logger.warning(f"Token cache set failed (non-critical): {cache_error}")

            return decrypted_token

        except InvalidToken as e:
            logger.warning("Failed to decrypt token: Invalid token or key (password change?)")
            raise TokenEncryptionError(
                "Token decryption failed - invalid token or password hash",
                error_code="DECRYPTION_INVALID_TOKEN",
                details={'hint': 'Password may have been changed'}
            )
        except ValueError as e:
            logger.error(f"Token decryption failed - invalid input: {e}", exc_info=True)
            raise TokenEncryptionError(
                "Token decryption failed due to invalid input",
                error_code="DECRYPTION_INVALID_INPUT",
                details={'error': str(e)}
            )
        except Exception as e:
            logger.error(f"Token decryption failed: {e}", exc_info=True)
            raise TokenEncryptionError(
                f"Token decryption failed: {str(e)}",
                error_code="DECRYPTION_FAILED",
                details={'error_type': type(e).__name__}
            )
    
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
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {file_path}: {e}", exc_info=True)
            # Return defaults on JSON parse errors
            return default.copy()
        except IOError as e:
            logger.error(f"I/O error loading {file_path}: {e}", exc_info=True)
            # Return defaults on I/O errors
            return default.copy()
        except Exception as e:
            logger.error(f"Unexpected error loading {file_path}: {e}", exc_info=True)
            # Return defaults on unexpected errors
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
            except TokenEncryptionError as e:
                logger.error(f"Token decryption failed: {e.message}", exc_info=True)
                # Re-raise to propagate structured error
                raise
            except Exception as e:
                logger.error(f"Unexpected error during token decryption: {e}", exc_info=True)
                raise TokenEncryptionError(
                    f"Unexpected token decryption error: {str(e)}",
                    error_code="DECRYPTION_UNEXPECTED_ERROR",
                    details={'error_type': type(e).__name__}
                )

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
    
    

    # === SERVICE FIRST Methods ===

    def get_config_service(self, request: GetConfigRequest) -> GetConfigResult:
        """SERVICE FIRST: Get configuration with Request/Result pattern."""
        try:
            config = self.get_config(force_reload=request.force_reload)
            return GetConfigResult(
                success=True,
                config=config
            )
        except ConfigLoadError as e:
            logger.error(f"Config load error via service: {e.message}", exc_info=True)
            return GetConfigResult(
                success=False,
                error_message=e.message
            )
        except ConfigCacheError as e:
            logger.warning(f"Config cache error (non-critical): {e.message}")
            # Try to load without cache
            try:
                config = self.get_config(force_reload=True)
                return GetConfigResult(
                    success=True,
                    config=config
                )
            except Exception as retry_error:
                logger.error(f"Retry after cache error failed: {retry_error}", exc_info=True)
                return GetConfigResult(
                    success=False,
                    error_message=f"Failed to load config after cache error: {str(retry_error)}"
                )
        except Exception as e:
            logger.error(f"Unexpected error getting config via service: {e}", exc_info=True)
            return GetConfigResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}"
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
        except ConfigLoadError as e:
            logger.error(f"Failed to load config for donation key validation: {e.message}", exc_info=True)
            return ValidateDonationKeyResult(
                success=False,
                error_message=f"Config load failed: {e.message}"
            )
        except Exception as e:
            logger.error(f"Unexpected error validating donation key: {e}", exc_info=True)
            return ValidateDonationKeyResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}"
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
            # Note: _load_json_file already handles JSON/IO errors and returns defaults
            mode_config = self._load_json_file(config_path, default_config)

            return GetEvolutionModeResult(
                success=True,
                use_dynamic=mode_config.get('use_dynamic', True),
                difficulty_multiplier=mode_config.get('difficulty_multiplier', 1.0)
            )

        except ConfigLoadError as e:
            logger.error(f"Failed to load evolution mode config: {e.message}", exc_info=True)
            # Return safe defaults on config load error
            return GetEvolutionModeResult(
                success=False,
                error=e.message,
                use_dynamic=True,  # Safe default
                difficulty_multiplier=1.0
            )
        except Exception as e:
            logger.error(f"Unexpected error getting evolution mode: {e}", exc_info=True)
            # Return safe defaults on unexpected error
            return GetEvolutionModeResult(
                success=False,
                error=f"Unexpected error: {str(e)}",
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

# === Form Parsing Functions (delegated to ConfigFormParserService) ===

def _parse_servers_from_form(form_data: Dict[str, Any]) -> list:
    """Legacy wrapper: Delegate to ConfigFormParserService."""
    return ConfigFormParserService.parse_servers_from_form(form_data)

def _parse_channel_permissions_from_form(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy wrapper: Delegate to ConfigFormParserService."""
    return ConfigFormParserService.parse_channel_permissions_from_form(form_data)

def process_config_form(form_data: Dict[str, Any], current_config: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Legacy wrapper: Delegate to ConfigFormParserService."""
    return ConfigFormParserService.process_config_form(form_data, current_config, get_config_service())