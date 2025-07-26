# -*- coding: utf-8 -*-
import os
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple, Union, Set
import base64
import hashlib
import traceback
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from werkzeug.security import generate_password_hash, check_password_hash

# Import your existing utils
from utils.logging_utils import setup_logger

# Setup logger for this module
logger = setup_logger('ddc.config_manager', level=logging.INFO)

# --- Constants from original config_loader ---
_TOKEN_ENCRYPTION_SALT = b'ddc-salt-for-token-encryption-key-v1'
_PBKDF2_ITERATIONS = 260000  # Number of iterations for PBKDF2

# Determine paths
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "config"))
_CONFIG_DIR_VERIFIED = False  # Flag to avoid repeated directory checks

# Default configurations - imported from original config_loader
# Important: Use direct imports to avoid circular imports
try:
    from utils.config_loader import (
        DEFAULT_BOT_CONFIG,
        DEFAULT_DOCKER_CONFIG,
        DEFAULT_CHANNELS_CONFIG,
        DEFAULT_WEB_CONFIG,
        DEFAULT_CONFIG,
        validate_server_config  # Reuse server validation logic
    )
except ImportError:
    logger.error("Failed to import defaults from config_loader, using hardcoded defaults")
    # Fallback hardcoded defaults if import fails
    DEFAULT_BOT_CONFIG = {
        "bot_token": None,
        "guild_id": None,
        "language": "en",
        "timezone": "Europe/Berlin",
        "heartbeat_channel_id": None,
    }
    
    DEFAULT_DOCKER_CONFIG = {
        "servers": [],
        "docker_list_refresh_seconds": 60,
    }
    
    DEFAULT_CHANNELS_CONFIG = {
        "channel_permissions": {},
        "default_channel_permissions": {
            "commands": {
                "serverstatus": True,
                "command": False,
                "control": False,
                "schedule": False
            },
            "post_initial": False,
            "update_interval_minutes": 5,
            "inactivity_timeout_minutes": 10,
            "enable_auto_refresh": True,
            "recreate_messages_on_inactivity": True
        }
    }
    
    DEFAULT_WEB_CONFIG = {
        "web_ui_user": "admin",
        "web_ui_password_hash": "pbkdf2:sha256:260000$defaulthash"  # Will be properly set on first save
    }
    
    DEFAULT_CONFIG = {
        **DEFAULT_BOT_CONFIG,
        **DEFAULT_DOCKER_CONFIG,
        **DEFAULT_CHANNELS_CONFIG,
        **DEFAULT_WEB_CONFIG
    }
    
    def validate_server_config(server_data: Dict[str, Any]) -> bool:
        """Simple validation for server configuration."""
        required_keys = ["name", "docker_name", "allowed_actions"]
        return all(key in server_data for key in required_keys)


# Function to check the configuration directory once
def ensure_config_directory():
    """Ensures that the configuration directory exists (only once per process)"""
    global _CONFIG_DIR_VERIFIED
    
    # First check if the directory check has already been done
    if _CONFIG_DIR_VERIFIED:
        return
        
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        _CONFIG_DIR_VERIFIED = True  # Set flag that the directory check has been done
        logger.info(f"Config directory exists or was created: {CONFIG_DIR}")
    except OSError as e:
        logger.error(f"Could not create config directory {CONFIG_DIR}: {e}")
        

