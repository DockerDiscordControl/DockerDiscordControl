# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Docker utilities for container management
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List
import docker
import docker.client
from utils.logging_utils import setup_logger
from utils.container_image import image_name_of
import time
import os
import json
import threading

# Import custom exceptions
from services.exceptions import (
    DockerServiceError, DockerConnectionError, DockerCommandTimeoutError,
    ContainerNotFoundError, ContainerActionError, ConfigLoadError
)

# Logger for Docker utils
logger = setup_logger('ddc.docker_utils', level=logging.INFO)

# Import the modern async connection pool
try:
    # Imported to find out whether the pool is there at all; the name itself is
    # not used here any more since the synchronous client getter was removed
    # (operator decision 2026-09-23, tests/spec/test_there_is_one_way_to_a_docker_client.py).
    from .docker_client_pool import get_docker_client_service  # noqa: F401
    USE_CONNECTION_POOL = True
    logger.info("Modern Async Docker Queue System enabled for optimal performance")
except ImportError:
    USE_CONNECTION_POOL = False
    logger.warning("Docker Connection Pool not available, using legacy single client")

# PERFORMANCE OPTIMIZATION: Flexible container timeout configuration
# Load from Advanced Settings first, then environment variables, then defaults
def _load_timeout_from_config(config_key: str, env_key: str, default: str) -> float:
    """Load timeout value from Advanced Settings config first, then env var, then default."""
    try:
        from services.config.config_service import load_config
        config = load_config()
        advanced_settings = config.get('advanced_settings', {})
        if config_key in advanced_settings:
            # The configured value, as configured. A block marked "TEMPORARY
            # FIX" used to replace any DDC_FAST_STATS_TIMEOUT or
            # DDC_FAST_INFO_TIMEOUT below 30 with 45.0 and log the substitution
            # at INFO. The panel offers both fields with min="1" max="60" and
            # suggests 10 - so the value the panel itself proposes was dead,
            # along with everything from 1 to 29. A form that accepts a number
            # and then ignores it is worse than one that refuses it (review
            # C59). If the daemon really is too slow for the chosen value, the
            # operator sees the timeouts and can raise it.
            return float(advanced_settings[config_key])
    except (ConfigLoadError, KeyError, ValueError, TypeError) as e:
        # Config loading/parsing errors - fall back to environment variable
        logger.debug(f"Config load failed for {config_key}, using env/default: {e}")

    return float(os.environ.get(env_key, default))

# --------------------------------------------------------------------------- #
# Timeout values - loaded on FIRST ACCESS, not at import time.
#
# These five used to be plain module-level assignments, each calling
# _load_timeout_from_config() and therefore load_config(). That made a bare
# ``import`` read configuration off disk: importing anything from
# ``services.docker_service`` runs ``__init__.py:10``, which pulls this module,
# which read five config files before a single line of caller code ran.
#
# Three problems came with that, and the third is how it was found:
#   1. A failing read does not break a function, it breaks the IMPORT - as an
#      ImportError deep inside a nine-level chain instead of a clear message.
#   2. The net below catches (ConfigLoadError, KeyError, ValueError, TypeError).
#      An AttributeError went straight through it.
#   3. WHEN the config is read depended on who imported first. That made two
#      tests in tests/unit/audit_2026_09/test_r2_g5_mech.py pass in their group
#      and fail alone - found by running all 127 test files in isolation.
#      See docs/quality/STAGE3_TESTS_THAT_CANNOT_FAIL.md.
#
# Module-level __getattr__ (PEP 562) keeps every reader unchanged: the names
# still resolve to floats, CONTAINER_TYPE_PATTERNS and DEFAULT_TIMEOUT_CONFIG
# still are dicts with the same keys. Only the moment of loading moved.
# --------------------------------------------------------------------------- #

_TIMEOUT_SPECS = {
    'DEFAULT_FAST_STATS_TIMEOUT': ('DDC_FAST_STATS_TIMEOUT', '45.0'),
    'DEFAULT_SLOW_STATS_TIMEOUT': ('DDC_SLOW_STATS_TIMEOUT', '60.0'),
    'DEFAULT_FAST_INFO_TIMEOUT': ('DDC_FAST_INFO_TIMEOUT', '45.0'),
    'DEFAULT_SLOW_INFO_TIMEOUT': ('DDC_SLOW_INFO_TIMEOUT', '60.0'),
    'DEFAULT_CONTAINER_LIST_TIMEOUT': ('DDC_CONTAINER_LIST_TIMEOUT', '30.0'),
}

_lazy_values: Dict[str, Any] = {}


def _timeout(name: str) -> float:
    """Return a timeout, loading it from the config once and caching it."""
    if name not in _lazy_values:
        key, default = _TIMEOUT_SPECS[name]
        _lazy_values[name] = _load_timeout_from_config(key, key, default)
        # Logged here rather than at import: same information, but only once the
        # value is actually wanted.
        logger.info(f"[TIMEOUT_CONFIG] {key}: {_lazy_values[name]}s")
    return _lazy_values[name]


