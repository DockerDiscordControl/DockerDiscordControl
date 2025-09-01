# -*- coding: utf-8 -*-
"""
Config Manager V2 - Simplified config manager using service architecture
"""

import os
import time
import base64
import logging
from typing import Dict, Any, Optional, Callable, List
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from services.config.unified_config_service import get_unified_config_service

# Token encryption constants
_TOKEN_ENCRYPTION_SALT = b'ddc-salt-for-token-encryption-key-v1'
_PBKDF2_ITERATIONS = 260000
_GLOBAL_FAILED_DECRYPT_CACHE = set()

logger = logging.getLogger('ddc.config_manager')

class ConfigManager:
    """Simplified config manager using service architecture."""
    
    _instance = None
    _is_initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._service = get_unified_config_service()
        self._subscribers: List[Callable] = []
        self._config_cache = None
        self._cache_timestamp = 0
        self._save_in_progress = False
        self._last_cache_invalidation = 0
        self._min_invalidation_interval = 30.0
        
        # Token decryption cache
        self._token_cache = None
        self._token_cache_hash_source = None
        
        self._initialized = True
        
        # Load initial config
        self._load_config_from_disk()
    
    def _load_config_from_disk(self) -> Dict[str, Any]:
        """Load configuration from disk."""
        try:
            config = self._service.get_legacy_config()
            
            # Sync advanced settings to environment variables on load
            self._sync_advanced_settings_to_environment(config)
            
            self._config_cache = config
            self._cache_timestamp = time.time()
            return config
        except Exception as e:
            print(f"Error loading config from disk: {e}")
            return self._get_config_fallback()
    
    def get_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """Get configuration with optional force reload."""
        if self._save_in_progress and not force_reload:
            return self._config_cache or self._get_config_fallback()
        
        if force_reload or self._config_cache is None or self._should_reload_cache():
            config = self._load_config_from_disk()
            
            # Decrypt token if needed
            token_to_decrypt = config.get('bot_token')
            current_hash = config.get('web_ui_password_hash')
            if token_to_decrypt and current_hash:
                decrypted_token = self._decrypt_token(token_to_decrypt, current_hash)
                if decrypted_token:  # Only set if decryption was successful
                    config['bot_token_decrypted_for_usage'] = decrypted_token
            
            # Sync advanced settings to environment variables on load
            self._sync_advanced_settings_to_environment(config)
            
            self._config_cache = config
            self._cache_timestamp = time.time()
        else:
            # If using cached config, ensure decrypted token is available
            config = self._config_cache.copy()
            if 'bot_token_decrypted_for_usage' not in config:
                token_to_decrypt = config.get('bot_token')
                current_hash = config.get('web_ui_password_hash')
                if token_to_decrypt and current_hash:
                    decrypted_token = self._decrypt_token(token_to_decrypt, current_hash)
                    if decrypted_token:
                        config['bot_token_decrypted_for_usage'] = decrypted_token
                        self._config_cache = config  # Update cache
        
        return self._config_cache or self._get_config_fallback()
    
    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """Save configuration."""
        try:
            self._save_in_progress = True
            config = config_data.copy()
            
            # Handle password change and token re-encryption
            from werkzeug.security import generate_password_hash
            new_password = config.pop('new_web_ui_password', None)
            if new_password:
                password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
                config['web_ui_password_hash'] = password_hash
                
                # Clear global failed decrypt cache since password changed
                _GLOBAL_FAILED_DECRYPT_CACHE.clear()
                logger.info("Cleared global failed decrypt cache due to password change")
                
                # Re-encrypt bot token with new password if needed
                token_value = config.get('bot_token')
                if token_value:
                    # First, try to get the plaintext token
                    plaintext_token = None
                    
                    # Check if it's already plaintext (not encrypted)
                    if not token_value.startswith('gAAAAA'):  # Fernet tokens start with gAAAAA
                        plaintext_token = token_value
                        logger.info("Using existing plaintext token for re-encryption")
                    else:
                        # Try to decrypt with old password hash first
                        old_password_hash = self._config_cache.get('web_ui_password_hash') if self._config_cache else None
                        if old_password_hash:
                            try:
                                plaintext_token = self._decrypt_token(token_value, old_password_hash)
                                if plaintext_token:
                                    logger.info("Successfully decrypted token with old password for re-encryption")
                            except Exception as e:
                                logger.warning(f"Could not decrypt token with old password: {e}")
                    
                    # Re-encrypt with new password if we have plaintext
                    if plaintext_token:
                        encrypted_token = self._encrypt_token(plaintext_token, password_hash)
                        if encrypted_token:
                            config['bot_token'] = encrypted_token
                            logger.info("Successfully re-encrypted bot token with new password")
                        else:
                            logger.error("Failed to encrypt token with new password")
                    else:
                        logger.error("Could not obtain plaintext token for re-encryption - token may become unusable")
            
            # Remove runtime-only fields
            if 'bot_token_decrypted_for_usage' in config:
                del config['bot_token_decrypted_for_usage']
            
            # Sync advanced settings to environment
            self._sync_advanced_settings_to_environment(config)
            
            # Save via service
            success = self._service.save_config(config)
            
            if success:
                self._config_cache = config_data.copy()
                self._cache_timestamp = time.time()
                self._notify_subscribers(config_data)
            
            return success
            
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
        finally:
            self._save_in_progress = False
    
    def get_server_config(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific server."""
        return self._service.get_server_config(server_name)
    
    def update_server_config(self, server_name: str, new_config_data: Dict[str, Any]) -> bool:
        """Update configuration for a specific server."""
        success = self._service.update_server_config(server_name, new_config_data)
        if success:
            # Invalidate cache and notify subscribers
            self._config_cache = None
            config = self.get_config(force_reload=True)
            self._notify_subscribers(config)
        return success
    
    def get_server_info_config(self, server_name: str) -> Dict[str, Any]:
        """Get info configuration for a server."""
        server_config = self.get_server_config(server_name)
        if server_config:
            return server_config.get('info', self._get_default_info_config())
        return self._get_default_info_config()
    
    def update_server_info_config(self, server_name: str, info_config: Dict[str, Any]) -> bool:
        """Update info configuration for a server."""
        server_config = self.get_server_config(server_name)
        if server_config:
            updated_config = server_config.copy()
            updated_config['info'] = info_config
            return self.update_server_config(server_name, updated_config)
        return False
    
    def subscribe_to_changes(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe to configuration changes."""
        self._subscribers.append(callback)
    
    def invalidate_cache(self) -> None:
        """Invalidate the configuration cache."""
        current_time = time.time()
        if current_time - self._last_cache_invalidation < self._min_invalidation_interval:
            return
        
        self._config_cache = None
        self._last_cache_invalidation = current_time
    
    def _should_reload_cache(self) -> bool:
        """Check if cache should be reloaded."""
        if not self._config_cache:
            return True
        
        # Reload every 60 seconds
        return time.time() - self._cache_timestamp > 60
    
    def _sync_advanced_settings_to_environment(self, config: Dict[str, Any]) -> None:
        """Sync advanced settings to environment variables."""
        try:
            advanced_settings = config.get('advanced_settings', {})
            for key, value in advanced_settings.items():
                if key.startswith('DDC_'):
                    os.environ[key] = str(value)
        except Exception:
            pass  # Silent fail to avoid breaking config saves
    
    def _notify_subscribers(self, config: Dict[str, Any]) -> None:
        """Notify subscribers of configuration changes."""
        for callback in self._subscribers:
            try:
                callback(config)
            except Exception as e:
                print(f"Error notifying config subscriber: {e}")
    
    def _get_default_info_config(self) -> Dict[str, Any]:
        """Get default info configuration for servers."""
        return {
            "enabled": False,
            "show_ip": False,
            "custom_ip": "",
            "custom_port": "",
            "custom_text": ""
        }
    
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
        # If token doesn't start with 'gAAAAA', it's likely plaintext - return as is
        if not encrypted_token_str.startswith('gAAAAA'):
            logger.debug("Token appears to be plaintext, returning as-is")
            return encrypted_token_str
        # Check if we've already failed to decrypt this token/hash combination (global cache)
        cache_key = f"{encrypted_token_str[:20]}:{password_hash[:20]}"
        if cache_key in _GLOBAL_FAILED_DECRYPT_CACHE:
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
            _GLOBAL_FAILED_DECRYPT_CACHE.add(cache_key)
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
    
    def check_all_permissions(self) -> Dict[str, tuple]:
        """Check file permissions for all config files.
        
        Returns:
            Dict with file paths as keys and (has_permission, error_msg) tuples as values
        """
        import os
        results = {}
        
        try:
            # Get config files from service
            config_dir = self._service.config_dir
            
            # Check all potential config files
            config_files = [
                config_dir / "bot_config.json",
                config_dir / "docker_config.json", 
                config_dir / "channels_config.json",
                config_dir / "web_config.json"
            ]
            
            for config_file in config_files:
                if config_file.exists():
                    # On Unraid/network shares, permission checks may fail even when files are accessible
                    # Try to actually read/write to test real permissions
                    try:
                        # Test read access
                        with open(config_file, 'r') as f:
                            f.read(1)  # Read one character to test
                        # Test write access by touching the file
                        config_file.touch()
                        results[str(config_file)] = (True, "OK - Tested read/write")
                    except (PermissionError, OSError) as perm_error:
                        results[str(config_file)] = (False, f"Cannot read/write: {perm_error}")
                    except Exception as test_error:
                        # File might be corrupted but permissions are OK
                        results[str(config_file)] = (True, f"Accessible but may need repair: {test_error}")
                else:
                    # Try to create parent directory
                    try:
                        config_file.parent.mkdir(parents=True, exist_ok=True)
                        results[str(config_file)] = (True, "File will be created")
                    except Exception as create_error:
                        results[str(config_file)] = (False, f"Cannot create directory: {create_error}")
                    
        except Exception as e:
            results["config"] = (False, f"Error checking config permissions: {e}")
            
        return results
    
    def _get_config_fallback(self) -> Dict[str, Any]:
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
    
    def _check_startup_permissions(self) -> None:
        """Check file permissions on startup."""
        # This will be handled by individual domain services
        pass

def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    return ConfigManager()

# Legacy compatibility functions
def load_config() -> Dict[str, Any]:
    """Load configuration."""
    manager = get_config_manager()
    return manager.get_config()

def save_config(config_data: Dict[str, Any]) -> bool:
    """Save configuration."""
    manager = get_config_manager()
    return manager.save_config(config_data)

def get_server_config(server_name: str) -> Optional[Dict[str, Any]]:
    """Get server configuration."""
    manager = get_config_manager()
    return manager.get_server_config(server_name)

def update_server_config(server_name: str, new_config_data: Dict[str, Any]) -> bool:
    """Update server configuration."""
    manager = get_config_manager()
    return manager.update_server_config(server_name, new_config_data)