class ConfigManager:
    """
    Singleton configuration manager for centralized configuration handling.
    Provides thread-safe caching and consistent access to configuration.
    """
    _instance = None
    _is_initialized = False  # Class attribute to prevent multiple initialization
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        if not self._initialized:
            # Ensure the configuration directory exists before initialization
            ensure_config_directory()
            
            # Configuration files
            self.BOT_CONFIG_FILE = os.path.join(CONFIG_DIR, "bot_config.json")
            self.DOCKER_CONFIG_FILE = os.path.join(CONFIG_DIR, "docker_config.json")
            self.CHANNELS_CONFIG_FILE = os.path.join(CONFIG_DIR, "channels_config.json")
            self.WEB_CONFIG_FILE = os.path.join(CONFIG_DIR, "web_config.json")
            
            # Cache state
            self._config_cache = None
            self._cache_timestamp = 0
            
            # PERFORMANCE: Add file modification tracking
            self._file_mtimes = {}
            
            self._initialized = True
            
            # Initial load of configuration
            self._load_config_from_disk()
            
            # Check file permissions on startup
            self._check_startup_permissions()
    
    def _load_json_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Load and parse a JSON file, with error handling."""
        if not os.path.exists(file_path):
            logger.debug(f"Config file not found: {file_path}")
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    logger.debug(f"Config file is empty: {file_path}")
                    return {}
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return None

    def _check_file_permissions(self, file_path: str) -> Tuple[bool, str]:
        """
        Check if a file has proper read/write permissions.
        
        Returns:
            Tuple of (has_permissions, error_message)
        """
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return True, ""  # File doesn't exist yet, will be created
            
            # Check read permission
            if not os.access(file_path, os.R_OK):
                return False, f"No read permission for {file_path}"
            
            # Check write permission
            if not os.access(file_path, os.W_OK):
                return False, f"No write permission for {file_path}"
            
            # Check if parent directory is writable (for creating backup files)
            parent_dir = os.path.dirname(file_path)
            if not os.access(parent_dir, os.W_OK):
                return False, f"No write permission for directory {parent_dir}"
            
            return True, ""
            
        except Exception as e:
            return False, f"Error checking permissions for {file_path}: {str(e)}"

    def _save_json_file(self, file_path: str, data: Dict[str, Any]) -> bool:
        """Save data to a JSON file atomically, with error handling."""
        try:
            # Check permissions first
            has_permission, error_msg = self._check_file_permissions(file_path)
            if not has_permission:
                logger.error(f"PERMISSION ERROR: {error_msg}")
                logger.error(f"Please fix file permissions. Run: sudo chmod 644 {file_path}")
                return False
            
            # Ensure the directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Use temporary file for atomic writes
            temp_file = file_path + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk
            
            # Verify the file was written correctly
            try:
                with open(temp_file, 'r', encoding='utf-8') as f_read:
                    content_after_save = json.load(f_read)
                    if content_after_save != data:
                        logger.error(f"Verification failed - content mismatch in {temp_file}")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        return False
            except Exception as e_verify:
                logger.error(f"Error during verification of {temp_file}: {e_verify}")
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return False
            
            # Rename temporary file to target file
            os.rename(temp_file, file_path)
            logger.debug(f"Successfully saved configuration to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing to {file_path}: {e}")
            traceback.print_exc()
            return False

    def _derive_encryption_key(self, password_hash: str) -> bytes:
        """Derives a Fernet-compatible encryption key from the password hash using PBKDF2."""
        if not password_hash or not isinstance(password_hash, str):
            logger.error("Cannot derive encryption key: Invalid password_hash provided.")
            raise ValueError("Cannot derive encryption key from invalid password hash")

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_TOKEN_ENCRYPTION_SALT,
            iterations=_PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password_hash.encode('utf-8')))
        return key

    def _decrypt_token(self, encrypted_token_str: Optional[str], password_hash: str) -> Optional[str]:
        """Attempts to decrypt the bot token string using a key derived from the password hash."""
        if not encrypted_token_str:
            return None

        try:
            derived_key = self._derive_encryption_key(password_hash)
            f = Fernet(derived_key)
            decrypted_token_bytes = f.decrypt(encrypted_token_str.encode('utf-8'))
            decrypted_token = decrypted_token_bytes.decode('utf-8')
            
            # Simplified cache update without lock acquisition
            try:
                self._token_cache = decrypted_token
                self._token_cache_hash_source = password_hash
            except Exception:
                # Ignore cache errors, as the token value is more important
                pass
                
            return decrypted_token
        except InvalidToken:
            logger.warning("Failed to decrypt token: Invalid token or key (password change?)")
            return None
        except ValueError as e:
            logger.error(f"Failed to decrypt bot token due to key derivation error: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to decrypt token: Unexpected error: {e}")
            return None

    def _encrypt_token(self, plaintext_token: str, password_hash: str) -> Optional[str]:
        """Encrypts a bot token using a key derived from the password hash."""
        if not plaintext_token or not password_hash:
            return None
            
        try:
            derived_key = self._derive_encryption_key(password_hash)
            f = Fernet(derived_key)
            encrypted_token = f.encrypt(plaintext_token.encode('utf-8')).decode('utf-8')
            return encrypted_token
        except Exception as e:
            logger.error(f"Failed to encrypt token: {e}")
            return None

    def _check_startup_permissions(self) -> None:
        """
        Check file permissions on startup and log warnings.
        """
        try:
            permission_issues = []
            
            # Check permissions for all configuration files
            permission_results = self.check_all_permissions()
            
            for file_path, (has_permission, error_msg) in permission_results.items():
                if not has_permission:
                    permission_issues.append(error_msg)
            
            if permission_issues:
                logger.warning("=" * 60)
                logger.warning("CONFIGURATION FILE PERMISSION ISSUES DETECTED!")
                logger.warning("The following files have incorrect permissions:")
                for issue in permission_issues:
                    logger.warning(f"  - {issue}")
                logger.warning("=" * 60)
                logger.warning("This will prevent saving configuration changes.")
                logger.warning("To fix, run these commands on your server:")
                logger.warning("  docker exec ddc chmod 644 /app/config/*.json")
                logger.warning("Or on the host:")
                logger.warning("  chmod 644 /mnt/user/appdata/dockerdiscordcontrol/config/*.json")
                logger.warning("  chown nobody:users /mnt/user/appdata/dockerdiscordcontrol/config/*.json")
                logger.warning("=" * 60)
                
        except Exception as e:
            logger.error(f"Error checking startup permissions: {e}")
    
    def _has_files_changed(self) -> bool:
        """Check if any config files have been modified since last load."""
        try:
            for file_path in [self.BOT_CONFIG_FILE, self.DOCKER_CONFIG_FILE, 
                            self.CHANNELS_CONFIG_FILE, self.WEB_CONFIG_FILE]:
                if os.path.exists(file_path):
                    current_mtime = os.path.getmtime(file_path)
                    last_mtime = self._file_mtimes.get(file_path)
                    if last_mtime is None or current_mtime > last_mtime:
                        return True
            return False
        except Exception:
            return True  # On error, assume files changed
    
    def _update_file_mtimes(self) -> None:
        """Update stored modification times of config files."""
        for file_path in [self.BOT_CONFIG_FILE, self.DOCKER_CONFIG_FILE, 
                         self.CHANNELS_CONFIG_FILE, self.WEB_CONFIG_FILE]:
            if os.path.exists(file_path):
                self._file_mtimes[file_path] = os.path.getmtime(file_path)
    
    def _load_config_from_disk(self) -> Dict[str, Any]:
        """Load configuration from disk and update cache."""
        logger.debug("Loading configuration from disk...")
        
        try:
            bot_config_raw = self._load_json_file(self.BOT_CONFIG_FILE) or {}
            docker_config_raw = self._load_json_file(self.DOCKER_CONFIG_FILE) or {}
            channels_config_raw = self._load_json_file(self.CHANNELS_CONFIG_FILE) or {}
            web_config_raw = self._load_json_file(self.WEB_CONFIG_FILE) or {}
            
            # Merge with defaults
            config = {**DEFAULT_CONFIG, **bot_config_raw, **docker_config_raw, 
                     **channels_config_raw, **web_config_raw}
            
            # Decrypt token if needed
            token_to_decrypt = config.get('bot_token')
            current_hash = config.get('web_ui_password_hash')
            if token_to_decrypt and current_hash:
                config['bot_token_decrypted_for_usage'] = self._decrypt_token(token_to_decrypt, current_hash)
            
            # Update cache and timestamps
            self._config_cache = config.copy()
            self._cache_timestamp = time.time()
            self._update_file_mtimes()
            
            # Load debug status without blocking
            try:
                debug_mode = config.get('scheduler_debug_mode', False)
                logger.info(f"Debug status loaded from configuration: {debug_mode}")
                
                # Update logging settings if needed
                try:
                    from utils.logging_utils import refresh_debug_status
                    refresh_debug_status()
                except ImportError:
                    pass
            except Exception as e:
                logger.error(f"Error loading debug status: {e}")
            
            logger.info(f"Configuration loaded from disk. Language: {config.get('language')}")
            return config
            
        except Exception as e:
            logger.error(f"Error loading configuration from disk: {e}")
            return DEFAULT_CONFIG.copy()
    
    def get_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Get the application configuration. Uses in-memory cache unless forced to reload.
        
        Args:
            force_reload: If True, bypass the cache and reload from disk.
            
        Returns:
            Dict containing the full configuration.
        """
        try:
            # Return cache if valid and no force_reload
            if self._config_cache is not None and not force_reload:
                # Only check for file changes every 60 seconds
                if time.time() - self._cache_timestamp > 60 and self._has_files_changed():
                    logger.info("Configuration files changed on disk, reloading...")
                    return self._load_config_from_disk()
                return self._config_cache.copy()
            
            # Load from disk if cache is empty or force_reload
            return self._load_config_from_disk()
                
        except Exception as e:
            logger.error(f"Error getting configuration: {e}")
            # Return a safe fallback configuration
            return self._get_config_fallback()
    
    def _get_config_fallback(self) -> Dict[str, Any]:
        """
        Fallback method to load configuration without locks.
        Used when lock acquisition fails and no cache exists.
        
        Returns:
            Dict containing basic configuration with defaults.
        """
        try:
            logger.debug("Using fallback config loading method (no locks)")
            
            # Try to load the main configuration files directly
            config = DEFAULT_CONFIG.copy()
            
            # Note: Only the most important configurations are loaded here,
            # without validation and without token decryption
            try:
                if os.path.exists(self.BOT_CONFIG_FILE):
                    with open(self.BOT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                        bot_config = json.load(f)
                        for key, value in bot_config.items():
                            if key in DEFAULT_BOT_CONFIG:
                                config[key] = value
            except Exception:
                pass  # Ignore errors in the fallback path
                
            try:
                if os.path.exists(self.DOCKER_CONFIG_FILE):
                    with open(self.DOCKER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                        docker_config = json.load(f)
                        if "servers" in docker_config and isinstance(docker_config["servers"], list):
                            config["servers"] = docker_config["servers"]
            except Exception:
                pass  # Ignore errors in the fallback path
            
            # Mark the configuration as fallback
            config['_is_fallback_config'] = True
            
            return config
            
        except Exception as e:
            logger.debug(f"Fallback config loading failed: {e}")
            return DEFAULT_CONFIG.copy()
    
    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """Save configuration to disk and update cache."""
        try:
            config = config_data.copy()
            
            # Handle password change
            new_password = config.pop('new_web_ui_password', None)
            if new_password:
                password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
                config['web_ui_password_hash'] = password_hash
                
                # Re-encrypt bot token with new password if needed
                token_value = config.get('bot_token')
                if token_value:
                    encrypted_token = self._encrypt_token(token_value, password_hash)
                    if encrypted_token:
                        config['bot_token'] = encrypted_token
            
            # Remove runtime-only fields
            if 'bot_token_decrypted_for_usage' in config:
                del config['bot_token_decrypted_for_usage']
            
            # Split and save component files
            bot_config = {k: config.get(k) for k in DEFAULT_BOT_CONFIG}
            docker_config = {k: config.get(k) for k in DEFAULT_DOCKER_CONFIG}
            channels_config = {k: config.get(k) for k in DEFAULT_CHANNELS_CONFIG}
            web_config = {k: config.get(k) for k in DEFAULT_WEB_CONFIG}
            
            success = all([
                self._save_json_file(self.BOT_CONFIG_FILE, bot_config),
                self._save_json_file(self.DOCKER_CONFIG_FILE, docker_config),
                self._save_json_file(self.CHANNELS_CONFIG_FILE, channels_config),
                self._save_json_file(self.WEB_CONFIG_FILE, web_config)
            ])
            
            if success:
                # Update cache
                self._config_cache = config.copy()
                self._cache_timestamp = time.time()
                self._update_file_mtimes()
                
                # Notify subscribers
                self._notify_subscribers(config)
                logger.info("Configuration saved successfully")
                return True
            
            logger.error("Failed to save one or more configuration files")
            return False
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
    
    def get_server_config(self, server_name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific server.
        
        Args:
            server_name: Name or docker_name of the server
            
        Returns:
            Server configuration dict or None if not found
        """
        config = self.get_config()
        servers = config.get('servers', [])
        
        for server in servers:
            if server.get('name') == server_name or server.get('docker_name') == server_name:
                return server.copy()
        
        logger.warning(f"Server configuration not found for '{server_name}'")
        return None
    
    def update_server_config(self, server_name: str, new_config_data: Dict[str, Any]) -> bool:
        """
        Update configuration for a specific server.
        
        Args:
            server_name: Name or docker_name of the server to update
            new_config_data: New server configuration
            
        Returns:
            bool: Success or failure
        """
        if not validate_server_config(new_config_data.copy()):
            logger.error(f"Invalid server configuration for '{server_name}'")
            return False
            
        config = self.get_config()
        servers = config.get('servers', [])
        server_index = -1
        
        for i, server in enumerate(servers):
            if server.get('name') == server_name or server.get('docker_name') == server_name:
                server_index = i
                break
                
        if server_index == -1:
            logger.error(f"Server '{server_name}' not found for update")
            return False
            
        # Update the server in the list
        servers[server_index] = new_config_data.copy()
        config['servers'] = servers
        
        # Remove decrypted token before saving
        if 'bot_token_decrypted_for_usage' in config:
            del config['bot_token_decrypted_for_usage']
            
        # Save the updated config
        return self.save_config(config)
    
    def invalidate_cache(self) -> None:
        """
        Invalidate the configuration cache, forcing reload on next access.
        """
        current_time = time.time()
        
        # Anti-thrashing: Prevent too many cache invalidations in a short time
        since_last_invalidation = current_time - self._last_cache_invalidation
        if since_last_invalidation < self._min_invalidation_interval:
            logger.debug(f"Ignoring cache invalidation request (too frequent: {since_last_invalidation:.1f}s < {self._min_invalidation_interval:.1f}s)")
            return
            
        self._config_cache = None
        self._cache_timestamp = 0
        self._last_full_log_time = None
        self._last_lang_log_time = None
        self._last_cache_invalidation = current_time
            
        logger.debug("Configuration cache invalidated")
    
    def set_cache_ttl(self, seconds: int) -> None:
        """
        Set the cache time-to-live.
        
        Args:
            seconds: Time in seconds before cache is considered stale
        """
        if seconds < 0:
            seconds = 0
            
        self._cache_ttl = seconds
        logger.debug(f"Cache TTL set to {seconds} seconds")

    def check_all_permissions(self) -> Dict[str, Tuple[bool, str]]:
        """
        Check permissions for all configuration files.
        
        Returns:
            Dict mapping file paths to (has_permission, error_message) tuples
        """
        results = {}
        for file_path in [self.BOT_CONFIG_FILE, self.DOCKER_CONFIG_FILE, 
                         self.CHANNELS_CONFIG_FILE, self.WEB_CONFIG_FILE]:
            results[file_path] = self._check_file_permissions(file_path)
        return results


# Create the global config manager instance
_config_manager = None

def get_config_manager() -> ConfigManager:
    """
    Get the global ConfigManager instance.
    
    Returns:
        ConfigManager singleton instance
    """
    global _config_manager
    if _config_manager is None:
        # Ensure the configuration directory exists before the ConfigManager is initialized
        ensure_config_directory()
        _config_manager = ConfigManager()
    return _config_manager

# Compatibility functions for the old API

def load_config() -> Dict[str, Any]:
    """
    Load configuration using the new ConfigManager.
    Compatibility function for the old load_config API.
    
    Returns:
        Dict containing the full configuration.
    """
    return get_config_manager().get_config()

def save_config(config_data: Dict[str, Any]) -> bool:
    """
    Save configuration using the new ConfigManager.
    Compatibility function for the old save_config API.
    
    Args:
        config_data: Configuration to save
        
    Returns:
        bool: Success or failure
    """
    return get_config_manager().save_config(config_data)

def get_server_config(server_name: str) -> Optional[Dict[str, Any]]:
    """
    Get server configuration using the new ConfigManager.
    Compatibility function for the old get_server_config API.
    
    Args:
        server_name: Name of the server
        
    Returns:
        Server configuration or None
    """
    return get_config_manager().get_server_config(server_name)

def update_server_config(server_name: str, new_config_data: Dict[str, Any]) -> bool:
    """
    Update server configuration using the new ConfigManager.
    Compatibility function for the old update_server_config API.
    
    Args:
        server_name: Name of the server
        new_config_data: New configuration
        
    Returns:
        bool: Success or failure
    """
    return get_config_manager().update_server_config(server_name, new_config_data) 