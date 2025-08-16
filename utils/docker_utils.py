# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List
import docker
import docker.client
from utils.logging_utils import setup_logger
import time
import os
import json
import threading

# Logger for Docker utils
logger = setup_logger('ddc.docker_utils', level=logging.INFO)

# Docker client pool for improved performance
_docker_client = None
_client_last_used = 0
_CLIENT_TIMEOUT = 300  # Erhöht von 60 auf 300 Sekunden (5 Minuten)
_client_ping_cache = 0  # Cache für Ping-Ergebnisse
_PING_CACHE_TTL = 120   # Ping-Cache für 2 Minuten
_docker_client_lock = threading.Lock()  # Thread safety for Docker client

# PERFORMANCE OPTIMIZATION: Flexible container timeout configuration
# Environment variables for timeout configuration (can be overridden)
DEFAULT_FAST_STATS_TIMEOUT = float(os.environ.get('DDC_FAST_STATS_TIMEOUT', '1.5'))  # Reduced from 2.0s
DEFAULT_SLOW_STATS_TIMEOUT = float(os.environ.get('DDC_SLOW_STATS_TIMEOUT', '3.0'))
DEFAULT_FAST_INFO_TIMEOUT = float(os.environ.get('DDC_FAST_INFO_TIMEOUT', '2.0'))
DEFAULT_SLOW_INFO_TIMEOUT = float(os.environ.get('DDC_SLOW_INFO_TIMEOUT', '3.0'))
DEFAULT_CONTAINER_LIST_TIMEOUT = float(os.environ.get('DDC_CONTAINER_LIST_TIMEOUT', '15.0'))

# Pattern-based timeout configuration (flexible and maintainable)
CONTAINER_TYPE_PATTERNS = {
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
        'stats_timeout': DEFAULT_FAST_STATS_TIMEOUT,
        'info_timeout': DEFAULT_SLOW_INFO_TIMEOUT
    },
    'media_server': {
        'patterns': [
            'plex', 'jellyfin', 'emby', 'kodi', 'sonarr', 'radarr', 'lidarr',
            'bazarr', 'prowlarr', 'jackett', 'transmission', 'qbittorrent',
            'deluge', 'rtorrent', 'sabnzbd', 'nzbget', 'overseerr', 'ombi',
            'tautulli', 'organizr', 'heimdall', 'muximux'
        ],
        'stats_timeout': DEFAULT_SLOW_STATS_TIMEOUT,
        'info_timeout': DEFAULT_FAST_INFO_TIMEOUT
    },
    'database': {
        'patterns': [
            'mysql', 'mariadb', 'postgres', 'postgresql', 'mongodb', 'redis',
            'elasticsearch', 'influxdb', 'grafana', 'prometheus', 'clickhouse',
            'cassandra', 'couchdb', 'neo4j', 'memcached', 'sqlite'
        ],
        'stats_timeout': DEFAULT_SLOW_STATS_TIMEOUT,
        'info_timeout': DEFAULT_FAST_INFO_TIMEOUT
    },
    'web_server': {
        'patterns': [
            'nginx', 'apache', 'httpd', 'caddy', 'traefik', 'haproxy',
            'nodejs', 'node', 'php', 'python', 'django', 'flask',
            'wordpress', 'nextcloud', 'owncloud', 'photoprism', 'bitwarden'
        ],
        'stats_timeout': DEFAULT_SLOW_STATS_TIMEOUT,
        'info_timeout': DEFAULT_FAST_INFO_TIMEOUT
    }
}

# Default timeout configuration
DEFAULT_TIMEOUT_CONFIG = {
    'stats_timeout': DEFAULT_SLOW_STATS_TIMEOUT,
    'info_timeout': DEFAULT_FAST_INFO_TIMEOUT
}

# Load custom timeout configuration from file
_custom_timeout_config = None
_custom_config_loaded = False

