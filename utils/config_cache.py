# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Config Cache                                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import threading
import logging
import sys
import gc
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

logger = logging.getLogger('ddc.config_cache')

class ConfigCache:
    """
    Thread-safe configuration cache for performance optimization.
    Reduces filesystem I/O by caching frequently accessed config data.
    Enhanced with memory optimization features.
    """
    
    def __init__(self, max_cache_age_minutes: int = 30):
        self._cache: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._last_update: Optional[datetime] = None
        self._max_cache_age = timedelta(minutes=max_cache_age_minutes)
        self._access_count = 0
        
    def set_config(self, config: Dict[str, Any]) -> None:
        """
        Sets the cached configuration.
        
        Args:
            config: The configuration dictionary to cache
        """
        with self._lock:
            # Clear old cache first to free memory
            self._cache.clear()
            
            # Store only essential config data to minimize memory usage
            self._cache = self._optimize_config_for_memory(config.copy() if config else {})
            self._last_update = datetime.now(timezone.utc)
            self._access_count = 0
            logger.debug(f"Config cache updated at {self._last_update} (size: {self._get_cache_size_mb():.2f} MB)")
    
    def _optimize_config_for_memory(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Optimizes config data for memory usage by removing unnecessary data.
        
        Args:
            config: Original configuration dictionary
            
        Returns:
            Memory-optimized configuration dictionary
        """
        # Remove large, rarely-used data that can be loaded on demand
        optimized = config.copy()
        
        # Remove encrypted token data from cache (can be loaded when needed)
        if 'bot_token_encrypted' in optimized:
            del optimized['bot_token_encrypted']
        
        # Keep only essential server data in cache
        if 'servers' in optimized and isinstance(optimized['servers'], list):
            essential_servers = []
            for server in optimized['servers']:
                if isinstance(server, dict):
                    # Keep only essential fields for autocomplete and basic operations
                    essential_server = {
                        'name': server.get('name', ''),
                        'docker_name': server.get('docker_name', ''),
                        'allowed_actions': server.get('allowed_actions', []),
                        'info': server.get('info', {
                            'enabled': False,
                            'show_ip': False,
                            'custom_ip': '',
                            'custom_text': ''
                        })
                    }
                    essential_servers.append(essential_server)
            optimized['servers'] = essential_servers
        
        return optimized
    
    def _get_cache_size_mb(self) -> float:
        """Returns approximate cache size in MB."""
        try:
            return sys.getsizeof(self._cache) / (1024 * 1024)
        except:
            return 0.0
    
    def get_config(self) -> Dict[str, Any]:
        """
        Gets the cached configuration with automatic cleanup.
        
        Returns:
            The cached configuration dictionary
        """
        with self._lock:
            self._access_count += 1
            
            # Perform periodic cleanup every 100 accesses
            if self._access_count % 100 == 0:
                self._cleanup_if_needed()
            
            return self._cache.copy()
    
    def _cleanup_if_needed(self) -> None:
        """Performs memory cleanup if cache is old or too large."""
        now = datetime.now(timezone.utc)
        
        # Clear cache if it's too old
        if (self._last_update and 
            now - self._last_update > self._max_cache_age):
            logger.info("Config cache expired, clearing for memory optimization")
            self._cache.clear()
            self._last_update = None
            gc.collect()  # Force garbage collection
    
    def get_servers(self) -> List[Dict[str, Any]]:
        """
        Gets the servers list from cached configuration.
        Optimized for autocomplete functions.
        
        Returns:
            List of server configurations
        """
        with self._lock:
            return self._cache.get('servers', [])
    
    def get_guild_id(self) -> Optional[int]:
        """
        Gets the guild ID from cached configuration.
        Optimized for autocomplete functions.
        
        Returns:
            Guild ID as integer or None if not configured
        """
        with self._lock:
            guild_id_str = self._cache.get('guild_id')
            if guild_id_str and isinstance(guild_id_str, str) and guild_id_str.isdigit():
                return int(guild_id_str)
            return None
    
    def get_language(self) -> str:
        """
        Gets the language from cached configuration.
        
        Returns:
            Language code (defaults to 'en')
        """
        with self._lock:
            return self._cache.get('language', 'en')
    
    def get_timezone(self) -> str:
        """
        Gets the timezone from cached configuration.
        
        Returns:
            Timezone string (defaults to 'Europe/Berlin')
        """
        with self._lock:
            return self._cache.get('timezone', 'Europe/Berlin')
    
    def get_channel_permissions(self) -> Dict[str, Any]:
        """
        Gets channel permissions from cached configuration.
        
        Returns:
            Channel permissions dictionary
        """
        with self._lock:
            return self._cache.get('channel_permissions', {})
    
    def get_default_channel_permissions(self) -> Dict[str, Any]:
        """
        Gets default channel permissions from cached configuration.
        
        Returns:
            Default channel permissions dictionary
        """
        with self._lock:
            return self._cache.get('default_channel_permissions', {})
    
    def is_valid(self) -> bool:
        """
        Checks if the cache contains valid data.
        
        Returns:
            True if cache is valid, False otherwise
        """
        with self._lock:
            if not self._cache or not self._last_update:
                return False
            
            # Check if cache has expired
            now = datetime.now(timezone.utc)
            return now - self._last_update <= self._max_cache_age
    
    def get_last_update(self) -> Optional[datetime]:
        """
        Gets the timestamp of the last cache update.
        
        Returns:
            Last update timestamp or None if never updated
        """
        with self._lock:
            return self._last_update
    
    def clear(self) -> None:
        """Clears the cache and forces garbage collection."""
        with self._lock:
            self._cache.clear()
            self._last_update = None
            self._access_count = 0
            gc.collect()  # Force garbage collection
            logger.debug("Config cache cleared and garbage collected")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """
        Gets memory usage statistics for the cache.
        
        Returns:
            Dictionary with memory statistics
        """
        with self._lock:
            return {
                'cache_size_mb': self._get_cache_size_mb(),
                'access_count': self._access_count,
                'last_update': self._last_update.isoformat() if self._last_update else None,
                'is_valid': self.is_valid(),
                'entries_count': len(self._cache)
            }

# Global instance with memory optimization
_config_cache = ConfigCache(max_cache_age_minutes=15)  # Reduced from 30 to 15 minutes

def get_config_cache() -> ConfigCache:
    """
    Gets the global config cache instance.
    
    Returns:
        The global ConfigCache instance
    """
    return _config_cache

def init_config_cache(config: Dict[str, Any]) -> None:
    """
    Initializes the global config cache with the provided configuration.
    
    Args:
        config: The configuration dictionary to cache
    """
    _config_cache.set_config(config)
    logger.info("Global config cache initialized with memory optimization")

def get_cached_config() -> Dict[str, Any]:
    """
    Gets the cached configuration. Uses ConfigManager directly for better performance.
    
    Returns:
        The configuration dictionary
    """
    # Use ConfigService directly instead of multiple cache layers
    from services.config.config_service import get_config_service
    return get_config_service().get_config()

def get_cached_servers() -> List[Dict[str, Any]]:
    """
    Gets the servers list from cache. Optimized for autocomplete.
    
    Returns:
        List of server configurations
    """
    if _config_cache.is_valid():
        return _config_cache.get_servers()
    else:
        return get_cached_config().get('servers', [])

def get_cached_guild_id() -> Optional[int]:
    """
    Gets the guild ID from cache. Optimized for autocomplete.
    
    Returns:
        Guild ID as integer or None
    """
    if _config_cache.is_valid():
        return _config_cache.get_guild_id()
    else:
        config = get_cached_config()
        guild_id_str = config.get('guild_id')
        if guild_id_str and isinstance(guild_id_str, str) and guild_id_str.isdigit():
            return int(guild_id_str)
        return None

def get_cache_memory_stats() -> Dict[str, Any]:
    """
    Gets memory usage statistics for the global config cache.
    
    Returns:
        Dictionary with memory statistics
    """
    return _config_cache.get_memory_stats() 