def _build_container_type_patterns() -> Dict[str, Any]:
    """Pattern-based timeout configuration (flexible and maintainable)."""
    return {
        'game_server': {
            'patterns': [
                'minecraft', 'factorio', 'terraria', 'starbound', 'rust', 'ark', 'palworld',
                'satisfactory', 'valheim', 'v-rising', 'vrising', 'conan', 'dayz', 'csgo',
                'tf2', 'gmod', 'arma', 'squad', 'insurgency', 'mordhau', 'chivalry',
                'space-engineers', 'astroneer', 'raft', 'green-hell', 'the-forest',
                'subnautica', 'no-mans-sky', 'kerbal', 'cities-skylines', 'farming-simulator',
                'truck-simulator', 'train-simulator', 'flight-simulator', 'assetto-corsa',
                'project-cars', 'dirt-rally', 'f1-', 'gran-turismo', 'forza'
            ],
            'stats_timeout': _timeout('DEFAULT_FAST_STATS_TIMEOUT'),
            'info_timeout': _timeout('DEFAULT_FAST_INFO_TIMEOUT')  # Fixed: Game servers should also have fast info timeouts
        },
        'media_server': {
            'patterns': [
                'plex', 'jellyfin', 'emby', 'kodi', 'sonarr', 'radarr', 'lidarr',
                'bazarr', 'prowlarr', 'jackett', 'transmission', 'qbittorrent',
                'deluge', 'rtorrent', 'sabnzbd', 'nzbget', 'overseerr', 'ombi',
                'tautulli', 'organizr', 'heimdall', 'muximux'
            ],
            'stats_timeout': _timeout('DEFAULT_SLOW_STATS_TIMEOUT'),
            'info_timeout': _timeout('DEFAULT_FAST_INFO_TIMEOUT')
        },
        'database': {
            'patterns': [
                'mysql', 'mariadb', 'postgres', 'postgresql', 'mongodb', 'redis',
                'elasticsearch', 'influxdb', 'grafana', 'prometheus', 'clickhouse',
                'cassandra', 'couchdb', 'neo4j', 'memcached', 'sqlite'
            ],
            'stats_timeout': _timeout('DEFAULT_SLOW_STATS_TIMEOUT'),
            'info_timeout': _timeout('DEFAULT_FAST_INFO_TIMEOUT')
        },
        'web_server': {
            'patterns': [
                'nginx', 'apache', 'httpd', 'caddy', 'traefik', 'haproxy',
                'nodejs', 'node', 'php', 'python', 'django', 'flask',
                'wordpress', 'nextcloud', 'owncloud', 'photoprism', 'bitwarden'
            ],
            'stats_timeout': _timeout('DEFAULT_SLOW_STATS_TIMEOUT'),
            'info_timeout': _timeout('DEFAULT_FAST_INFO_TIMEOUT')
        }
    }


def _build_default_timeout_config() -> Dict[str, Any]:
    """Default timeout configuration."""
    return {
        'stats_timeout': _timeout('DEFAULT_FAST_STATS_TIMEOUT'),  # Use fast stats for default
        'info_timeout': _timeout('DEFAULT_FAST_INFO_TIMEOUT')     # Use fast info for default
    }


# The names below are resolved on first access instead of at import time.
# Everything a reader sees stays the same: the five DEFAULT_*_TIMEOUT names are
# floats, CONTAINER_TYPE_PATTERNS and DEFAULT_TIMEOUT_CONFIG are dicts with the
# same keys. Only the moment of loading moved. See the block above for why.
_LAZY_BUILDERS = {
    'CONTAINER_TYPE_PATTERNS': _build_container_type_patterns,
    'DEFAULT_TIMEOUT_CONFIG': _build_default_timeout_config,
    '_CACHE_TTL': lambda: _get_cache_ttl(),
}


def _lazy_value(name: str) -> Any:
    """Read one of the lazily built values from inside this module.

    Needed because module-level __getattr__ (PEP 562) is only consulted for
    attribute access from OUTSIDE (``docker_utils.X``). A bare name inside a
    function body is looked up in globals() and would raise NameError, so every
    in-module reader goes through here.
    """
    if name not in _lazy_values:
        _lazy_values[name] = _LAZY_BUILDERS[name]()
    return _lazy_values[name]


def __getattr__(name: str) -> Any:
    """PEP 562 module-level attribute access for the lazily loaded values.

    Python only calls this for names that are NOT already in the module
    namespace, so it costs nothing for every other attribute.
    """
    if name in _TIMEOUT_SPECS:
        return _timeout(name)
    if name in _LAZY_BUILDERS:
        if name not in _lazy_values:
            _lazy_values[name] = _LAZY_BUILDERS[name]()
        return _lazy_values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Load custom timeout configuration from file
_custom_timeout_config = None
_custom_config_loaded = False

def load_custom_timeout_config():
    """Load custom timeout configuration from JSON file."""
    global _custom_timeout_config, _custom_config_loaded

    if _custom_config_loaded:
        return _custom_timeout_config

    _custom_config_loaded = True
    # Via utils/config_paths.py (DDC_CONFIG_DIR) - derived from __file__
    # before, so custom timeouts in a DDC_CONFIG_DIR volume were never read.
    from utils.config_paths import get_config_dir
    config_path = get_config_dir() / "container_timeouts.json"

    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                _custom_timeout_config = json.load(f)
                logger.info(f"Loaded custom container timeout configuration from {config_path}")
                return _custom_timeout_config
        else:
            logger.debug(f"Custom timeout config file not found at {config_path}")
    except (json.JSONDecodeError, IOError, OSError, ValueError) as e:
        logger.warning(f"Failed to load custom timeout config: {e}")

    return None

