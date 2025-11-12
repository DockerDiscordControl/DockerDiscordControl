# -*- coding: utf-8 -*-
"""
Configuration Cache Service - Handles config caching and token encryption caching
Part of ConfigService refactoring for Single Responsibility Principle
"""

import hashlib
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Dict, Any, Optional

logger = logging.getLogger('ddc.config_cache')


class ConfigCacheService:
    """
    Handles all configuration caching operations.

    Responsibilities:
    - Cache configuration data
    - Cache timestamps for invalidation
    - Cache decrypted tokens
    - Thread-safe cache operations
    """

    def __init__(self):
        """Initialize cache service."""
        self._config_cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_lock = Lock()

        # Token encryption cache
        self._token_cache: Optional[str] = None
        self._token_cache_hash: Optional[str] = None

    def get_cached_config(self, cache_key: str, config_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Get cached configuration if valid.

        Args:
            cache_key: Cache key to lookup
            config_dir: Config directory to check modification time

        Returns:
            Cached config dict if valid, None otherwise
        """
        with self._cache_lock:
            current_time = os.path.getmtime(config_dir) if config_dir.exists() else 0

            if (cache_key in self._config_cache and
                self._cache_timestamps.get(cache_key, 0) >= current_time):
                return self._config_cache[cache_key].copy()

            return None

    def set_cached_config(self, cache_key: str, config: Dict[str, Any], config_dir: Path) -> None:
        """
        Cache configuration data.

        Args:
            cache_key: Cache key to store under
            config: Configuration data to cache
            config_dir: Config directory to get modification time
        """
        with self._cache_lock:
            current_time = os.path.getmtime(config_dir) if config_dir.exists() else 0
            self._config_cache[cache_key] = config.copy()
            self._cache_timestamps[cache_key] = current_time

    def invalidate_cache(self) -> None:
        """Clear all caches."""
        with self._cache_lock:
            self._config_cache.clear()
            self._cache_timestamps.clear()
            self._token_cache = None
            self._token_cache_hash = None
        logger.debug("Cache invalidated")

    def get_cached_token(self, encrypted_token: str, password_hash: str) -> Optional[str]:
        """
        Get cached decrypted token if available.

        Args:
            encrypted_token: Encrypted token
            password_hash: Password hash used for encryption

        Returns:
            Decrypted token if cached, None otherwise
        """
        cache_key = hashlib.sha256(f"{encrypted_token}{password_hash}".encode()).hexdigest()

        if self._token_cache_hash == cache_key and self._token_cache:
            logger.debug("Token cache hit")
            return self._token_cache

        return None

    def set_cached_token(self, encrypted_token: str, password_hash: str, decrypted_token: str) -> None:
        """
        Cache decrypted token.

        Args:
            encrypted_token: Encrypted token
            password_hash: Password hash used for encryption
            decrypted_token: Decrypted token to cache
        """
        cache_key = hashlib.sha256(f"{encrypted_token}{password_hash}".encode()).hexdigest()
        self._token_cache = decrypted_token
        self._token_cache_hash = cache_key
        logger.debug("Token cached successfully")

    def clear_token_cache(self) -> None:
        """Clear token cache only."""
        self._token_cache = None
        self._token_cache_hash = None
        logger.debug("Token cache cleared")