def load_custom_timeout_config():
    """Load custom timeout configuration from JSON file."""
    global _custom_timeout_config, _custom_config_loaded
    
    if _custom_config_loaded:
        return _custom_timeout_config
    
    _custom_config_loaded = True
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'container_timeouts.json')
    
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                _custom_timeout_config = json.load(f)
                logger.info(f"Loaded custom container timeout configuration from {config_path}")
                return _custom_timeout_config
        else:
            logger.debug(f"Custom timeout config file not found at {config_path}")
    except Exception as e:
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
        return DEFAULT_TIMEOUT_CONFIG.copy()
    
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
                'stats_timeout': override_config.get('stats_timeout', DEFAULT_TIMEOUT_CONFIG['stats_timeout']),
                'info_timeout': override_config.get('info_timeout', DEFAULT_TIMEOUT_CONFIG['info_timeout'])
            }
    
    # 2. Check custom patterns (medium priority)
    if custom_config and 'custom_patterns' in custom_config:
        for pattern_name, pattern_config in custom_config['custom_patterns'].items():
            if 'patterns' in pattern_config:
                for pattern in pattern_config['patterns']:
                    if pattern in container_lower:
                        logger.debug(f"Container '{container_name}' matches custom pattern '{pattern}' from {pattern_name}")
                        return {
                            'stats_timeout': pattern_config.get('stats_timeout', DEFAULT_TIMEOUT_CONFIG['stats_timeout']),
                            'info_timeout': pattern_config.get('info_timeout', DEFAULT_TIMEOUT_CONFIG['info_timeout'])
                        }
    
    # 3. Check built-in container type patterns (lowest priority)
    for container_type, config in CONTAINER_TYPE_PATTERNS.items():
        for pattern in config['patterns']:
            if pattern in container_lower:
                logger.debug(f"Container '{container_name}' matches built-in {container_type} pattern '{pattern}'")
                return {
                    'stats_timeout': config['stats_timeout'],
                    'info_timeout': config['info_timeout']
                }
    
    # Return default if no pattern matches
    logger.debug(f"Container '{container_name}' using default timeout configuration")
    return DEFAULT_TIMEOUT_CONFIG.copy()

def get_container_type_info(container_name: str) -> dict:
    """
    Get container type information for debugging and monitoring.
    
    Args:
        container_name: Name of the Docker container
        
    Returns:
        Dict with container type information including custom configuration
    """
    if not container_name:
        return {'type': 'unknown', 'matched_pattern': None, 'timeout_config': DEFAULT_TIMEOUT_CONFIG, 'config_source': 'default'}
    
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
                    'stats_timeout': override_config.get('stats_timeout', DEFAULT_TIMEOUT_CONFIG['stats_timeout']),
                    'info_timeout': override_config.get('info_timeout', DEFAULT_TIMEOUT_CONFIG['info_timeout'])
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
                                'stats_timeout': pattern_config.get('stats_timeout', DEFAULT_TIMEOUT_CONFIG['stats_timeout']),
                                'info_timeout': pattern_config.get('info_timeout', DEFAULT_TIMEOUT_CONFIG['info_timeout'])
                            },
                            'config_source': 'custom_pattern'
                        }
    
    # Check built-in container type patterns
    for container_type, config in CONTAINER_TYPE_PATTERNS.items():
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
        'timeout_config': DEFAULT_TIMEOUT_CONFIG,
        'config_source': 'default'
    }