def get_container_timeouts(container_name: str) -> dict:
    """
    Get timeout configuration for a specific container based on flexible patterns and custom config.

    Args:
        container_name: Name of the Docker container

    Returns:
        Dict with 'stats_timeout' and 'info_timeout' values
    """
    if not container_name:
        return _lazy_value('DEFAULT_TIMEOUT_CONFIG').copy()

    container_lower = container_name.lower()

    # Load custom configuration
    custom_config = load_custom_timeout_config()

    # 1. Check for exact container name override first (highest priority)
    if custom_config and 'container_overrides' in custom_config:
        container_overrides = custom_config['container_overrides']
        if container_name in container_overrides:
            override_config = container_overrides[container_name]
            logger.debug(f"Container '{container_name}' using exact name override")
            return {
                'stats_timeout': override_config.get('stats_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['stats_timeout']),
                'info_timeout': override_config.get('info_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['info_timeout'])
            }

    # 2. Check custom patterns (medium priority)
    if custom_config and 'custom_patterns' in custom_config:
        for pattern_name, pattern_config in custom_config['custom_patterns'].items():
            if 'patterns' in pattern_config:
                for pattern in pattern_config['patterns']:
                    if pattern in container_lower:
                        logger.debug(f"Container '{container_name}' matches custom pattern '{pattern}' from {pattern_name}")
                        return {
                            'stats_timeout': pattern_config.get('stats_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['stats_timeout']),
                            'info_timeout': pattern_config.get('info_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['info_timeout'])
                        }

    # 3. Check built-in container type patterns (lowest priority)
    for container_type, config in _lazy_value('CONTAINER_TYPE_PATTERNS').items():
        for pattern in config['patterns']:
            if pattern in container_lower:
                logger.debug(f"Container '{container_name}' matches built-in {container_type} pattern '{pattern}'")
                return {
                    'stats_timeout': config['stats_timeout'],
                    'info_timeout': config['info_timeout']
                }

    # Return default if no pattern matches
    logger.debug(f"Container '{container_name}' using default timeout configuration")
    return _lazy_value('DEFAULT_TIMEOUT_CONFIG').copy()

def get_container_type_info(container_name: str) -> dict:
    """
    Get container type information for debugging and monitoring.

    Args:
        container_name: Name of the Docker container

    Returns:
        Dict with container type information including custom configuration
    """
    if not container_name:
        return {'type': 'unknown', 'matched_pattern': None, 'timeout_config': _lazy_value('DEFAULT_TIMEOUT_CONFIG'), 'config_source': 'default'}

    container_lower = container_name.lower()
    custom_config = load_custom_timeout_config()

    # Check for exact container name override first
    if custom_config and 'container_overrides' in custom_config:
        container_overrides = custom_config['container_overrides']
        if container_name in container_overrides:
            override_config = container_overrides[container_name]
            return {
                'type': 'custom_override',
                'matched_pattern': container_name,
                'timeout_config': {
                    'stats_timeout': override_config.get('stats_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['stats_timeout']),
                    'info_timeout': override_config.get('info_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['info_timeout'])
                },
                'config_source': 'custom_override'
            }

    # Check custom patterns
    if custom_config and 'custom_patterns' in custom_config:
        for pattern_name, pattern_config in custom_config['custom_patterns'].items():
            if 'patterns' in pattern_config:
                for pattern in pattern_config['patterns']:
                    if pattern in container_lower:
                        return {
                            'type': f'custom_{pattern_name}',
                            'matched_pattern': pattern,
                            'timeout_config': {
                                'stats_timeout': pattern_config.get('stats_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['stats_timeout']),
                                'info_timeout': pattern_config.get('info_timeout', _lazy_value('DEFAULT_TIMEOUT_CONFIG')['info_timeout'])
                            },
                            'config_source': 'custom_pattern'
                        }

    # Check built-in container type patterns
    for container_type, config in _lazy_value('CONTAINER_TYPE_PATTERNS').items():
        for pattern in config['patterns']:
            if pattern in container_lower:
                return {
                    'type': container_type,
                    'matched_pattern': pattern,
                    'timeout_config': {
                        'stats_timeout': config['stats_timeout'],
                        'info_timeout': config['info_timeout']
                    },
                    'config_source': 'built_in'
                }

    return {
        'type': 'default',
        'matched_pattern': None,
        'timeout_config': _lazy_value('DEFAULT_TIMEOUT_CONFIG'),
        'config_source': 'default'
    }

def get_smart_timeout(operation: str = 'default', container_name: str = None) -> float:
    """
    Get intelligent timeout based on Advanced Settings and container type.

    Args:
        operation: Type of operation ('stats', 'info', 'list', 'action', 'default')
        container_name: Container name for type-specific optimization

    Returns:
        Timeout in seconds from Advanced Settings
    """
    # Container type-specific timeout optimization
    if container_name:
        container_type_info = get_container_type_info(container_name)
        timeout_config = container_type_info.get('timeout_config', {})

        if operation == 'stats':
            timeout_value = timeout_config.get('stats_timeout', _timeout('DEFAULT_FAST_STATS_TIMEOUT'))
            logger.debug(f"[TIMEOUT_DEBUG] {container_name}: stats operation -> {timeout_value}s (type: {container_type_info.get('type', 'unknown')}, source: {container_type_info.get('config_source', 'unknown')})")
            return timeout_value
        elif operation == 'info':
            timeout_value = timeout_config.get('info_timeout', _timeout('DEFAULT_FAST_INFO_TIMEOUT'))
            logger.debug(f"[TIMEOUT_DEBUG] {container_name}: info operation -> {timeout_value}s (type: {container_type_info.get('type', 'unknown')}, source: {container_type_info.get('config_source', 'unknown')})")
            return timeout_value

    # Global operation timeouts from Advanced Settings
    if operation == 'stats':
        logger.debug(f"[TIMEOUT_DEBUG] No container specified: stats operation -> {_timeout('DEFAULT_FAST_STATS_TIMEOUT')}s (global)")
        return _timeout('DEFAULT_FAST_STATS_TIMEOUT')  # From DDC_FAST_STATS_TIMEOUT
    elif operation == 'info':
        logger.debug(f"[TIMEOUT_DEBUG] No container specified: info operation -> {_timeout('DEFAULT_FAST_INFO_TIMEOUT')}s (global)")
        return _timeout('DEFAULT_FAST_INFO_TIMEOUT')   # From DDC_FAST_INFO_TIMEOUT
    elif operation == 'list':
        logger.debug(f"[TIMEOUT_DEBUG] No container specified: list operation -> {_timeout('DEFAULT_CONTAINER_LIST_TIMEOUT')}s (global)")
        return _timeout('DEFAULT_CONTAINER_LIST_TIMEOUT')  # From DDC_CONTAINER_LIST_TIMEOUT
    elif operation == 'action':
        logger.debug(f"[TIMEOUT_DEBUG] No container specified: action operation -> {_timeout('DEFAULT_FAST_INFO_TIMEOUT')}s (global)")
        return _timeout('DEFAULT_FAST_INFO_TIMEOUT')   # Actions are usually fast
    else:
        logger.debug(f"[TIMEOUT_DEBUG] No container specified: default operation -> {_timeout('DEFAULT_FAST_STATS_TIMEOUT')}s (global)")
        return _timeout('DEFAULT_FAST_STATS_TIMEOUT')  # Default fallback


def get_docker_client_async(timeout: float = None, operation: str = 'default', container_name: str = None):
    """
    Modern async Docker client with intelligent queue system and Advanced Settings integration.

    This is the OPTIMAL version that uses your configured Advanced Settings timeouts.
    Returns an async context manager with queue integration.

    Usage:
        async with get_docker_client_async(operation='stats', container_name='nginx') as client:
            containers = await asyncio.to_thread(client.containers.list)

    Args:
        timeout: Manual timeout override (if None, uses Advanced Settings)
        operation: Operation type for smart timeout selection
        container_name: Container name for type-specific optimization

    Features:
        - Advanced Settings timeout integration (DDC_FAST_STATS_TIMEOUT, etc.)
        - Container-type-specific timeout optimization
        - Intelligent queueing when pool is full
        - Real-time performance statistics
        - Automatic resource cleanup
    """
    # Use Advanced Settings smart timeout if not manually specified
    if timeout is None:
        timeout = get_smart_timeout(operation, container_name)
    if USE_CONNECTION_POOL:
        try:
            # SERVICE FIRST: Use new Docker Client Service with backward compatibility context manager
            from .docker_client_pool import get_docker_client_async
            return get_docker_client_async(timeout=timeout, operation=operation, container_name=container_name)
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.warning(f"Connection pool failed, falling back: {e}")

    # Fallback to individual client creation
    from contextlib import asynccontextmanager

    from .client_factory import build_docker_client

    @asynccontextmanager
    async def individual_client():
        client = None
        try:
            # Through the one client factory (follows DOCKER_HOST, the v3.0
            # proxy), with the timeout worked out above. It used to call
            # docker.from_env() bare, which meant docker-py's 60 s whatever the
            # operation - the smart timeout was computed and then ignored here.
            client = await asyncio.to_thread(build_docker_client, timeout=timeout)
            yield client
        finally:
            if client:
                try:
                    await asyncio.to_thread(client.close)
                except (OSError, RuntimeError, AttributeError) as e:
                    # Client close errors are non-critical - just log
                    logger.debug(f"Error closing Docker client: {e}")

    # Called, not handed over: every caller writes "async with
    # get_docker_client_async(...)", and the bare function has no __aenter__ - so
    # the safety net raised TypeError exactly when the connection pool was gone
    # and it was the only thing left (review C4).
    return individual_client()

class DockerError(Exception):
    """Custom exception class for Docker-related errors."""
    pass

async def get_docker_stats(docker_container_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Gets CPU and memory usage for a Docker container using the SDK.
    Now uses Advanced Settings timeouts for optimal performance.

    Args:
        docker_container_name: Name of the Docker container

    Returns:
        Tuple of (CPU percentage, memory usage) or (None, None) on error
    """
    if not docker_container_name:
        return None, None

    # 🔒 SECURITY: Validate container name format before Docker API call
    from utils.common_helpers import validate_container_name
    if not validate_container_name(docker_container_name):
        logger.error(f"get_docker_stats: Invalid container name format: {docker_container_name}")
        return None, None

    try:
        # 🔧 PERFORMANCE: Use Advanced Settings timeout (DDC_FAST_STATS_TIMEOUT) + container-specific optimization
        operation_timeout = get_smart_timeout('stats', docker_container_name)
        logger.debug(f"[get_docker_stats] {docker_container_name}: Starting with operation_timeout={operation_timeout}s")

        overall_start = time.time()
        async with get_docker_client_async(operation='stats', container_name=docker_container_name) as client:
            pool_time = (time.time() - overall_start) * 1000
            logger.debug(f"[get_docker_stats] {docker_container_name}: Got client from pool in {pool_time:.1f}ms")

            start_time = time.time()

            try:
                # Add operation-specific timeout to prevent hanging Docker API calls
                get_start = time.time()
                container = await asyncio.wait_for(
                    asyncio.to_thread(client.containers.get, docker_container_name),
                    timeout=operation_timeout
                )
                get_time = (time.time() - get_start) * 1000
                logger.debug(f"[get_docker_stats] {docker_container_name}: container.get() took {get_time:.1f}ms")

                # Stats can be slower, use same timeout but track it
                stats_start = time.time()
                stats = await asyncio.wait_for(
                    asyncio.to_thread(container.stats, stream=False),
                    timeout=operation_timeout
                )
                stats_time = (time.time() - stats_start) * 1000
                logger.debug(f"[get_docker_stats] {docker_container_name}: container.stats() took {stats_time:.1f}ms")

                elapsed_time = (time.time() - start_time) * 1000
                if elapsed_time > 5000:  # Over 5 seconds - informational only
                    logger.info(f"Long stats call for {docker_container_name}: {elapsed_time:.1f}ms (but got real data)")
                elif elapsed_time > 2000:  # Over 2 seconds
                    logger.debug(f"Slow stats call for {docker_container_name}: {elapsed_time:.1f}ms")

            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting stats for {docker_container_name}")
                return None, None
            except (docker.errors.DockerException, OSError, RuntimeError) as e:
                logger.warning(f"Docker error getting stats for {docker_container_name}: {e}")
                return None, None

            cpu_usage = stats.get('cpu_stats', {}).get('cpu_usage', {}).get('total_usage', 0)
            system_cpu_usage = stats.get('cpu_stats', {}).get('system_cpu_usage', 0)
            previous_cpu = stats.get('precpu_stats', {}).get('cpu_usage', {}).get('total_usage', 0)
            previous_system = stats.get('precpu_stats', {}).get('system_cpu_usage', 0)

            cpu_delta = cpu_usage - previous_cpu
            system_delta = system_cpu_usage - previous_system

            cpu_percent = 'N/A'
            if cpu_delta > 0 and system_delta > 0:
                online_cpus = stats.get('cpu_stats', {}).get('online_cpus')
                if online_cpus is None: # Fallback for older Docker API versions or if online_cpus is not present
                    percpu_usage = stats.get('cpu_stats', {}).get('cpu_usage', {}).get('percpu_usage', [1])
                    online_cpus = len(percpu_usage) if percpu_usage else 1
                cpu_percent_raw = (cpu_delta / system_delta) * online_cpus * 100.0
                cpu_percent = f"{cpu_percent_raw:.2f}"
            elif stats.get('State', {}).get('Running', False):
                logger.debug(f"Could not calculate CPU percentage for {docker_container_name}. Stats: {stats}")

            memory_usage = stats.get('memory_stats', {}).get('usage', 0)
            mem_usage_str = 'N/A'
            if memory_usage > 0:
                 if memory_usage < 1024 * 1024:
                     mem_usage_str = f"{memory_usage / 1024:.1f} KiB"
                 elif memory_usage < 1024 * 1024 * 1024:
                     mem_usage_str = f"{memory_usage / (1024 * 1024):.1f} MiB"
                 else:
                     mem_usage_str = f"{memory_usage / (1024 * 1024 * 1024):.1f} GiB"
            return cpu_percent, mem_usage_str
    except docker.errors.NotFound:
        logger.warning(f"Container '{docker_container_name}' not found during stats retrieval.")
        return None, None
    except asyncio.TimeoutError:
        logger.error(f"Timeout getting Docker stats for {docker_container_name}")
        return None, None
    # DockerServiceError first: get_docker_client_async raises
    # DockerConnectionError when the daemon cannot be reached at all, and it
    # is in none of the types below. This function is documented "or
    # (None, None) on error" (review E49; E43 repaired its neighbour at 734
    # and left this one).
    except (DockerServiceError, docker.errors.DockerException, OSError, RuntimeError, KeyError, ValueError) as e:
        logger.error(f"Error getting Docker stats for {docker_container_name}: {e}", exc_info=True)
        return None, None

async def get_docker_info(docker_container_name: str) -> Optional[Dict[str, Any]]:
    if not docker_container_name:
        logger.warning("get_docker_info called without container name.")
        return None

    # 🔒 SECURITY: Validate container name format before Docker API call
    from utils.common_helpers import validate_container_name
    if not validate_container_name(docker_container_name):
        logger.error(f"get_docker_info: Invalid container name format: {docker_container_name}")
        return None

    try:
        # 🔧 PERFORMANCE: Use Advanced Settings timeout (DDC_FAST_INFO_TIMEOUT) + container-specific optimization
        operation_timeout = get_smart_timeout('info', docker_container_name)
        logger.debug(f"[get_docker_info] {docker_container_name}: Starting with operation_timeout={operation_timeout}s")

        start_time = time.time()
        async with get_docker_client_async(operation='info', container_name=docker_container_name) as client:
            pool_time = (time.time() - start_time) * 1000
            logger.debug(f"[get_docker_info] {docker_container_name}: Got client from pool in {pool_time:.1f}ms")

            # Add operation-specific timeout to prevent hanging Docker API calls
            api_start = time.time()
            container = await asyncio.wait_for(
                asyncio.to_thread(client.containers.get, docker_container_name),
                timeout=operation_timeout
            )
            api_time = (time.time() - api_start) * 1000
            total_time = (time.time() - start_time) * 1000

            logger.debug(f"[get_docker_info] {docker_container_name}: API call took {api_time:.1f}ms, total {total_time:.1f}ms")
            return container.attrs
    except docker.errors.NotFound:
        logger.warning(f"Container '{docker_container_name}' not found.")
        return None
    except asyncio.TimeoutError:
        logger.error(f"Timeout getting info for '{docker_container_name}'")
        return None
    # DockerServiceError first, for the same reason as get_docker_stats
    # above. The automation service reads None from here as "the running
    # state could not be determined" and says so in the log (review E49).
    except (DockerServiceError, docker.errors.DockerException, OSError, RuntimeError) as e:
        logger.error(f"Docker error in get_docker_info for '{docker_container_name}': {e}", exc_info=True)
        return None

async def docker_action(docker_container_name: str, action: str) -> bool:
    # Honour the container's own StopTimeout (docker-py's restart() would force 10s)
    from .docker_action_service import get_stop_timeout_kwargs
    valid_actions = {
        'start': lambda c: c.start(),
        'stop': lambda c: c.stop(**get_stop_timeout_kwargs(c)),
        'restart': lambda c: c.restart(**get_stop_timeout_kwargs(c)),
    }
    if action not in valid_actions:
        raise DockerError(f"Invalid Docker action: {action}")
    if not docker_container_name:
        logger.error("Docker action failed: No container name provided")
        return False

    # Validate container name format for security
    from utils.common_helpers import validate_container_name
    if not validate_container_name(docker_container_name):
        logger.error(f"Docker action failed: Invalid container name format: {docker_container_name}")
        return False
    try:
        # 🔧 PERFORMANCE: Use Advanced Settings timeout (DDC_FAST_ACTION_TIMEOUT) + container-specific optimization
        async with get_docker_client_async(operation='action', container_name=docker_container_name) as client:
            container = await asyncio.to_thread(client.containers.get, docker_container_name)
            # Noted before the call, taken back only when Docker refused - the
            # same rule as DockerActionService.execute_docker_action, and why.
            from services.automation.own_actions import forget, note_own_action
            note_own_action(docker_container_name, action)
            action_func = valid_actions[action]
            try:
                await asyncio.to_thread(action_func, container)
            except docker.errors.APIError:
                forget(docker_container_name)
                raise
            logger.info(f"Docker action '{action}' on container '{docker_container_name}' successful via SDK")
            return True
    except docker.errors.NotFound:
        logger.warning(f"Container '{docker_container_name}' not found for action '{action}'.")
        return False
    except asyncio.TimeoutError:
        logger.error(f"Timeout during docker action '{action}' on '{docker_container_name}'")
        return False
    except (DockerServiceError, docker.errors.DockerException, docker.errors.APIError, OSError, RuntimeError) as e:
        logger.error(f"Docker error during action '{action}' on '{docker_container_name}': {e}", exc_info=True)
        return False

_containers_cache = None
_cache_timestamp = 0

# Load cache TTL from Advanced Settings to align with user configuration
def _get_cache_ttl() -> int:
    """Get cache TTL from Advanced Settings (DDC_DOCKER_CACHE_DURATION)."""
    try:
        from services.config.config_service import load_config
        config = load_config()
        advanced_settings = config.get('advanced_settings', {})
        return int(advanced_settings.get('DDC_DOCKER_CACHE_DURATION', 30))
    except (ConfigLoadError, KeyError, ValueError, TypeError):
        return 30  # Default fallback

_containers_cache_lock = threading.Lock()  # Thread safety for container cache

async def list_docker_containers() -> List[Dict[str, Any]]:
    try:
        # 🔧 PERFORMANCE: Use Advanced Settings timeout (DDC_FAST_LIST_TIMEOUT) for container listing
        async with get_docker_client_async(operation='list') as client:
            raw_containers = await asyncio.to_thread(client.containers.list, all=True)
            containers = []
            for container in raw_containers:
                try:
                     # From attrs: container.image is a second request, and a
                     # removed image made this container drop out of the list
                     # through the NotFound handler below (review E53).
                     image_name = image_name_of(container)
                     containers.append({
                         "id": container.short_id,
                         "name": container.name,
                         "status": container.status,
                         "image": image_name
                     })
                except docker.errors.NotFound:
                     logger.warning(f"Could not get full details for a listed container (possibly removed during listing): {container.id}")
                     continue
                except (AttributeError, KeyError, IndexError) as e_inner:
                     logger.warning(f"Error processing container {container.id} in list: {e_inner}")
                     continue
            return sorted(containers, key=lambda x: x.get('name', '').lower())
    except asyncio.TimeoutError:
        logger.error("Timeout listing Docker containers")
        return []
    except (DockerServiceError, docker.errors.DockerException, OSError, RuntimeError) as e:
        logger.error(f"Docker error listing containers: {e}", exc_info=True)
        return []

async def is_container_exists(docker_container_name: str) -> Optional[bool]:
    """True, False, or None when DDC could not ask.

    Three states, and they used to share two return values: a Docker that was
    unreachable answered False, and the caller announced "Container not found"
    about a container that is fine - and skipped the action it was meant to
    take. Unknown is its own answer now, the way _get_running_state already
    keeps it.
    """
    if not docker_container_name:
        return False

    # 🔒 SECURITY: Validate container name format before Docker API call
    from utils.common_helpers import validate_container_name
    if not validate_container_name(docker_container_name):
        logger.error(f"is_container_exists: Invalid container name format: {docker_container_name}")
        return False

    try:
        # 🔧 PERFORMANCE: Use Advanced Settings timeout (DDC_FAST_INFO_TIMEOUT) + container-specific optimization
        async with get_docker_client_async(operation='info', container_name=docker_container_name) as client:
            await asyncio.to_thread(client.containers.get, docker_container_name)
            return True
    except docker.errors.NotFound:
        return False
    except (DockerServiceError, docker.errors.DockerException, OSError, RuntimeError) as e:
        # NOT False: this is "could not ask", and saying "does not exist" here
        # is an answer DDC does not have.
        logger.error(f"Docker error checking existence of '{docker_container_name}': {e}", exc_info=True)
        return None

async def get_containers_data() -> List[Dict[str, Any]]:
    global _containers_cache, _cache_timestamp
    current_time = time.time()

    # Thread-safe cache access
    with _containers_cache_lock:
        if _containers_cache is not None and (current_time - _cache_timestamp < _lazy_value('_CACHE_TTL')):
            logger.debug("Using cached container data")
            return _containers_cache.copy()  # Return copy to avoid modification

    try:
        # 🔧 PERFORMANCE: Use Advanced Settings timeout (DDC_FAST_LIST_TIMEOUT) for container data retrieval
        async with get_docker_client_async(operation='list') as client:
            # Only keywords docker-py actually declares: APIClient.containers has a
            # fixed signature and no **kwargs, so the "Lstat=True" that used to sit
            # here raised TypeError on every single listing (review C56).
            containers_api_list = await asyncio.to_thread(client.api.containers, all=True)
            result = []
            for c_data in containers_api_list:
                try:
                    name = (c_data.get('Names') or ['N/A'])[0].lstrip('/') # Names can be a list
                    status = c_data.get('State', 'unknown').lower()
                    is_running = status == "running"
                    image_name = c_data.get('Image', 'N/A')
                    if '@sha256:' in image_name: # often image name is with digest
                        image_name = image_name.split('@sha256:')[0]

                    container_info = {
                        "id": c_data.get('Id', 'N/A')[:12],
                        "name": name,
                        "status": status,
                        "running": is_running,
                        "image": image_name,
                        "created": datetime.fromtimestamp(c_data.get('Created', 0), timezone.utc).isoformat() if c_data.get('Created') else "N/A",
                    }
                    if is_running:
                        container_info["ports"] = c_data.get("Ports", {})
                        # No start time here. In the low-level listing "State" is a
                        # plain string ("running") - the object with StartedAt only
                        # comes from an inspect call. Calling .get() on that string
                        # raised AttributeError, which the handler below turned into
                        # status "error_processing", running False: every healthy
                        # running container was reported as broken (review C56).
                        # Nothing outside ever read the field.
                    result.append(container_info)
                except (AttributeError, KeyError, ValueError, TypeError) as e_inner:
                    logger.warning(f"Error processing individual container data for {c_data.get('Id', 'unknown_id')}: {e_inner}")
                    result.append({
                        "id": c_data.get('Id', 'unknown_id')[:12],
                        "name": (c_data.get('Names') or ['error'])[0].lstrip('/'),
                        "status": "error_processing",
                        "running": False,
                        "error": str(e_inner)
                    })
            sorted_result = sorted(result, key=lambda x: x.get("name", "").lower())

            # Thread-safe cache update
            with _containers_cache_lock:
                _containers_cache = sorted_result
                _cache_timestamp = current_time

            return sorted_result
    except (DockerServiceError, docker.errors.DockerException, asyncio.TimeoutError, OSError, RuntimeError) as e:
        logger.error(f"Error in get_containers_data: {e}", exc_info=True)
        return []

async def test_docker_performance(container_names: List[str] = None, iterations: int = 1) -> Dict[str, Any]:
    """
    Test Docker API performance for troubleshooting slow containers.

    Args:
        container_names: List of container names to test. If None, tests all containers.
        iterations: Number of test iterations to run for averaging

    Returns:
        Dict with performance metrics and timing data
    """
    if container_names is None:
        # Get all container names
        containers_data = await get_containers_data()
        container_names = [c['name'] for c in containers_data]

    if not container_names:
        logger.warning("No containers found for performance testing")
        return {}

    logger.info(f"Starting Docker performance test for {len(container_names)} containers, {iterations} iterations")

    results = {
        'total_containers': len(container_names),
        'iterations': iterations,
        'container_results': {},
        'summary': {
            'fastest_container': None,
            'slowest_container': None,
            'average_time_ms': 0,
            'total_time_ms': 0,
            'timeout_count': 0
        }
    }

    total_time_sum = 0
    container_times = {}
    timeout_count = 0

    for iteration in range(iterations):
        logger.info(f"Performance test iteration {iteration + 1}/{iterations}")

        for container_name in container_names:
            start_time = time.time()

            # Read once, up front, and hand the value to the error handlers
            # below. They used to call get_container_timeouts() again while
            # handling an error - including an error that came from that very
            # call, because it reads the configuration and can raise. The
            # handler then raised the same error a second time, and it left
            # test_docker_performance altogether: the tool died on the one
            # container it was asked to diagnose and took the report on all the
            # others with it (review C57). None means "we never got that far".
            timeout_config = None

            try:
                # Use container-specific timeout
                timeout_config = get_container_timeouts(container_name)

                # Test both info and stats calls
                info_task = asyncio.create_task(get_docker_info(container_name))
                stats_task = asyncio.create_task(get_docker_stats(container_name))

                total_timeout = timeout_config['info_timeout'] + timeout_config['stats_timeout']

                info, stats = await asyncio.wait_for(
                    asyncio.gather(info_task, stats_task, return_exceptions=True),
                    timeout=total_timeout
                )

                elapsed_time = (time.time() - start_time) * 1000

                # Track results
                if container_name not in container_times:
                    container_times[container_name] = []
                container_times[container_name].append(elapsed_time)

                # Check for errors
                error_info = None
                if isinstance(info, Exception):
                    error_info = f"Info error: {info}"
                elif isinstance(stats, Exception):
                    error_info = f"Stats error: {stats}"
                elif stats == ("N/A", "N/A"):
                    error_info = "Stats timeout"
                    timeout_count += 1
                elif info is None:
                    # An unreachable daemon used to arrive here as an exception
                    # object, captured by `return_exceptions=True` above and
                    # recorded as "Info error: ...". Since E49 get_docker_info
                    # keeps the promise in its signature and answers None
                    # instead - so the report has to read the None, or a
                    # container nobody could reach is listed with a timing and
                    # no errors, which reads as healthy.
                    error_info = "Info error: Docker did not answer"
                elif stats == (None, None):
                    error_info = "Stats error: Docker did not answer"

                if container_name not in results['container_results']:
                    results['container_results'][container_name] = {
                        'times_ms': [],
                        'average_ms': 0,
                        'min_ms': float('inf'),
                        'max_ms': 0,
                        'timeout_config': timeout_config,
                        'errors': []
                    }

                results['container_results'][container_name]['times_ms'].append(elapsed_time)

                if error_info:
                    results['container_results'][container_name]['errors'].append(error_info)

                total_time_sum += elapsed_time

            except asyncio.TimeoutError:
                elapsed_time = (time.time() - start_time) * 1000
                logger.warning(f"Performance test timeout for {container_name}: {elapsed_time:.1f}ms")
                timeout_count += 1

                if container_name not in results['container_results']:
                    results['container_results'][container_name] = {
                        'times_ms': [],
                        'average_ms': 0,
                        'min_ms': float('inf'),
                        'max_ms': 0,
                        'timeout_config': timeout_config,
                        'errors': []
                    }

                results['container_results'][container_name]['times_ms'].append(elapsed_time)
                results['container_results'][container_name]['errors'].append("Overall timeout")

            except (docker.errors.DockerException, RuntimeError) as e:
                elapsed_time = (time.time() - start_time) * 1000
                logger.error(f"Performance test error for {container_name}: {e}", exc_info=True)

                if container_name not in results['container_results']:
                    results['container_results'][container_name] = {
                        'times_ms': [],
                        'average_ms': 0,
                        'min_ms': float('inf'),
                        'max_ms': 0,
                        'timeout_config': timeout_config,
                        'errors': []
                    }

                results['container_results'][container_name]['errors'].append(f"Exception: {e}")

    # Calculate averages and summary
    for container_name, container_result in results['container_results'].items():
        times = container_result['times_ms']
        if times:
            container_result['average_ms'] = sum(times) / len(times)
            container_result['min_ms'] = min(times)
            container_result['max_ms'] = max(times)

    # Summary statistics
    all_averages = [cr['average_ms'] for cr in results['container_results'].values() if cr['times_ms']]
    if all_averages:
        results['summary']['average_time_ms'] = sum(all_averages) / len(all_averages)
        results['summary']['total_time_ms'] = total_time_sum
        results['summary']['timeout_count'] = timeout_count

        # Find fastest and slowest containers, among those that were actually
        # measured. A container whose calls failed on every iteration keeps
        # times_ms empty and average_ms at its initial 0 - and min() over all of
        # them then presented exactly that broken container to the operator as
        # the fastest one, at 0 ms (review C58). Its errors list still says what
        # happened to it. The list is not empty here: all_averages above is
        # built from the same condition.
        measured = [item for item in results['container_results'].items()
                    if item[1]['times_ms']]
        fastest_container = min(measured, key=lambda x: x[1]['average_ms'])
        slowest_container = max(measured, key=lambda x: x[1]['average_ms'])

        results['summary']['fastest_container'] = {
            'name': fastest_container[0],
            'average_ms': fastest_container[1]['average_ms']
        }
        results['summary']['slowest_container'] = {
            'name': slowest_container[0],
            'average_ms': slowest_container[1]['average_ms']
        }

    logger.info(f"Performance test completed. Average time: {results['summary']['average_time_ms']:.1f}ms, "
                f"Timeouts: {timeout_count}, Fastest: {results['summary']['fastest_container']}, "
                f"Slowest: {results['summary']['slowest_container']}")

    return results

async def compare_container_performance(container_names: List[str] = None) -> str:
    """
    Simple comparison of Docker stats performance between containers.
    Shows the user why some containers are slower.

    Args:
        container_names: list of containers to compare

    Returns:
        Formatted string with the comparison results
    """
    if not container_names:
        # Find running containers automatically
        containers_data = await get_containers_data()
        container_names = [c['name'] for c in containers_data if c.get('running', False)][:5]  # at most 5 containers

    if not container_names:
        return "❌ No running containers found to test."

    logger.info(f"Comparing performance of {len(container_names)} containers")
    results = []

    for container_name in container_names:
        logger.info(f"Testing container: {container_name}")

        # 🔒 SECURITY: Validate container name format before Docker API call
        from utils.common_helpers import validate_container_name
        if not validate_container_name(container_name):
            logger.error(f"compare_container_performance: Invalid container name format: {container_name}")
            continue

        # Simple performance test (3 iterations)
        times = []
        try:
            # 🔧 PERFORMANCE: Use Advanced Settings timeout for performance comparison
            async with get_docker_client_async(operation='stats', container_name=container_name) as client:
                container = await asyncio.to_thread(client.containers.get, container_name)

                # 3 quick tests
                for i in range(3):
                    start_time = time.time()
                    try:
                        stats = await asyncio.wait_for(
                            asyncio.to_thread(container.stats, stream=False),
                            timeout=10.0  # 10s max
                        )
                        elapsed = (time.time() - start_time) * 1000
                        times.append(elapsed)

                        # Short pause
                        if i < 2:
                            await asyncio.sleep(0.2)

                    except asyncio.TimeoutError:
                        times.append(10000)  # 10s Timeout
                    except (docker.errors.DockerException, RuntimeError, OSError) as e:
                        logger.warning(f"Error with {container_name}: {e}", exc_info=True)
                        continue

                if times:
                    avg_time = sum(times) / len(times)
                    min_time = min(times)
                    max_time = max(times)

                    # Determine the container type
                    container_type_info = get_container_type_info(container_name)
                    container_type = container_type_info.get('type', 'unknown')
                    matched_pattern = container_type_info.get('matched_pattern', 'none')

                    # Performance category
                    if avg_time > 2000:
                        category = "🔴 VERY SLOW"
                    elif avg_time > 1000:
                        category = "🟡 SLOW"
                    elif avg_time > 500:
                        category = "🟠 MEDIUM"
                    else:
                        category = "🟢 FAST"

                    results.append({
                        'name': container_name,
                        'avg_time': avg_time,
                        'min_time': min_time,
                        'max_time': max_time,
                        'category': category,
                        'type': container_type,
                        'pattern': matched_pattern
                    })

        except (DockerServiceError, docker.errors.DockerException, asyncio.TimeoutError, RuntimeError, OSError) as e:
            logger.error(f"Error testing {container_name}: {e}", exc_info=True)
            results.append({
                'name': container_name,
                'avg_time': -1,
                'category': "❌ ERROR",
                'error': str(e)
            })

    # Sort the results (slowest first)
    results.sort(key=lambda x: x.get('avg_time', 0), reverse=True)

    # Build the formatted output
    output_lines = [
        "🔍 **DOCKER STATS PERFORMANCE COMPARISON**",
        "=" * 50,
        ""
    ]

    for i, result in enumerate(results):
        if result.get('avg_time', -1) >= 0:
            output_lines.extend([
                f"**{i+1}. {result['name']}** {result['category']}",
                f"   ⏱️  Average: {result['avg_time']:.0f}ms",
                f"   📊 Range: {result['min_time']:.0f}ms - {result['max_time']:.0f}ms",
                f"   🏷️  Type: {result.get('type', 'unknown')} (pattern: {result.get('pattern', 'none')})",
                ""
            ])
        else:
            output_lines.extend([
                f"**{i+1}. {result['name']}** {result['category']}",
                f"   ❌ Error: {result.get('error', 'Unknown')}",
                ""
            ])

    # Add analysis
    valid_results = [r for r in results if r.get('avg_time', -1) >= 0]
    if len(valid_results) >= 2:
        fastest = min(valid_results, key=lambda x: x['avg_time'])
        slowest = max(valid_results, key=lambda x: x['avg_time'])
        speed_difference = slowest['avg_time'] / fastest['avg_time']

        output_lines.extend([
            "📈 **ANALYSIS:**",
            f"   🏃 Fastest: {fastest['name']} ({fastest['avg_time']:.0f}ms)",
            f"   🐌 Slowest: {slowest['name']} ({slowest['avg_time']:.0f}ms)",
            f"   ⚡ Difference: {speed_difference:.1f}x slower!",
            "",
            "💡 **WHY IS THAT?**",
            "   Game servers (Satisfactory, Valheim, etc.) have:",
            "   • High CPU load → cgroups reading takes longer",
            "   • High memory allocation → memory stats take time",
            "   • Intensive disk I/O → block device stats are slow",
            "   • Many network connections → network stats take longer",
            "",
            "   Simple containers (nginx, databases) have:",
            "   • Stable, low resource usage",
            "   • Predictable I/O patterns",
            "   • Fewer active processes",
            ""
        ])

    output_lines.extend([
        "🔧 **SOLUTION APPROACH:**",
        "   ✅ Pattern-based timeouts (now implemented)",
        "   ✅ Game servers: 2s timeout (abort quickly)",
        "   ✅ Standard containers: 3s timeout (more time)",
        "   ✅ True parallelization (no longer sequential)",
        ""
    ])

    return "\n".join(output_lines)
