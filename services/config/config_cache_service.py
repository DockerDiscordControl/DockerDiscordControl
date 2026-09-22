# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
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
            current_time = self.get_config_dir_mtime(config_dir)

            if (cache_key in self._config_cache and
                self._cache_timestamps.get(cache_key, 0) >= current_time):
                return self._config_cache[cache_key].copy()

            return None

    # The directories DDC keeps configuration in, below config/ itself. A
    # directory's mtime moves when an entry in THAT directory is created,
    # renamed or removed - not when a file inside a subdirectory changes. The
    # channel permissions and the container settings, which are the two things
    # an operator actually edits, live one level down (review E29).
    _CONFIG_SUBDIRECTORIES = ('channels', 'containers')

    @staticmethod
    def get_config_dir_mtime(config_dir: Path) -> float:
        """The newest mtime of the config directory and the ones below it.

        This used to be ``config_dir`` alone, and it missed every change to a
        channel or a container file. Nothing broke, because every save path goes
        on to call ``ConfigService.save_config``, which invalidates explicitly,
        and the bot and the web panel are one process - so that invalidation
        reaches both (measured: a single ``python3 run.py`` in the container).

        What this check is for is the case where nothing called it: a file
        edited by hand on the host - normal here, since ``config/`` is mode 700
        and gets edited through the Unraid shell - or a future save path that
        writes a channel file without going through ``save_config``. Then DDC
        served the old configuration until something unrelated touched
        ``config/`` itself, or until a restart, and the change simply did not
        take effect (review E29).

        Two extra stat calls per lookup, against a configuration that silently
        does not apply.
        """
        if not config_dir.exists():
            return 0
        newest = os.path.getmtime(config_dir)
        for name in ConfigCacheService._CONFIG_SUBDIRECTORIES:
            sub = config_dir / name
            try:
                newest = max(newest, os.path.getmtime(sub))
            except OSError:
                # Not every install has both; a fresh one has neither.
                continue
        return newest

    def set_cached_config(self, cache_key: str, config: Dict[str, Any], config_dir: Path,
                          mtime: Optional[float] = None) -> None:
        """
        Cache configuration data.

        Args:
            cache_key: Cache key to store under
            config: Configuration data to cache
            config_dir: Config directory to get modification time
            mtime: Directory mtime captured BEFORE the config was loaded. A save
                that lands during the load then invalidates this entry. Falls
                back to the current mtime when omitted.
        """
        with self._cache_lock:
            current_time = mtime if mtime is not None else self.get_config_dir_mtime(config_dir)
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

        # Under the lock, like every other method of this class - including
        # invalidate_cache(), which clears these very two fields. Unguarded, a
        # reader could catch set_cached_token() between its two writes and hand
        # out the new token next to the old hash: a decrypted bot token for the
        # wrong key (review B35).
        with self._cache_lock:
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
        # Token and hash belong together - see get_cached_token (review B35).
        with self._cache_lock:
            self._token_cache = decrypted_token
            self._token_cache_hash = cache_key
        logger.debug("Token cached successfully")

    def clear_token_cache(self) -> None:
        """Clear token cache only."""
        with self._cache_lock:
            self._token_cache = None
            self._token_cache_hash = None
        logger.debug("Token cache cleared")
