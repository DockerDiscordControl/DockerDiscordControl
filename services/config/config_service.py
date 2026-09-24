# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
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
import shutil
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from threading import Lock, RLock
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
_PBKDF2_ITERATIONS = 600000

# Web UI password hashing scheme (verified by app/auth.py via check_password_hash)
_PASSWORD_HASH_METHOD = "pbkdf2:sha256:600000"
# Same minimum length the first-run setup flow enforces (main_routes /setup)
MIN_WEB_UI_PASSWORD_LENGTH = 12

# Keys that get_config() adds at runtime. They must never be written back to
# config.json - the decrypted token would otherwise end up on disk in plaintext.
# 'config_read_errors' reports that a configuration file could not be parsed -
# saved, it would be a statement about a long-gone state.
_RUNTIME_ONLY_CONFIG_KEYS = ('bot_token_decrypted_for_usage', 'config_read_errors')

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
class SetEvolutionModeRequest:
    """Request to persist evolution mode configuration.

    use_dynamic=True  -> community-based pricing, the multiplier is ignored
    use_dynamic=False -> static override, the requirement is multiplied
    """
    use_dynamic: bool
    difficulty_multiplier: float = 1.0

@dataclass
class SetEvolutionModeResult:
    """Result of persisting evolution mode configuration."""
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

def _difficulty_in_range(value, minimum: float, maximum: float) -> float:
    """The stored difficulty multiplier, or 1.0 when it is not usable.

    Writing it is bounds-checked; reading it was not, so a 0 from a hand-edited
    evolution_mode.json made every level cost nothing and one cent walked the
    mech from level 1 to 11.
    """
    try:
        multiplier = float(value)
    except (TypeError, ValueError):
        logger.warning("difficulty_multiplier is not a number (%r) - using 1.0", value)
        return 1.0
    if not (minimum <= multiplier <= maximum):
        logger.warning("difficulty_multiplier %s is outside %s..%s - using 1.0",
                       multiplier, minimum, maximum)
        return 1.0
    return multiplier