def get_docker_client():
    """
    Get Docker client with immediate fallback and connection caching.
    Returns None if all methods fail.
    """
    global _docker_client, _client_last_used
    
    current_time = time.time()
    
    # Return cached client if still valid
    if (_docker_client is not None and 
        current_time - _client_last_used < _CLIENT_TIMEOUT):
        _client_last_used = current_time
        return _docker_client
    
    # Create new client with immediate fallback
    logger.info("Creating Docker client with immediate fallback system...")
    
    try:
        # Method 1: Standard socket (non-blocking)
        logger.info("Trying docker.from_env() for immediate connection...")
        _docker_client = docker.from_env(timeout=int(DEFAULT_CONTAINER_LIST_TIMEOUT))
        
        # Quick ping test
        _docker_client.ping()
        logger.info("✅ Docker client created successfully with docker.from_env()")
        
        _client_last_used = current_time
        return _docker_client

    except Exception as e1:
        logger.warning(f"docker.from_env() failed: {e1}")
        
        try:
            # Method 2: Direct socket path
            logger.info("Trying direct socket path...")
            _docker_client = docker.DockerClient(base_url='unix:///var/run/docker.sock', timeout=int(DEFAULT_CONTAINER_LIST_TIMEOUT))
            
            # Quick ping test
            _docker_client.ping()
            logger.info("✅ Docker client created successfully with direct socket")
            
            _client_last_used = current_time
            return _docker_client
            
        except Exception as e2:
            logger.error(f"All Docker client methods failed: docker.from_env()={e1}, direct_socket={e2}")
            _docker_client = None
            return None

def release_docker_client():
    """Closes the current Docker client if idle for too long."""
    global _docker_client, _client_last_used
    
    if _docker_client is not None and (time.time() - _client_last_used > _CLIENT_TIMEOUT):
        try:
            _docker_client.close()
            logger.info("Released Docker client due to inactivity.")
            _docker_client = None
        except Exception as e:
            logger.debug(f"Error during client release: {e}")

class DockerError(Exception):
    """Custom exception class for Docker-related errors."""
    pass