class ConfigService:
    """Unified configuration service - single source of truth for all DDC configuration.

    This service provides centralized configuration management for DockerDiscordControl.
    It handles loading from multiple sources, token encryption, caching, and thread-safe
    operations.

    Features:
        * Modular configuration loading (containers, channels, settings)
        * Token encryption/decryption with PBKDF2
        * Thread-safe operations with locks
        * Configuration caching with automatic invalidation
        * Legacy v1.x compatibility layer
        * Migration support for old configurations

    The service is implemented as a singleton - use :func:`get_config_service` to get the
    instance instead of creating it directly.

    Example:
        >>> from services.config.config_service import get_config_service
        >>> config_service = get_config_service()
        >>> config = config_service.get_config()
        >>> print(f"Guild: {config['guild_id']}")
        >>> print(f"Servers: {len(config['servers'])} containers")

    Thread Safety:
        All public methods are thread-safe. Internal state is protected by locks.

    See Also:
        * :class:`ConfigLoaderService` - Configuration loading operations
        * :class:`ConfigCacheService` - Configuration caching
        * :class:`ConfigMigrationService` - Configuration migration
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

        # Directory setup. ``DDC_CONFIG_DIR`` lets tests (and special
        # deployments) point the service at an alternative writable
        # directory without monkey-patching the singleton - resolved in
        # utils/config_paths.py, the one place that knows the rule.
        from utils.config_paths import get_config_dir
        self.project_root = Path(__file__).parent.parent.parent
        self.config_dir = get_config_dir()
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Read-only mount (e.g., dev SMB share). Treat as best-effort —
            # the caller will surface a sane error if the dir really is
            # required for the current operation.
            pass

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

        # An RLock, so a read-modify-write can hold it across its own
        # save_config call - see the spec test of update_config_fields.
        self._save_lock = RLock()

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

        # One-time upgrade step: legacy settings files -> config.json (single source)
        self._fold_legacy_settings_once()


    # === Core Configuration Methods ===

    def get_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """Get unified configuration from all config files.

        Loads configuration from multiple sources and combines them into a single
        dictionary. Uses caching for performance - set force_reload=True to bypass.

        The configuration is loaded from:
            * System settings (config/config.json)
            * Authentication (config/auth.json)
            * Heartbeat settings (config/heartbeat.json)
            * Web UI settings (config/web_ui.json)
            * Docker settings (config/docker_settings.json)
            * Containers (config/containers/*.json - only active ones)
            * Channels (config/channels/*.json)

        Args:
            force_reload (bool): If True, bypass cache and reload from disk.
                Defaults to False for better performance.

        Returns:
            Dict[str, Any]: Complete configuration dictionary containing all settings.
                Key structure includes:

                * 'language': Language code (e.g., 'de', 'en')
                * 'timezone': Timezone string (e.g., 'Europe/Berlin')
                * 'guild_id': Discord guild ID
                * 'bot_token': Encrypted Discord bot token
                * 'servers': List of active container configurations
                * 'channel_permissions': Channel-specific settings
                * 'docker_socket_path': Path to Docker socket
                * And many more settings...

        Raises:
            ConfigLoadError: If configuration files cannot be loaded
            ConfigCacheError: If cache operations fail (non-critical)

        Example:
            >>> config_service = get_config_service()
            >>>
            >>> # Normal usage with caching
            >>> config = config_service.get_config()
            >>> print(f"Language: {config['language']}")
            >>> print(f"Servers: {len(config['servers'])}")
            >>>
            >>> # Force reload from disk
            >>> fresh_config = config_service.get_config(force_reload=True)

        Note:
            This method automatically decrypts the bot token if a password hash is
            available. The decrypted token is stored in 'bot_token_decrypted_for_usage'.

        See Also:
            :meth:`save_config` - Save configuration to disk
            :class:`ConfigLoaderService` - Underlying loading implementation
        """
        cache_key = 'unified'

        # Try to get from cache if not force reload
        if not force_reload:
            cached_config = self._cache_service.get_cached_config(cache_key, self.config_dir)
            if cached_config is not None:
                return cached_config

        # Capture the directory mtime BEFORE loading: a save that lands while we
        # load bumps the mtime past this stamp, so the next call reloads instead
        # of serving the (possibly stale) result cached below.
        load_mtime = self._cache_service.get_config_dir_mtime(self.config_dir)

        # Collect the read errors of THIS load (see _record_read_error).
        # The reset is the point: a fixed permission problem must reopen the
        # login instead of keeping it locked for the lifetime of the process.
        self._read_errors = []

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

        # Attach the read errors to the result so they are cached with it and
        # reach every caller - without a caller having to ask (and so construct)
        # the service. The key is in _RUNTIME_ONLY_CONFIG_KEYS and is therefore
        # never saved.
        if self._read_errors:
            config['config_read_errors'] = list(self._read_errors)

        # Cache the result using cache service
        self._cache_service.set_cached_config(cache_key, config, self.config_dir, mtime=load_mtime)

        return config

    def save_config(self, config: Dict[str, Any]) -> ConfigServiceResult:
        """
        Save main configuration to config/config.json using atomic write pattern.

        This method saves the main configuration settings (bot_token, guild_id,
        web_ui_password_hash, etc.) to config/config.json.

        Note: Modular structure is used for specialized config:
        - Containers: config/containers/*.json (saved by ConfigurationSaveService)
        - Channels: config/channels/*.json (saved by ChannelConfigService)
        - Main settings: config/config.json (saved by THIS method)

        Args:
            config: Configuration dictionary to save

        Returns:
            ConfigServiceResult with success status
        """
        with self._save_lock:
            try:
                import json
                import os
                import shutil
                import tempfile
                from pathlib import Path

                # Prepare main config (exclude modular data saved separately)
                main_config = config.copy()

                # 'servers' lives in config/containers/*.json; the channel copy is KEPT.
                main_config.pop('servers', None)

                # Remove runtime-only keys added by get_config() (plaintext token). The
                # values are only used by the token self-repair below.
                runtime_values = {field: main_config.pop(field, None) for field in _RUNTIME_ONLY_CONFIG_KEYS}

                # === Critical Field Protection ===
                # Merge with existing config to prevent accidental loss of
                # critical fields (bot_token, guild_id) when a partial config
                # is saved (e.g. from the setup handler).
                # web_ui_password_hash included: losing it drops the panel back into first-run
                # setup mode, where admin/setup is accepted on every route (app/auth.py).
                # channel_permissions too: a save silent about channels must not
                # erase the copy. Preserved, never invented - see the spec test.
                _critical_fields = ('bot_token', 'guild_id', 'encrypted_bot_token',
                                    'web_ui_password_hash', 'channel_permissions')
                existing = {}
                if self.main_config_file.exists():
                    try:
                        existing = self._load_json_file(self.main_config_file, {})
                        for field in _critical_fields:
                            if field in existing and existing[field] and field not in main_config:
                                main_config[field] = existing[field]
                                logger.info(f"Preserved critical field '{field}' from existing config")
                    except (IOError, OSError, ValueError) as merge_err:
                        logger.warning(f"Could not read existing config for merge: {merge_err}")

                # === Token Self-Repair ===
                # Before the decrypted copy is dropped for good: if the stored token does not
                # decrypt with the password hash being saved, rebuild it from that copy.
                self._repair_bot_token(main_config,
                                       runtime_values.get('bot_token_decrypted_for_usage'),
                                       existing.get('bot_token_decrypted_for_usage'))

                # === Plaintext Token Protection ===
                self._keep_bot_token_encrypted(main_config, existing)

                logger.info(f"save_config called - saving main config with {len(main_config)} fields")
                logger.debug(f"Main config keys: {list(main_config.keys())}")

                # Ensure config directory exists
                config_dir = Path(self.main_config_file).parent
                config_dir.mkdir(parents=True, exist_ok=True)

                # === Backup Before Save ===
                # Keep a rolling backup so data can be recovered if a save
                # produces a corrupt or incomplete config.
                backup_path = self.main_config_file.with_suffix('.json.bak')
                if self.main_config_file.exists():
                    try:
                        shutil.copy2(str(self.main_config_file), str(backup_path))
                        logger.debug(f"Config backup created: {backup_path}")
                    except (IOError, OSError) as bak_err:
                        logger.warning(f"Could not create config backup: {bak_err}")

                # === Atomic Write Pattern (Best Practice) ===
                # Write to temp file first, then atomically rename to prevent corruption

                # Create temp file in same directory (required for atomic rename on same filesystem)
                fd, temp_path = tempfile.mkstemp(
                    dir=str(config_dir),
                    prefix='.config_',
                    suffix='.json.tmp'
                )

                try:
                    # Write to temp file
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        json.dump(main_config, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())  # Ensure data is written to disk

                    # Atomic rename (POSIX) or move (Windows)
                    if os.name == 'posix':
                        # On POSIX systems, rename is atomic
                        os.rename(temp_path, str(self.main_config_file))
                    else:
                        # On Windows, use replace for atomic operation
                        os.replace(temp_path, str(self.main_config_file))

                    logger.info(f"✅ Main configuration saved successfully to {self.main_config_file}")

                    # Log important fields that were saved (without showing sensitive data)
                    if 'bot_token' in main_config:
                        logger.info("  - bot_token: saved (encrypted)")
                    if 'guild_id' in main_config:
                        logger.info(f"  - guild_id: {main_config.get('guild_id')}")
                    if 'web_ui_password_hash' in main_config:
                        logger.info("  - web_ui_password_hash: saved")

                except (IOError, OSError) as write_error:
                    # Clean up temp file on error
                    try:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                    except (IOError, OSError):
                        pass  # Ignore cleanup errors
                    raise write_error

                # Invalidate cache after successful save
                try:
                    self._cache_service.invalidate_cache()
                    logger.debug("Cache invalidated after config save")
                except (ConfigCacheError, IOError, OSError) as cache_error:
                    # Cache invalidation failure is not critical
                    logger.warning(f"Cache invalidation failed (non-critical): {cache_error}")

                return ConfigServiceResult(
                    success=True,
                    message="Configuration saved successfully"
                )

            except ConfigCacheError:
                # Re-raise cache errors
                raise
            except (IOError, OSError, PermissionError) as e:
                logger.error(f"File I/O error saving configuration: {e}", exc_info=True)
                raise ConfigSaveError(
                    f"Configuration save failed (I/O error): {str(e)}",
                    error_code="CONFIG_SAVE_IO_ERROR",
                    details={'config_keys': list(config.keys()) if config else []}
                )
            except (ValueError, TypeError, KeyError) as e:
                logger.error(f"Data format error saving configuration: {e}", exc_info=True)
                raise ConfigSaveError(
                    f"Configuration save failed (data error): {str(e)}",
                    error_code="CONFIG_SAVE_DATA_ERROR",
                    details={'config_keys': list(config.keys()) if config else []}
                )

    def update_config_fields(self, updates: Dict[str, Any]) -> ConfigServiceResult:
        """Update only specific fields in config.json without touching other fields.

        This is safer than save_config() for targeted updates (e.g. setting a
        password hash) because it reads the existing config first and merges
        the updates, preventing accidental loss of unrelated fields.

        Args:
            updates: Dictionary of field names and values to update.

        Returns:
            ConfigServiceResult with success status.
        """
        with self._save_lock:
            try:
                import json

                # Load existing config from disk (not from cache)
                existing = {}
                if self.main_config_file.exists():
                    existing = self._load_json_file(self.main_config_file, {})

                # Apply updates
                existing.update(updates)

                logger.info(f"update_config_fields: updating {list(updates.keys())}")
            except (IOError, OSError, ValueError) as e:
                logger.error(f"Error reading config for field update: {e}", exc_info=True)
                return ConfigServiceResult(
                    success=False,
                    message=f"Failed to read existing config: {e}"
                )

            # INSIDE the lock: a save landing between the read and this write
            # was silently rolled back. Nests because the lock is an RLock.
            return self.save_config(existing)

    def change_web_ui_password(self, new_password: str, *, enforce_min_length: bool = True) -> None:
        """Set a new Web UI password and re-encrypt the stored bot token.

        The bot token encryption key is derived from ``web_ui_password_hash``,
        so swapping only the hash would leave an encrypted token undecryptable.
        This decrypts the token with the old hash, re-encrypts it with the new
        one and persists both fields together.

        Args:
            new_password: The new plaintext password (never stored or logged).
            enforce_min_length: False only for DDC_ADMIN_PASSWORD at startup: rejecting a
                short env password would leave the install without a hash, i.e. in
                first-time setup mode where admin/setup is accepted on every route.

        Raises:
            ValueError: If the password is empty or too short.
            TokenEncryptionError: If the token cannot be re-encrypted.
            ConfigSaveError: If the new configuration cannot be persisted.
        """
        if not isinstance(new_password, str) or not new_password:
            raise ValueError("Password is required")
        if enforce_min_length and len(new_password) < MIN_WEB_UI_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_WEB_UI_PASSWORD_LENGTH} characters long")

        new_hash = generate_password_hash(new_password, method=_PASSWORD_HASH_METHOD)
        updates = {'web_ui_password_hash': new_hash}

        # Effective (merged) values - the same ones auth.py and the bot use
        current = self.get_config(force_reload=True)
        old_hash = current.get('web_ui_password_hash')
        stored_token = current.get('bot_token')

        if (stored_token and old_hash and isinstance(stored_token, str) and
                not self._validation_service.looks_like_discord_token(stored_token)):
            try:
                plaintext_token = self.decrypt_token(stored_token, old_hash)
            except TokenEncryptionError:
                plaintext_token = None

            if plaintext_token:
                updates['bot_token'] = self.encrypt_token(plaintext_token, new_hash)
                logger.info("Bot token re-encrypted for the new Web UI password")
            else:
                # Already unusable with the current hash - leave it untouched
                # rather than discarding data we cannot interpret.
                logger.warning("Stored bot token could not be decrypted with the current "
                               "password hash - leaving it unchanged")

        result = self.update_config_fields(updates)
        if not result.success:
            raise ConfigSaveError(
                result.message or "Failed to save the new Web UI password",
                error_code="CONFIG_SAVE_PASSWORD_ERROR"
            )

        logger.info("Web UI password changed")

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
            # NOTE: Fernet.encrypt() already returns a base64-encoded token, no need for additional encoding
            fernet = Fernet(key)
            encrypted_bytes = fernet.encrypt(plaintext_token.encode())
            return encrypted_bytes.decode('utf-8')

        except ValueError as e:
            logger.error(f"Token encryption failed - invalid input: {e}", exc_info=True)
            raise TokenEncryptionError(
                f"Invalid input for token encryption: {e}",
                error_code="TOKEN_ENCRYPTION_INVALID_INPUT",
                details={'error': str(e)}
            )
        except (TypeError, AttributeError) as e:
            logger.error(f"Token encryption failed - type error: {e}", exc_info=True)
            raise TokenEncryptionError(
                f"Token encryption type error: {e}",
                error_code="TOKEN_ENCRYPTION_TYPE_ERROR",
                details={'error': str(e)}
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
        except (ConfigCacheError, IOError, OSError, KeyError) as cache_error:
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
            except (ConfigCacheError, IOError, OSError) as cache_error:
                # Cache errors are non-critical
                logger.warning(f"Token cache set failed (non-critical): {cache_error}")

            return decrypted_token

        except InvalidToken as e:
            logger.warning("Failed to decrypt token: Invalid token or key (password change?)")
            raise TokenEncryptionError(
                "Invalid token or encryption key",
                error_code="TOKEN_DECRYPTION_INVALID_TOKEN",
                details={'error': 'Token may have been encrypted with different key'}
            )
        except ValueError as e:
            logger.error(f"Token decryption failed - invalid input: {e}", exc_info=True)
            raise TokenEncryptionError(
                f"Invalid input for token decryption: {e}",
                error_code="TOKEN_DECRYPTION_INVALID_INPUT",
                details={'error': str(e)}
            )
        except (TypeError, AttributeError, UnicodeDecodeError) as e:
            logger.error(f"Token decryption failed - type/encoding error: {e}", exc_info=True)
            raise TokenEncryptionError(
                f"Token decryption type/encoding error: {e}",
                error_code="TOKEN_DECRYPTION_TYPE_ERROR",
                details={'error': str(e)}
            )

    # === Private Helper Methods ===

    def _record_read_error(self, file_path: Path, reason: str) -> None:
        """Records that a configuration file could not be parsed.

        WHY THIS IS NEEDED: the return value below is the default in every error
        case - and that cannot be told apart from a real read result. For
        ``web_ui_password_hash`` this means: an unreadable config.json looks
        like a fresh installation, and ``app/auth.py:176`` then lets admin/setup
        onto every one of the 70 routes with ``@auth.login_required``. The error
        is in the log, but no caller can evaluate a log.

        ``hasattr`` instead of an assignment in the constructor:
        ``_load_json_file`` is already called FROM the constructor
        (``ensure_modular_structure`` :242, ``_fold_legacy_settings_once`` :248),
        i.e. before any later initialisation would run.
        """
        if not hasattr(self, '_read_errors'):
            self._read_errors = []
        entry = f"{file_path}: {reason}"
        if entry not in self._read_errors:
            self._read_errors.append(entry)

    def _load_json_file(self, file_path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """Load JSON file with fallback to defaults.

        Every failure is also recorded - see ``_record_read_error``. Without
        that record, "file was broken" cannot be told apart from "file does not
        exist".
        """
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
            self._record_read_error(file_path, f"not valid JSON ({e})")
            # Return defaults on JSON parse errors
            return default.copy()
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"File access error loading {file_path}: {e}", exc_info=True)
            self._record_read_error(file_path, f"not readable ({e})")
            # Return defaults on I/O errors
            return default.copy()
        except (TypeError, AttributeError, UnicodeDecodeError) as e:
            logger.error(f"Data format error loading {file_path}: {e}", exc_info=True)
            self._record_read_error(file_path, f"unexpected format ({e})")
            # Return defaults on data format errors
            return default.copy()

    def _save_json_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Save data to JSON file atomically to prevent corruption."""
        # Create temp file in same directory as target file
        temp_dir = str(file_path.parent)
        fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True, suffix='.json.tmp')

        try:
            # Write to temp file
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

            # Atomic rename (POSIX) or move (Windows)
            if os.name == 'posix':
                os.rename(temp_path, file_path)
            else:
                # Windows: remove target first if exists
                if file_path.exists():
                    file_path.unlink()
                os.rename(temp_path, file_path)
        except Exception:
            # Cleanup temp file on error
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass  # Best effort cleanup
            raise

    def _decrypt_token_if_needed(self, token: str, password_hash: Optional[str]) -> Optional[str]:
        """The usable bot token, or None. Never a token-shaped thing that is not one.

        This used to end in a bare ``return token``, and that line was reached
        in two ways that are not "it was already plaintext" (review E26):

        1. no ``web_ui_password_hash``, so the branch below is skipped entirely
           and the ENCRYPTED token comes back as if it were usable;
        2. the decryption raised nothing but produced something that is not a
           Discord token.

        ``get_config`` then logged "Successfully decrypted token for usage" and
        handed the ciphertext to the bot, so Discord answered "Improper token
        has been passed" while DDC's log reported a success - and the operator
        went looking for a wrong token instead of a missing password.

        A config with an encrypted token and no password hash is not
        hypothetical: ``_repair_bot_token`` exists for exactly that state and
        handles it on save and in the legacy fold. The read path had nothing.

        Telling the two apart is safe to do by shape, and it was measured
        rather than assumed: a Discord bot token is three dot-separated parts,
        and a Fernet ciphertext is dotless base64url. See
        tests/spec/test_an_undecryptable_token_is_not_handed_on.py.
        """
        if not token:
            return None

        looks_like_token = self._validation_service.looks_like_discord_token
        if looks_like_token(token):
            return token

        # Not a Discord token, so it is either encrypted or damaged. Either way
        # it is only usable if it decrypts into one.
        if not password_hash:
            logger.error(
                "The stored bot token is encrypted and there is no Web UI "
                "password to decrypt it with. The bot cannot log in until a "
                "password is set on the /setup page - the token itself is fine.")
            return None

        try:
            decrypted = self.decrypt_token(token, password_hash)
        except TokenEncryptionError as e:
            logger.error(f"Token decryption failed: {e.message}", exc_info=True)
            return None

        if decrypted and looks_like_token(decrypted):
            return decrypted

        logger.error(
            "The stored bot token was decrypted without error but the result is "
            "not a Discord token - the Web UI password has most likely changed "
            "since the token was saved. Re-enter the token on the configuration "
            "page.")
        return None

    def _keep_bot_token_encrypted(self, main_config: Dict[str, Any], existing: Dict[str, Any]) -> None:
        """Never let a save replace an encrypted bot_token with a plaintext one."""
        new_token = main_config.get('bot_token')
        old_token = existing.get('bot_token')
        if (not new_token or not old_token or new_token == old_token or
                not isinstance(new_token, str) or not isinstance(old_token, str)):
            return

        # Only act when a plaintext token is about to overwrite an encrypted one
        looks_plain = self._validation_service.looks_like_discord_token
        if not looks_plain(new_token) or looks_plain(old_token):
            return

        password_hash = main_config.get('web_ui_password_hash') or existing.get('web_ui_password_hash')
        if not password_hash:
            logger.warning("Plaintext bot_token replaces an encrypted one but no password hash "
                           "is available to encrypt it")
            return

        encrypted = self.encrypt_token(new_token, password_hash)
        if encrypted:
            main_config['bot_token'] = encrypted
            logger.info("Encrypted plaintext bot_token before saving")

    def _repair_bot_token(self, main_config: Dict[str, Any], *plaintext_copies: Optional[str]) -> None:
        """Self-repair an encrypted ``bot_token`` that the current password hash cannot decrypt.

        Earlier versions stored the decrypted token next to it (``bot_token_decrypted_for_usage``)
        and could leave the encrypted token keyed to another hash (e.g. DDC_ADMIN_PASSWORD on a
        migrated install). Instead of dropping the only usable copy, re-encrypt it with the
        current hash - or keep it in plaintext when there is no hash to derive a key from.
        """
        looks_plain = self._validation_service.looks_like_discord_token
        plaintext = next((c for c in plaintext_copies if isinstance(c, str) and looks_plain(c)), None)
        token = main_config.get('bot_token')
        if not plaintext or not token or not isinstance(token, str) or looks_plain(token):
            return

        password_hash = main_config.get('web_ui_password_hash')
        if not password_hash:
            main_config['bot_token'] = plaintext
            logger.warning("Stored bot token is encrypted but no Web UI password hash is set - "
                           "keeping the last decrypted copy so the bot can still log in")
            return

        try:
            decrypted = self.decrypt_token(token, password_hash)
            if decrypted and looks_plain(decrypted):
                return  # usable with the current key - nothing to repair
        except TokenEncryptionError:
            pass
        try:
            repaired = self.encrypt_token(plaintext, password_hash)
        except TokenEncryptionError as e:
            logger.error(f"Bot token self-repair failed: {e.message}")
            return
        if repaired:
            main_config['bot_token'] = repaired
            logger.warning("Stored bot token could not be decrypted with the current Web UI password "
                           "hash - re-encrypted it from the last decrypted copy")

    def _backup_config_files(self, files: List[Path], backup_name: str) -> Optional[Path]:
        """Copy the existing ``files`` into config/<backup_name>/ (permissions kept)."""
        existing_files = [f for f in files if f.exists()]
        if not existing_files:
            return None
        backup_dir = self.config_dir / backup_name
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        for file_path in existing_files:
            shutil.copy2(str(file_path), str(backup_dir / file_path.name))
        return backup_dir

    def _fold_legacy_settings_once(self) -> bool:
        """One-time upgrade step: make config.json the single source of the settings.

        Migrated installs still carry legacy settings files next to config.json: auth.json /
        web_ui.json / docker_settings.json in the modular layout, the v1 split files
        (bot_config.json, docker_config.json, web_config.json) in the virtual layout. v2.3 let
        them override config.json; now config.json - the file every save writes - wins. So that
        no install silently switches to other values (password hash, bot token, language...),
        the values v2.3 used are written into config.json once, after a backup, and the modular
        legacy files are renamed to ``*.folded-<timestamp>`` (the v1 split files stay: they
        also hold containers and channels). A marker file keeps the step from running twice.
        On errors nothing is lost: the loader keeps the v2.3 precedence until a fold succeeds.

        Returns:
            True if config.json was rewritten.
        """
        loader = self._loader_service
        try:
            marker = loader.read_fold_marker()
            raw_main = self._load_json_file(self.main_config_file, {})
            if 'servers' in raw_main or 'docker_name' in raw_main:
                return False  # monolithic v1.1.x config.json: migrate_legacy_v1_config_if_needed

            if loader.has_real_modular_structure():
                mode = 'real'
                to_rename = [f for f in loader.legacy_settings_files if f.exists()]
                if not to_rename or (marker is not None and marker.get('mode') == 'real'):
                    return False
                folded = loader.load_pre_fold_real_settings()
                involved = [self.main_config_file, *to_rename]
            else:
                mode = 'virtual'
                v1_files = [f for f in (self.bot_config_file, self.docker_config_file, self.web_config_file)
                            if f.exists()]
                if marker is not None or not v1_files:
                    return False
                to_rename = []
                # Without config.json there is nothing to fold: it becomes authoritative with
                # its first write, which starts from the loaded (v1) values.
                folded = loader.load_pre_fold_virtual_settings() if self.main_config_file.exists() else None
                involved = [self.main_config_file, *v1_files]

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            with self._save_lock:
                backup_dir = None
                if folded is not None:
                    backup_dir = self._backup_config_files(involved, f"backup_{timestamp}_settings_fold")
                    runtime_values = {key: folded.pop(key, None) for key in _RUNTIME_ONLY_CONFIG_KEYS}
                    self._repair_bot_token(folded, runtime_values.get('bot_token_decrypted_for_usage'))
                    self._save_json_file(self.main_config_file, folded)
                self._save_json_file(loader.fold_marker_file, {
                    'folded_at': timestamp,
                    'mode': mode,
                    'files': [f.name for f in involved if f.exists()],
                    'backup': backup_dir.name if backup_dir else None,
                })
                renamed = []
                for legacy_file in to_rename:
                    target = legacy_file.with_name(f"{legacy_file.name}.folded-{timestamp}")
                    try:
                        legacy_file.rename(target)
                        renamed.append(target.name)
                    except OSError as e:
                        logger.warning(f"Could not rename {legacy_file.name} after folding it into "
                                       f"config.json: {e} (config.json still wins)")
            self._cache_service.invalidate_cache()
        except (ConfigServiceError, OSError, TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error(f"Could not fold legacy settings into config.json: {e} - "
                         f"the legacy files keep precedence for now", exc_info=True)
            return False

        if folded is None:
            logger.info("Legacy v1 settings files found without config.json - config.json will "
                        "be the authoritative settings file from its first write")
            return False
        logger.info(f"Folded legacy settings ({', '.join(f.name for f in involved[1:])}) into "
                    f"config.json; backup: {backup_dir.name if backup_dir else '-'}"
                    + (f"; renamed: {', '.join(renamed)}" if renamed else ""))
        if not folded.get('web_ui_password_hash'):
            logger.warning("No Web UI password is set - log in with admin / setup and choose one "
                           "on the /setup page (or set DDC_ADMIN_PASSWORD)")
        return True

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
            except ConfigLoadError as retry_error:
                logger.error(f"Retry after cache error failed: {retry_error.message}", exc_info=True)
                return GetConfigResult(
                    success=False,
                    error_message=f"Failed to load config after cache error: {retry_error.message}"
                )
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.error(f"Service error getting config via service: {e}", exc_info=True)
            return GetConfigResult(
                success=False,
                error_message=f"Service error: {str(e)}"
            )
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"File I/O error getting config via service: {e}", exc_info=True)
            return GetConfigResult(
                success=False,
                error_message=f"File access error: {str(e)}"
            )

    def validate_donation_key_service(self, request: ValidateDonationKeyRequest) -> ValidateDonationKeyResult:
        """SERVICE FIRST: Validate donation key with Request/Result pattern."""
        try:
            # Validate against list of valid donation keys from key_crypto
            from utils.key_crypto import get_valid_donation_keys

            valid_keys = get_valid_donation_keys()
            provided_key = request.key.strip()

            # Case-insensitive comparison with all valid keys
            is_valid = any(provided_key.upper() == valid_key.upper() for valid_key in valid_keys)

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
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error(f"Data error validating donation key: {e}", exc_info=True)
            return ValidateDonationKeyResult(
                success=False,
                error_message=f"Data validation error: {str(e)}"
            )

    # Accepted range for the static difficulty multiplier. Rejecting out-of-range values is
    # deliberate: silently clamping would tell the user "saved" while pricing differently.
    MIN_DIFFICULTY_MULTIPLIER = 0.1
    MAX_DIFFICULTY_MULTIPLIER = 10.0

    def set_evolution_mode_service(self, request: SetEvolutionModeRequest) -> SetEvolutionModeResult:
        """SERVICE FIRST: Persist evolution mode configuration.

        This writer was missing entirely until v2.4.1. The Web UI called a method that did not
        exist on the mech service, so every save failed with HTTP 500 and evolution_mode.json was
        never created - which left every installation permanently on dynamic pricing, no matter
        what the difficulty slider showed.

        Only the two keys the reader consumes are written, so the file stays readable by older
        versions.
        """
        try:
            multiplier = float(request.difficulty_multiplier)
        except (TypeError, ValueError):
            return SetEvolutionModeResult(
                success=False,
                error=f"Difficulty multiplier must be a number, got {request.difficulty_multiplier!r}"
            )

        if not (self.MIN_DIFFICULTY_MULTIPLIER <= multiplier <= self.MAX_DIFFICULTY_MULTIPLIER):
            return SetEvolutionModeResult(
                success=False,
                error=(f"Difficulty multiplier must be between {self.MIN_DIFFICULTY_MULTIPLIER} "
                       f"and {self.MAX_DIFFICULTY_MULTIPLIER}, got {multiplier}")
            )

        use_dynamic = bool(request.use_dynamic)
        config_path = self.config_dir / "evolution_mode.json"

        try:
            self._save_json_file(config_path, {
                'use_dynamic': use_dynamic,
                'difficulty_multiplier': multiplier,
            })
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to save evolution mode config: {e}", exc_info=True)
            return SetEvolutionModeResult(success=False, error=f"Could not write {config_path.name}: {e}")

        logger.info(
            "Evolution mode saved: %s (multiplier %.2f%s)",
            "dynamic" if use_dynamic else "static",
            multiplier,
            "" if not use_dynamic else ", ignored in dynamic mode",
        )
        return SetEvolutionModeResult(
            success=True, use_dynamic=use_dynamic, difficulty_multiplier=multiplier
        )

    def get_evolution_mode_service(self, request: GetEvolutionModeRequest) -> GetEvolutionModeResult:
        """SERVICE FIRST: Get evolution mode configuration with Request/Result pattern."""
        try:
            config_path = self.config_dir / "evolution_mode.json"
            default_config = {
                'use_dynamic': True,
                'difficulty_multiplier': 1.0
            }

            # _load_json_file handles JSON/IO errors and returns the defaults
            mode_config = self._load_json_file(config_path, default_config)

            return GetEvolutionModeResult(
                success=True,
                use_dynamic=mode_config.get('use_dynamic', True),
                difficulty_multiplier=_difficulty_in_range(  # bounds on READ too
                    mode_config.get('difficulty_multiplier', 1.0), self.MIN_DIFFICULTY_MULTIPLIER,
                    self.MAX_DIFFICULTY_MULTIPLIER)
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
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Data error getting evolution mode: {e}", exc_info=True)
            # Return safe defaults on data error
            return GetEvolutionModeResult(
                success=False,
                error=f"Data format error: {str(e)}",
                use_dynamic=True,  # Safe default
                difficulty_multiplier=1.0
            )
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"File access error getting evolution mode: {e}", exc_info=True)
            # Return safe defaults on file error
            return GetEvolutionModeResult(
                success=False,
                error=f"File access error: {str(e)}",
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

def update_config_fields(updates: Dict[str, Any]) -> bool:
    """Legacy compatibility: Update specific fields without overwriting others."""
    result = get_config_service().update_config_fields(updates)
    return result.success

def change_web_ui_password(new_password: str, *, enforce_min_length: bool = True) -> None:
    """Change the Web UI password and re-encrypt the bot token with the new key.

    ``enforce_min_length=False`` is reserved for DDC_ADMIN_PASSWORD (see the method).

    Raises:
        ValueError: If the password is empty or too short (user-readable message).
        TokenEncryptionError: If the token cannot be re-encrypted.
        ConfigSaveError: If the new configuration cannot be persisted.
    """
    get_config_service().change_web_ui_password(new_password, enforce_min_length=enforce_min_length)

# === Form Parsing Functions (delegated to ConfigFormParserService) ===

def process_config_form(form_data: Dict[str, Any], current_config: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Legacy wrapper: Delegate to ConfigFormParserService."""
    return ConfigFormParserService.process_config_form(form_data, current_config, get_config_service())