async def get_docker_stats(docker_container_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Gets CPU and memory usage for a Docker container using the SDK.
    Now allows longer execution for accurate data collection.

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
        client = get_docker_client()
        if not client:
            logger.warning(f"get_docker_stats: Could not get Docker client for {docker_container_name}.")
            return None, None
        
        start_time = time.time()
        
        try:
            container = await asyncio.to_thread(client.containers.get, docker_container_name)
            # Let Docker stats run naturally - no artificial timeout
            # Cache update can take time, UI will use last known data
            stats = await asyncio.to_thread(container.stats, stream=False)
            
            elapsed_time = (time.time() - start_time) * 1000
            if elapsed_time > 5000:  # Over 5 seconds - informational only
                logger.info(f"Long stats call for {docker_container_name}: {elapsed_time:.1f}ms (but got real data)")
            elif elapsed_time > 2000:  # Over 2 seconds
                logger.debug(f"Slow stats call for {docker_container_name}: {elapsed_time:.1f}ms")
            
        except Exception as e:
            logger.warning(f"Error getting stats for {docker_container_name}: {e}")
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
    except Exception as e:
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
        client = get_docker_client()
        if not client:
            logger.warning(f"get_docker_info: Could not get Docker client for {docker_container_name}.")
            return None
        container = await asyncio.to_thread(client.containers.get, docker_container_name)
        return container.attrs
    except docker.errors.NotFound:
        logger.warning(f"Container '{docker_container_name}' not found.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_docker_info for '{docker_container_name}': {e}", exc_info=True)
        return None

async def docker_action(docker_container_name: str, action: str) -> bool:
    valid_actions = {
        'start': lambda c: c.start(),
        'stop': lambda c: c.stop(),
        'restart': lambda c: c.restart(),
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
        client = get_docker_client()
        if not client:
            logger.warning(f"docker_action: Could not get Docker client for {docker_container_name}.")
            return False
        container = await asyncio.to_thread(client.containers.get, docker_container_name)
        action_func = valid_actions[action]
        await asyncio.to_thread(action_func, container)
        logger.info(f"Docker action '{action}' on container '{docker_container_name}' successful via SDK")
        return True
    except docker.errors.NotFound:
        logger.warning(f"Container '{docker_container_name}' not found for action '{action}'.")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during docker action '{action}' on '{docker_container_name}': {e}", exc_info=True)
        return False

_containers_cache = None
_cache_timestamp = 0
_CACHE_TTL = 10  # seconds
_containers_cache_lock = threading.Lock()  # Thread safety for container cache

async def list_docker_containers() -> List[Dict[str, Any]]:
    try:
        client = get_docker_client()
        if not client:
            logger.warning("list_docker_containers: Could not get Docker client.")
            return []
        raw_containers = await asyncio.to_thread(client.containers.list, all=True)
        containers = []
        for container in raw_containers:
            try:
                 image_tags = container.image.tags
                 image_name = image_tags[0] if image_tags else container.image.id[:12]
                 containers.append({
                     "id": container.short_id,
                     "name": container.name,
                     "status": container.status,
                     "image": image_name
                 })
            except docker.errors.NotFound:
                 logger.warning(f"Could not get full details for a listed container (possibly removed during listing): {container.id}")
                 continue
            except Exception as e_inner:
                 logger.warning(f"Error processing container {container.id} in list: {e_inner}")
                 continue
        return sorted(containers, key=lambda x: x.get('name', '').lower())
    except Exception as e:
        logger.error(f"Unexpected error listing Docker containers: {e}", exc_info=True)
        return []

async def is_container_exists(docker_container_name: str) -> bool:
    if not docker_container_name:
        return False
    
    # 🔒 SECURITY: Validate container name format before Docker API call
    from utils.common_helpers import validate_container_name
    if not validate_container_name(docker_container_name):
        logger.error(f"is_container_exists: Invalid container name format: {docker_container_name}")
        return False
        
    try:
        client = get_docker_client()
        if not client:
            logger.warning(f"is_container_exists: Could not get Docker client for {docker_container_name}.")
            return False
        await asyncio.to_thread(client.containers.get, docker_container_name)
        return True
    except docker.errors.NotFound:
        return False
    except Exception as e:
        logger.error(f"Docker error checking existence of '{docker_container_name}': {e}", exc_info=True)
        return False

async def get_containers_data() -> List[Dict[str, Any]]:
    global _containers_cache, _cache_timestamp
    current_time = time.time()
    
    # Thread-safe cache access
    with _containers_cache_lock:
        if _containers_cache is not None and (current_time - _cache_timestamp < _CACHE_TTL):
            logger.debug("Using cached container data")
            return _containers_cache.copy()  # Return copy to avoid modification
    
    try:
        client = get_docker_client()
        if not client:
            logger.warning("get_containers_data: Could not get Docker client.")
            return []
        
        containers_api_list = await asyncio.to_thread(client.api.containers, all=True, Lstat=True) # Use low-level API for more resilience
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
                    ports_info = c_data.get("Ports", {})
                    container_info["ports"] = ports_info
                    state_detail = c_data.get("State", {})
                    if state_detail:
                        container_info["started_at"] = state_detail.get("StartedAt", "")
                        # Health status is not directly in low-level API list, would need inspect
                        # container_info["health"] = "unknown" 
                result.append(container_info)
            except Exception as e_inner:
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
    except Exception as e:
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
            
            try:
                # Test both info and stats calls
                info_task = asyncio.create_task(get_docker_info(container_name))
                stats_task = asyncio.create_task(get_docker_stats(container_name))
                
                # Use container-specific timeout
                timeout_config = get_container_timeouts(container_name)
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
                        'timeout_config': get_container_timeouts(container_name),
                        'errors': []
                    }
                
                results['container_results'][container_name]['times_ms'].append(elapsed_time)
                results['container_results'][container_name]['errors'].append("Overall timeout")
                
            except Exception as e:
                elapsed_time = (time.time() - start_time) * 1000
                logger.error(f"Performance test error for {container_name}: {e}")
                
                if container_name not in results['container_results']:
                    results['container_results'][container_name] = {
                        'times_ms': [],
                        'average_ms': 0,
                        'min_ms': float('inf'),
                        'max_ms': 0,
                        'timeout_config': get_container_timeouts(container_name),
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
        
        # Find fastest and slowest containers
        fastest_container = min(results['container_results'].items(), key=lambda x: x[1]['average_ms'])
        slowest_container = max(results['container_results'].items(), key=lambda x: x[1]['average_ms'])
        
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

async def analyze_docker_stats_performance(container_name: str, iterations: int = 5) -> dict:
    """
    Detaillierte Analyse warum ein Container langsame Docker Stats hat.
    
    Args:
        container_name: Name des Docker-Containers
        iterations: Anzahl der Test-Iterationen
        
    Returns:
        Dict mit detaillierten Performance-Metriken
    """
    if not container_name:
        return {}
    
    # 🔒 SECURITY: Validate container name format before Docker API call
    from utils.common_helpers import validate_container_name
    if not validate_container_name(container_name):
        logger.error(f"analyze_docker_stats_performance: Invalid container name format: {container_name}")
        return {}
    
    logger.info(f"Analysiere Docker Stats Performance für Container '{container_name}'")
    
    results = {
        'container_name': container_name,
        'iterations': iterations,
        'timing_breakdown': {
            'get_container_times': [],
            'stats_call_times': [],
            'total_times': []
        },
        'container_metrics': {
            'cpu_usage_trend': [],
            'memory_usage_trend': [],
            'io_stats': [],
            'network_stats': []
        },
        'system_info': {},
        'analysis': {}
    }
    
    try:
        client = get_docker_client()
        if not client:
            logger.warning(f"Konnte Docker Client für Analyse nicht erhalten: {container_name}")
            return results
        
        # Container-Objekt einmal holen für Analyse
        container = await asyncio.to_thread(client.containers.get, container_name)
        container_info = container.attrs
        
        # System-Informationen sammeln
        results['system_info'] = {
            'container_state': container_info.get('State', {}).get('Status', 'unknown'),
            'container_created': container_info.get('Created', 'unknown'),
            'restart_count': container_info.get('RestartCount', 0),
            'platform': container_info.get('Platform', 'unknown'),
            'driver': container_info.get('Driver', 'unknown')
        }
        
        # Host-Informationen hinzufügen
        try:
            host_info = await asyncio.to_thread(client.info)
            results['system_info'].update({
                'docker_version': host_info.get('ServerVersion', 'unknown'),
                'total_containers': host_info.get('Containers', 0),
                'running_containers': host_info.get('ContainersRunning', 0),
                'system_memory': host_info.get('MemTotal', 0),
                'storage_driver': host_info.get('StorageDriver', 'unknown')
            })
        except Exception as e:
            logger.warning(f"Konnte Host-Info nicht abrufen: {e}")
        
        for iteration in range(iterations):
            logger.info(f"Performance-Analyse Iteration {iteration + 1}/{iterations} für '{container_name}'")
            
            # 1. Container-Objekt abrufen (sollte schnell sein, da gecacht)
            start_time = time.time()
            try:
                # Note: container name already validated above, safe to use
                container = await asyncio.to_thread(client.containers.get, container_name)
                get_container_time = (time.time() - start_time) * 1000
                results['timing_breakdown']['get_container_times'].append(get_container_time)
            except Exception as e:
                logger.error(f"Fehler beim Container-Abruf: {e}")
                continue
            
            # 2. Stats-Call (hier wird es interessant)
            stats_start_time = time.time()
            try:
                stats = await asyncio.to_thread(container.stats, stream=False)
                stats_call_time = (time.time() - stats_start_time) * 1000
                results['timing_breakdown']['stats_call_times'].append(stats_call_time)
                
                total_time = (time.time() - start_time) * 1000
                results['timing_breakdown']['total_times'].append(total_time)
                
                # 3. Stats-Daten analysieren für Trends
                if stats:
                    # CPU-Metriken
                    cpu_stats = stats.get('cpu_stats', {})
                    if cpu_stats:
                        cpu_usage = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                        system_cpu = cpu_stats.get('system_cpu_usage', 0)
                        results['container_metrics']['cpu_usage_trend'].append({
                            'iteration': iteration,
                            'cpu_usage': cpu_usage,
                            'system_cpu': system_cpu,
                            'online_cpus': cpu_stats.get('online_cpus', 1)
                        })
                    
                    # Memory-Metriken
                    memory_stats = stats.get('memory_stats', {})
                    if memory_stats:
                        memory_usage = memory_stats.get('usage', 0)
                        memory_limit = memory_stats.get('limit', 0)
                        memory_cache = memory_stats.get('stats', {}).get('cache', 0)
                        results['container_metrics']['memory_usage_trend'].append({
                            'iteration': iteration,
                            'memory_usage': memory_usage,
                            'memory_limit': memory_limit,
                            'memory_cache': memory_cache,
                            'memory_percent': (memory_usage / memory_limit * 100) if memory_limit > 0 else 0
                        })
                    
                    # I/O-Metriken
                    blkio_stats = stats.get('blkio_stats', {})
                    if blkio_stats:
                        io_service_bytes = blkio_stats.get('io_service_bytes_recursive', [])
                        total_read = sum(entry.get('value', 0) for entry in io_service_bytes if entry.get('op') == 'Read')
                        total_write = sum(entry.get('value', 0) for entry in io_service_bytes if entry.get('op') == 'Write')
                        results['container_metrics']['io_stats'].append({
                            'iteration': iteration,
                            'total_read_bytes': total_read,
                            'total_write_bytes': total_write,
                            'stats_call_time_ms': stats_call_time
                        })
                    
                    # Network-Metriken
                    networks = stats.get('networks', {})
                    if networks:
                        total_rx_bytes = sum(net.get('rx_bytes', 0) for net in networks.values())
                        total_tx_bytes = sum(net.get('tx_bytes', 0) for net in networks.values())
                        total_rx_packets = sum(net.get('rx_packets', 0) for net in networks.values())
                        total_tx_packets = sum(net.get('tx_packets', 0) for net in networks.values())
                        results['container_metrics']['network_stats'].append({
                            'iteration': iteration,
                            'total_rx_bytes': total_rx_bytes,
                            'total_tx_bytes': total_tx_bytes,
                            'total_rx_packets': total_rx_packets,
                            'total_tx_packets': total_tx_packets,
                            'stats_call_time_ms': stats_call_time
                        })
                
                # Log für langsame Calls
                if stats_call_time > 1000:
                    logger.warning(f"LANGSAMER Stats-Call für '{container_name}': {stats_call_time:.1f}ms")
                elif stats_call_time > 500:
                    logger.info(f"Mittellangsamer Stats-Call für '{container_name}': {stats_call_time:.1f}ms")
                
            except Exception as e:
                logger.error(f"Fehler beim Stats-Abruf (Iteration {iteration}): {e}")
                continue
            
            # Kurze Pause zwischen Iterationen
            if iteration < iterations - 1:
                await asyncio.sleep(0.5)
        
        # Analyse der Ergebnisse
        if results['timing_breakdown']['stats_call_times']:
            stats_times = results['timing_breakdown']['stats_call_times']
            avg_stats_time = sum(stats_times) / len(stats_times)
            max_stats_time = max(stats_times)
            min_stats_time = min(stats_times)
            
            # Variabilität berechnen
            variance = sum((t - avg_stats_time) ** 2 for t in stats_times) / len(stats_times)
            std_deviation = variance ** 0.5
            
            results['analysis'] = {
                'avg_stats_time_ms': avg_stats_time,
                'max_stats_time_ms': max_stats_time,
                'min_stats_time_ms': min_stats_time,
                'std_deviation_ms': std_deviation,
                'variability_high': std_deviation > (avg_stats_time * 0.3),  # >30% Variabilität
                'consistently_slow': avg_stats_time > 1000,  # Durchschnitt >1s
                'performance_category': 'langsam' if avg_stats_time > 1000 else 'mittel' if avg_stats_time > 500 else 'schnell'
            }
            
            # Korrelations-Analyse (falls genug Daten)
            if len(results['container_metrics']['memory_usage_trend']) >= 3:
                memory_usage = [m['memory_percent'] for m in results['container_metrics']['memory_usage_trend']]
                # Einfache Korrelation zwischen Memory-Nutzung und Stats-Zeit
                if len(memory_usage) == len(stats_times):
                    avg_memory = sum(memory_usage) / len(memory_usage)
                    memory_high = avg_memory > 70  # >70% Memory-Nutzung
                    results['analysis']['memory_correlation'] = {
                        'avg_memory_percent': avg_memory,
                        'high_memory_usage': memory_high,
                        'likely_memory_impact': memory_high and avg_stats_time > 1000
                    }
            
            # Empfehlungen basierend auf Analyse
            recommendations = []
            if results['analysis']['consistently_slow']:
                recommendations.append("Container ist konsistent langsam - erwägen Sie niedrigere Timeouts")
            if results['analysis']['variability_high']:
                recommendations.append("Hohe Variabilität - Container-Last schwankt stark")
            if results['analysis'].get('memory_correlation', {}).get('likely_memory_impact', False):
                recommendations.append("Hohe Memory-Nutzung könnte Stats-Performance beeinträchtigen")
            if avg_stats_time > 2000:
                recommendations.append("Sehr langsam - prüfen Sie Container-Gesundheit und Host-Performance")
            
            results['analysis']['recommendations'] = recommendations
        
        logger.info(f"Performance-Analyse abgeschlossen für '{container_name}': "
                   f"Durchschnitt {results['analysis'].get('avg_stats_time_ms', 0):.1f}ms, "
                   f"Kategorie: {results['analysis'].get('performance_category', 'unbekannt')}")
        
    except Exception as e:
        logger.error(f"Fehler bei Performance-Analyse für '{container_name}': {e}", exc_info=True)
        results['error'] = str(e)
    
    return results

async def compare_container_performance(container_names: List[str] = None) -> str:
    """
    Einfacher Vergleich der Docker Stats Performance zwischen Containern.
    Zeigt dem User, warum manche Container langsamer sind.
    
    Args:
        container_names: Liste der Container zum Vergleichen
        
    Returns:
        Formatierter String mit Vergleichsergebnissen
    """
    if not container_names:
        # Automatisch laufende Container finden
        containers_data = await get_containers_data()
        container_names = [c['name'] for c in containers_data if c.get('running', False)][:5]  # Max 5 Container
    
    if not container_names:
        return "❌ Keine laufenden Container gefunden zum Testen."
    
    logger.info(f"Vergleiche Performance von {len(container_names)} Containern")
    results = []
    
    for container_name in container_names:
        logger.info(f"Teste Container: {container_name}")
        
        # 🔒 SECURITY: Validate container name format before Docker API call
        from utils.common_helpers import validate_container_name
        if not validate_container_name(container_name):
            logger.error(f"compare_container_performance: Invalid container name format: {container_name}")
            continue
        
        # Einfacher Performance-Test (3 Iterationen)
        times = []
        try:
            client = get_docker_client()
            if not client:
                continue
                
            container = await asyncio.to_thread(client.containers.get, container_name)
            
            # 3 schnelle Tests
            for i in range(3):
                start_time = time.time()
                try:
                    stats = await asyncio.wait_for(
                        asyncio.to_thread(container.stats, stream=False),
                        timeout=10.0  # 10s max
                    )
                    elapsed = (time.time() - start_time) * 1000
                    times.append(elapsed)
                    
                    # Kurze Pause
                    if i < 2:
                        await asyncio.sleep(0.2)
                        
                except asyncio.TimeoutError:
                    times.append(10000)  # 10s Timeout
                except Exception as e:
                    logger.warning(f"Fehler bei {container_name}: {e}")
                    continue
            
            if times:
                avg_time = sum(times) / len(times)
                min_time = min(times)
                max_time = max(times)
                
                # Container-Typ ermitteln
                container_type_info = get_container_type_info(container_name)
                container_type = container_type_info.get('type', 'unknown')
                matched_pattern = container_type_info.get('matched_pattern', 'none')
                
                # Performance-Kategorie
                if avg_time > 2000:
                    category = "🔴 SEHR LANGSAM"
                elif avg_time > 1000:
                    category = "🟡 LANGSAM"
                elif avg_time > 500:
                    category = "🟠 MITTEL"
                else:
                    category = "🟢 SCHNELL"
                
                results.append({
                    'name': container_name,
                    'avg_time': avg_time,
                    'min_time': min_time,
                    'max_time': max_time,
                    'category': category,
                    'type': container_type,
                    'pattern': matched_pattern
                })
        
        except Exception as e:
            logger.error(f"Fehler beim Test von {container_name}: {e}")
            results.append({
                'name': container_name,
                'avg_time': -1,
                'category': "❌ FEHLER",
                'error': str(e)
            })
    
    # Ergebnisse sortieren (langsamste zuerst)
    results.sort(key=lambda x: x.get('avg_time', 0), reverse=True)
    
    # Formatierte Ausgabe erstellen
    output_lines = [
        "🔍 **DOCKER STATS PERFORMANCE VERGLEICH**",
        "=" * 50,
        ""
    ]
    
    for i, result in enumerate(results):
        if result.get('avg_time', -1) >= 0:
            output_lines.extend([
                f"**{i+1}. {result['name']}** {result['category']}",
                f"   ⏱️  Durchschnitt: {result['avg_time']:.0f}ms",
                f"   📊 Bereich: {result['min_time']:.0f}ms - {result['max_time']:.0f}ms",
                f"   🏷️  Typ: {result.get('type', 'unknown')} (Pattern: {result.get('pattern', 'none')})",
                ""
            ])
        else:
            output_lines.extend([
                f"**{i+1}. {result['name']}** {result['category']}",
                f"   ❌ Fehler: {result.get('error', 'Unbekannt')}",
                ""
            ])
    
    # Analyse hinzufügen
    valid_results = [r for r in results if r.get('avg_time', -1) >= 0]
    if len(valid_results) >= 2:
        fastest = min(valid_results, key=lambda x: x['avg_time'])
        slowest = max(valid_results, key=lambda x: x['avg_time'])
        speed_difference = slowest['avg_time'] / fastest['avg_time']
        
        output_lines.extend([
            "📈 **ANALYSE:**",
            f"   🏃 Schnellster: {fastest['name']} ({fastest['avg_time']:.0f}ms)",
            f"   🐌 Langsamster: {slowest['name']} ({slowest['avg_time']:.0f}ms)",
            f"   ⚡ Unterschied: {speed_difference:.1f}x langsamer!",
            "",
            "💡 **WARUM IST DAS SO?**",
            "   Game-Server (Satisfactory, Valheim, etc.) haben:",
            "   • Hohe CPU-Last → cgroups-Auslesen dauert länger",
            "   • Viel Memory-Allokation → Memory-Stats brauchen Zeit", 
            "   • Intensive Disk-I/O → Block-Device-Stats sind langsam",
            "   • Viele Netzwerk-Connections → Network-Stats dauern länger",
            "",
            "   Einfache Container (nginx, databases) haben:",
            "   • Stabile, niedrige Ressourcennutzung",
            "   • Vorhersagbare I/O-Patterns",
            "   • Weniger aktive Prozesse",
            ""
        ])
    
    output_lines.extend([
        "🔧 **LÖSUNGSANSATZ:**",
        "   ✅ Pattern-basierte Timeouts (jetzt implementiert)",
        "   ✅ Game-Server: 2s Timeout (schnell abbrechen)",
        "   ✅ Standard-Container: 3s Timeout (mehr Zeit)",
        "   ✅ Echte Parallelisierung (nicht mehr sequenziell)",
        ""
    ])
    
    return "\n".join(output_lines)
