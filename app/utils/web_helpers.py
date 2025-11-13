# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
import os
import logging
import time
import docker
from threading import Lock, Thread
import threading
from flask import current_app # For logging within set_initial_password_from_env if needed
from werkzeug.security import check_password_hash, generate_password_hash
import json
from datetime import datetime, timedelta
import flask

# Gevent-compatible Thread/Lock implementation
try:
    import gevent
    from gevent import monkey
    from gevent.event import Event as GEvent
    from gevent.lock import BoundedSemaphore as GLock
    from gevent import Greenlet
    
    def create_thread(target, args, daemon=True, name=None):
        return Greenlet(target, *args)
        
    def create_event():
        return GEvent()
    
    HAS_GEVENT = True
except ImportError:
    # Fallback to standard threading
    from threading import Lock as GLock
    from threading import Thread, Event
    
    def create_thread(target, args, daemon=True, name=None):
        return Thread(target=target, args=args, daemon=daemon, name=name)
        
    def create_event():
        return Event()
        
    HAS_GEVENT = False

# --- Global Variables / Constants needed by helpers ---
_APP_DIR_HELPER = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT_HELPER = os.path.abspath(os.path.join(_APP_DIR_HELPER, "..", "..")) # Adjusted path to project root

# Constants - keep paths in sync with utils/action_logger.py
LOG_DIR = os.path.join(_PROJECT_ROOT_HELPER, 'logs')
ACTION_LOG_FILE = os.path.join(LOG_DIR, 'user_actions.log')
DISCORD_LOG_FILE = os.path.join(LOG_DIR, 'discord.log')

# Helper function to get advanced settings from config
def _get_advanced_setting(key: str, default_value, value_type=int):
    """Get advanced setting value with fallback to environment variable."""
    try:
        from services.config.config_service import get_config_service
        config = get_config_service().get_config()
        advanced_settings = config.get('advanced_settings', {})
        value = advanced_settings.get(key, os.environ.get(key, default_value))
        if value_type == bool:
            # Special handling for boolean values
            if isinstance(value, bool):
                return value
            return str(value).lower() in ('true', '1', 'yes', 'on')
        return value_type(value)
    except (ImportError, AttributeError, RuntimeError):
        # Service dependency errors (config service unavailable)
        fallback = os.environ.get(key, default_value)
        if value_type == bool:
            return str(fallback).lower() in ('true', '1', 'yes', 'on')
        return value_type(fallback)
    except (ValueError, TypeError, KeyError):
        # Data errors (invalid config values, type conversion failures)
        fallback = os.environ.get(key, default_value)
        if value_type == bool:
            return str(fallback).lower() in ('true', '1', 'yes', 'on')
        return value_type(fallback)

# Improved cache configuration
# CRITICAL: Cache duration MUST be shorter than minimum update interval (1 minute)
# Keep at 45 seconds to ensure fresh data for 1-minute Web UI updates
DEFAULT_CACHE_DURATION = _get_advanced_setting('DDC_DOCKER_CACHE_DURATION', 30)
# Minimum time between Docker API requests in seconds
DOCKER_QUERY_COOLDOWN = _get_advanced_setting('DDC_DOCKER_QUERY_COOLDOWN', 2.0, float)
# Maximum age for container data before forced update in seconds
# Keep at 90 seconds (1.5x cache duration) to support 1-minute updates
MAX_CACHE_AGE = _get_advanced_setting('DDC_DOCKER_MAX_CACHE_AGE', 300)
# Flag to enable background refresh
ENABLE_BACKGROUND_REFRESH = _get_advanced_setting('DDC_ENABLE_BACKGROUND_REFRESH', True, bool)
# Background refresh interval - MUST be frequent for 1-minute update intervals
# Keep at 30 seconds to support minimum 1-minute Web UI update intervals and align with 45s cache TTL
BACKGROUND_REFRESH_INTERVAL = _get_advanced_setting('DDC_BACKGROUND_REFRESH_INTERVAL', 30)
# Background refresh limit - Maximum containers to refresh per cycle
BACKGROUND_REFRESH_LIMIT = _get_advanced_setting('DDC_BACKGROUND_REFRESH_LIMIT', 50)
# Background refresh timeout - Timeout for each refresh operation
BACKGROUND_REFRESH_TIMEOUT = _get_advanced_setting('DDC_BACKGROUND_REFRESH_TIMEOUT', 30)
# Max containers to display in Web UI
MAX_CONTAINERS_DISPLAY = _get_advanced_setting('DDC_MAX_CONTAINERS_DISPLAY', 100)
# Memory optimization: Limit maximum containers in cache
MAX_CACHED_CONTAINERS = _get_advanced_setting('DDC_MAX_CACHED_CONTAINERS', 100)
# Memory optimization: Cache cleanup interval (can be longer since it's just cleanup)
CACHE_CLEANUP_INTERVAL = _get_advanced_setting('DDC_CACHE_CLEANUP_INTERVAL', 300)  # 5 minutes

# Extended cache structure with TTL and container-specific timestamps
docker_cache = {
    'global_timestamp': None,         # Timestamp of last complete refresh
    'containers': [],                 # List of container data
    'error': None,                    # Last error
    'container_timestamps': {},       # Timestamp per container
    'container_hashes': {},           # Hash per container to detect changes
    'bg_refresh_running': False,      # Flag for background refresh
    'priority_containers': set(),     # Set of containers with higher refresh priority
    'last_cleanup': None,             # Timestamp of last cache cleanup
    'access_count': 0                 # Access counter for optimization
}
cache_lock = GLock()  # Use Gevent-compatible lock
last_docker_query_time = 0
background_refresh_thread = None
stop_background_thread = create_event()  # Use Gevent-compatible event

# Mech decay background task globals
mech_decay_thread = None
stop_mech_decay_thread = create_event()  # Use Gevent-compatible event
MECH_DECAY_INTERVAL = _get_advanced_setting('DDC_MECH_DECAY_INTERVAL', 30)  # 30 seconds default

# Initialize the logger instance that will be configured by setup_action_logger
action_logger = logging.getLogger('user_actions')

# --- Helper Functions ---
def setup_action_logger(app_instance):
    """
    Checks if the central action logger from services.infrastructure.action_logger is correctly initialized.
    This function no longer initializes the logger itself, but only tries to use it.
    """
    try:
        # Import the central logger
        from services.infrastructure.action_logger import user_action_logger, _ACTION_LOG_FILE
        
        # Check if the configuration was successful
        if not any(isinstance(h, logging.FileHandler) for h in user_action_logger.handlers):
            app_instance.logger.warning("Action logger has no FileHandler configured! Check utils/action_logger.py")
        else:
            app_instance.logger.info(f"Action logger verified: Logging to {_ACTION_LOG_FILE}")
            
        return user_action_logger
    except ImportError as e:
        # Import errors (action_logger module unavailable)
        app_instance.logger.error(f"Import error loading user_action_logger: {e}", exc_info=True)
        return logging.getLogger('user_actions')  # Fallback
    except (AttributeError, RuntimeError) as e:
        # Service errors (logger configuration issues)
        app_instance.logger.error(f"Service error checking action logger: {e}", exc_info=True)
        return logging.getLogger('user_actions')  # Fallback


def hash_container_data(container_data):
    """Creates a simple hash of container data to detect changes"""
    try:
        # Create a hash from relevant fields
        hash_input = f"{container_data.get('id', '')}-{container_data.get('status', '')}-{container_data.get('image', '')}"
        return hash(hash_input)
    except (TypeError, AttributeError, KeyError):
        # Data errors (invalid container data structure, missing methods/attributes)
        # In case of errors, return a random hash, which leads to reevaluation
        return time.time()

def get_docker_containers_live(logger, force_refresh=False, container_name=None):
    """
    Enhanced function to retrieve Docker container information with advanced caching features.
    
    Args:
        logger: The logger for logging
        force_refresh: Forces a refresh regardless of cache status
        container_name: Optional, specific container name (only filtered for the response)
        
    Returns:
        Tuple (container_list, error_message)
    """
    global last_docker_query_time, docker_cache, background_refresh_thread, stop_background_thread
    
    # Start background thread if not running and enabled
    if ENABLE_BACKGROUND_REFRESH and not docker_cache['bg_refresh_running'] and not background_refresh_thread:
        start_background_refresh(logger)
    
    current_time = time.time()
    with cache_lock:
        # 1. Check if cache is valid (if not force_refresh)
        if not force_refresh and docker_cache['global_timestamp']:
            cache_age = current_time - docker_cache['global_timestamp']
            
            # If the general cache is still fresh
            if cache_age < DEFAULT_CACHE_DURATION:
                # If a specific container was requested, just filter the output
                if container_name:
                    matching_containers = [c for c in docker_cache['containers'] if c['name'] == container_name]
                    if matching_containers:
                        logger.debug(f"Returning filtered cached data for container '{container_name}' (cache age: {cache_age:.1f}s)")
                        return matching_containers, docker_cache['error']
                    logger.debug(f"Container '{container_name}' not found in cache, returning all cached data")
                
                logger.debug(f"Returning fresh docker cache (age: {cache_age:.1f}s)")
                # Apply display limit for Web UI
                containers_to_return = docker_cache['containers'][:MAX_CONTAINERS_DISPLAY] if len(docker_cache['containers']) > MAX_CONTAINERS_DISPLAY else docker_cache['containers']
                if len(docker_cache['containers']) > MAX_CONTAINERS_DISPLAY:
                    logger.debug(f"Limiting display to {MAX_CONTAINERS_DISPLAY} containers (total: {len(docker_cache['containers'])})")
                return list(containers_to_return), docker_cache['error']
            # Force refresh if cache is too old
            elif cache_age > MAX_CACHE_AGE:
                logger.info(f"Cache too old ({cache_age:.1f}s > {MAX_CACHE_AGE}s), forcing refresh")
                force_refresh = True
        
        # 2. Rate limiting check
        time_since_last_query = current_time - last_docker_query_time
        if not force_refresh and time_since_last_query < DOCKER_QUERY_COOLDOWN:
            logger.debug(f"Rate limiting Docker query - within cooldown period ({time_since_last_query:.2f}s < {DOCKER_QUERY_COOLDOWN}s)")
            return list(docker_cache['containers']), docker_cache['error']
    
    # 3. Query Docker API (only if necessary)
    if force_refresh or not docker_cache['global_timestamp']:
        update_docker_cache(logger)
    
    # 4. Updated data to return
    with cache_lock:
        if container_name:
            # Return only the requested container without updating
            matching_containers = [c for c in docker_cache['containers'] if c['name'] == container_name]
            if matching_containers:
                return matching_containers, docker_cache['error']
            # If the container is not found, return all (with display limit)
            containers_to_return = docker_cache['containers'][:MAX_CONTAINERS_DISPLAY] if len(docker_cache['containers']) > MAX_CONTAINERS_DISPLAY else docker_cache['containers']
            return list(containers_to_return), docker_cache['error']
        else:
            # Apply display limit for Web UI
            containers_to_return = docker_cache['containers'][:MAX_CONTAINERS_DISPLAY] if len(docker_cache['containers']) > MAX_CONTAINERS_DISPLAY else docker_cache['containers']
            if len(docker_cache['containers']) > MAX_CONTAINERS_DISPLAY:
                logger.debug(f"Limiting display to {MAX_CONTAINERS_DISPLAY} containers (total: {len(docker_cache['containers'])})")
            return list(containers_to_return), docker_cache['error']

def update_docker_cache(logger):
    """Updates the Docker container cache with current data and memory optimization"""
    global last_docker_query_time, docker_cache
    import gc
    
    logger.info("Updating Docker cache with memory optimization")
    last_docker_query_time = time.time()  # Update query time immediately
    
    client = None
    try:
        client = docker.from_env()
        
        # Retrieve either all containers or just a specific one with timeout
        import signal
        from contextlib import contextmanager
        
        @contextmanager
        def timeout(seconds):
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Operation timed out after {seconds} seconds")
            
            # Only use signal-based timeout on Unix-like systems
            if hasattr(signal, 'SIGALRM'):
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(seconds)
                try:
                    yield
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
            else:
                # On Windows or if SIGALRM not available, just yield without timeout
                yield
        
        try:
            with timeout(BACKGROUND_REFRESH_TIMEOUT):
                containers_to_process = client.containers.list(all=True)
        except TimeoutError as te:
            logger.error(f"Container list operation timed out after {BACKGROUND_REFRESH_TIMEOUT} seconds")
            containers_to_process = []
        
        # Process containers and update cache
        with cache_lock:
            # Increment access counter for optimization tracking
            docker_cache['access_count'] += 1
            
            # Perform periodic cleanup every 50 cache updates
            if docker_cache['access_count'] % 50 == 0:
                _cleanup_docker_cache(logger, time.time())
            
            # Empty the list for a complete refresh
            old_container_count = len(docker_cache['containers'])
            docker_cache['containers'] = []
            
            # Apply both background refresh limit and max cache limit
            # Use the smaller of the two limits
            effective_limit = min(BACKGROUND_REFRESH_LIMIT, MAX_CACHED_CONTAINERS)
            containers_limited = containers_to_process[:effective_limit] if len(containers_to_process) > effective_limit else containers_to_process
            if len(containers_to_process) > effective_limit:
                logger.warning(f"Docker cache: Limiting to {effective_limit} containers (found {len(containers_to_process)}, refresh_limit={BACKGROUND_REFRESH_LIMIT}, cache_limit={MAX_CACHED_CONTAINERS})")
            
            current_time = time.time()
            for container in containers_limited:
                # Create optimized container data (only essential fields)
                container_data = {
                    'id': container.id[:12],
                    'name': container.name,
                    'status': container.status,
                    'image': container.image.tags[0] if container.image.tags else container.image.id[:12]
                }
                
                # Calculate a hash for change detection
                container_hash = hash_container_data(container_data)
                old_hash = docker_cache['container_hashes'].get(container.name)
                
                # Update timestamp and hash only if something has changed
                if old_hash != container_hash:
                    docker_cache['container_timestamps'][container.name] = current_time
                    docker_cache['container_hashes'][container.name] = container_hash
                
                docker_cache['containers'].append(container_data)
            
            # Sort containers by name
            docker_cache['containers'] = sorted(docker_cache['containers'], key=lambda x: x.get('name', '').lower())
            
            # Update global timestamp only for complete refresh
            docker_cache['global_timestamp'] = current_time
            
            docker_cache['error'] = None
            
            container_count = len(docker_cache['containers'])
            memory_saved = old_container_count - container_count if old_container_count > container_count else 0
            logger.info(f"Docker cache updated with {container_count} containers (memory optimization: {memory_saved} containers removed)")
            
            # Force garbage collection periodically
            if docker_cache['access_count'] % 20 == 0:
                gc.collect()
            
    except docker.errors.DockerException as e_outer:
        error_msg = f"Docker connection error during live query: {str(e_outer)}"
        logger.error(error_msg)

        # Enhanced Docker connectivity error logging with actionable information
        logger.warning("🚨 DOCKER CONNECTIVITY FAILURE DETECTED 🚨")
        logger.warning("=" * 60)
        logger.warning("IMPACT: All container controls will show as 'offline without buttons'")
        logger.warning("IMPACT: Discord bot status messages will be corrupted/unavailable")
        logger.warning("IMPACT: System running in FALLBACK MODE with cached data only")
        logger.warning("")
        logger.warning("COMMON CAUSES & SOLUTIONS:")
        logger.warning("1. Docker daemon not running → Check: 'docker ps' on host system")
        logger.warning("2. Docker socket not mounted → Check: '/var/run/docker.sock' mount in DDC container")
        logger.warning("3. Permissions issue → Check: DDC container user has docker group access")
        logger.warning("4. Docker API timeout → Check: Host system Docker performance")
        logger.warning("5. Network connectivity → Check: Container can reach Docker daemon")
        logger.warning("")
        logger.warning("IMMEDIATE ACTIONS:")
        logger.warning("- Verify Docker daemon: systemctl status docker")
        logger.warning("- Check DDC container mounts: Unraid Docker tab → DDC → Edit")
        logger.warning("- Restart DDC container if needed")
        logger.warning("=" * 60)

        with cache_lock:
            docker_cache['error'] = f"🚨 DOCKER CONNECTIVITY LOST: {str(e_outer)}"

    except (ValueError, TypeError, KeyError, AttributeError) as e_general:
        # Data errors (unexpected container data structure, invalid attributes)
        error_msg = f"Data error during live query: {str(e_general)}"
        logger.error(error_msg, exc_info=True)

        # Enhanced general error logging
        logger.warning("⚠️ UNEXPECTED DOCKER QUERY ERROR")
        logger.warning("This may indicate a deeper system issue beyond Docker connectivity")
        logger.warning(f"Error details: {str(e_general)}")
        logger.warning("Check the full traceback above for technical details")

        with cache_lock:
            docker_cache['error'] = f"⚠️ DOCKER QUERY ERROR: {str(e_general)}"
    finally:
        if client:
            try:
                client.close()
            except (AttributeError, RuntimeError) as close_err:
                # Service errors (client close failures, invalid client state)
                logger.debug(f"Error closing Docker client after live query: {close_err}")

def _cleanup_docker_cache(logger, current_time):
    """Performs memory cleanup on Docker cache"""
    if not docker_cache.get('last_cleanup'):
        docker_cache['last_cleanup'] = current_time
        return
    
    # Only cleanup if enough time has passed
    if current_time - docker_cache['last_cleanup'] < CACHE_CLEANUP_INTERVAL:
        return
    
    logger.info("Performing Docker cache memory cleanup")
    
    # Clean up old container timestamps and hashes
    # Use longer cutoff for cleanup (10 minutes) since this is just memory management
    cutoff_time = current_time - 600  # Keep data for 10 minutes
    
    old_timestamps = docker_cache['container_timestamps'].copy()
    old_hashes = docker_cache['container_hashes'].copy()
    
    # Remove old entries
    for container_name in list(old_timestamps.keys()):
        if old_timestamps[container_name] < cutoff_time:
            docker_cache['container_timestamps'].pop(container_name, None)
            docker_cache['container_hashes'].pop(container_name, None)
    
    removed_count = len(old_timestamps) - len(docker_cache['container_timestamps'])
    if removed_count > 0:
        logger.info(f"Docker cache cleanup: Removed {removed_count} old container entries")
    
    docker_cache['last_cleanup'] = current_time
    
    # Force garbage collection after cleanup
    import gc
    gc.collect()

def background_refresh_worker(logger):
    """Background worker for regular Docker cache updates"""
    logger.info("Starting background Docker cache refresh worker")
    
    thread_name = threading.current_thread().name if hasattr(threading.current_thread(), 'name') else "Greenlet"
    logger.debug(f"Background worker running in thread '{thread_name}'")
    
    with cache_lock:
        docker_cache['bg_refresh_running'] = True
    
    try:
        while not stop_background_thread.is_set():
            try:
                # Update the cache
                update_docker_cache(logger)
                
                # Wait for the configured time, but check regularly for stop signal
                # Shorten the interval to notice the stop signal faster
                check_interval = min(BACKGROUND_REFRESH_INTERVAL, 5) # Max. 5 seconds without checking the stop signal
                remaining_time = BACKGROUND_REFRESH_INTERVAL
                
                while remaining_time > 0 and not stop_background_thread.is_set():
                    wait_time = min(check_interval, remaining_time)
                    if HAS_GEVENT:
                        gevent.sleep(wait_time)
                    else:
                        time.sleep(wait_time)
                    remaining_time -= wait_time

            except (ImportError, AttributeError, RuntimeError) as e:
                # Service dependency errors (docker service unavailable, cache update failures)
                logger.error(f"Service error in background refresh worker: {str(e)}", exc_info=True)
                # In case of errors, wait briefly and try again
                # Also use smaller interval here for better response to stop signal
                for _ in range(5): # 5x1 second instead of once 5 seconds
                    if stop_background_thread.is_set():
                        break
                    if HAS_GEVENT:
                        gevent.sleep(1)
                    else:
                        time.sleep(1)
            except (ValueError, TypeError, KeyError) as e:
                # Data errors (invalid cache data, unexpected data structures)
                logger.error(f"Data error in background refresh worker: {str(e)}", exc_info=True)
                # In case of errors, wait briefly and try again
                # Also use smaller interval here for better response to stop signal
                for _ in range(5): # 5x1 second instead of once 5 seconds
                    if stop_background_thread.is_set():
                        break
                    if HAS_GEVENT:
                        gevent.sleep(1)
                    else:
                        time.sleep(1)
    except (AttributeError, RuntimeError) as e:
        # Service/runtime errors (thread/event errors, gevent issues)
        logger.error(f"Runtime error in background worker thread: {e}", exc_info=True)
    finally:
        with cache_lock:
            docker_cache['bg_refresh_running'] = False
        logger.info("Background Docker cache refresh worker stopped")

async def check_docker_connectivity(logger):
    """Immediate Docker connectivity check using SERVICE FIRST architecture"""
    logger.info("🔍 Performing Docker connectivity check...")

    # Use DockerConnectivityService following SERVICE FIRST principle
    from services.infrastructure.docker_connectivity_service import get_docker_connectivity_service, DockerConnectivityRequest

    connectivity_service = get_docker_connectivity_service()
    connectivity_request = DockerConnectivityRequest(timeout_seconds=5.0)
    connectivity_result = await connectivity_service.check_connectivity(connectivity_request)

    if connectivity_result.is_connected:
        logger.info("✅ Docker connectivity: SUCCESS")
        return True
    else:
        logger.error("🚨 DOCKER CONNECTIVITY CHECK FAILED 🚨")
        logger.error("=" * 60)
        logger.error(f"Error: {connectivity_result.error_message}")
        logger.error(f"Type: {connectivity_result.error_type}")
        if connectivity_result.technical_details:
            logger.error(f"Details: {connectivity_result.technical_details}")
        logger.error("")
        logger.error("SYSTEM IMPACT:")
        logger.error("- Container controls will show as 'offline without buttons'")
        logger.error("- Discord bot status messages will fail")
        logger.error("- Web UI will use fallback/cached data only")
        logger.error("")
        logger.error("TROUBLESHOOTING STEPS:")
        logger.error("1. Check Docker daemon on host: 'docker ps'")
        logger.error("2. Verify DDC container has Docker socket mounted:")
        logger.error("   → Unraid: Docker tab → DDC → Edit → Extra Parameters")
        logger.error("   → Should include: -v /var/run/docker.sock:/var/run/docker.sock")
        logger.error("3. Check DDC container user permissions (docker group)")
        logger.error("4. Restart DDC container if needed")
        logger.error("=" * 60)
        return False

def start_background_refresh(logger):
    """Starts the background thread for cache updates"""
    global background_refresh_thread, stop_background_thread

    # Immediate Docker connectivity check (sync wrapper for async function)
    import asyncio
    try:
        connectivity_ok = asyncio.get_event_loop().run_until_complete(check_docker_connectivity(logger))
    except (RuntimeError, AttributeError) as e:
        # Runtime errors (event loop issues, asyncio problems)
        logger.error(f"Runtime error during Docker connectivity check: {e}", exc_info=True)
        connectivity_ok = False
    except (ImportError, ValueError) as e:
        # Import/data errors (service unavailable, invalid parameters)
        logger.error(f"Service error during Docker connectivity check: {e}", exc_info=True)
        connectivity_ok = False

    if not connectivity_ok:
        logger.warning("⚠️ Starting background refresh despite Docker connectivity issues")
        logger.warning("Background refresh will continue attempting to connect...")

    # Check if thread is already running
    if background_refresh_thread:
        if (HAS_GEVENT and not background_refresh_thread.dead) or \
           (not HAS_GEVENT and background_refresh_thread.is_alive()):
            logger.debug("Background refresh thread already running")
            return

    # Start a new thread only if the previous one is no longer running
    stop_background_thread.clear()

    # Thread creation with Gevent compatibility
    background_refresh_thread = create_thread(
        background_refresh_worker,
        (logger,),
        daemon=True,
        name="DockerCacheRefresh"
    )

    # Start the thread
    if HAS_GEVENT:
        background_refresh_thread.start_later(0)
    else:
        background_refresh_thread.start()

    logger.info("Started background Docker cache refresh thread")

def stop_background_refresh(logger):
    """Stops the background thread for cache updates"""
    global background_refresh_thread, stop_background_thread
    
    logger.info("Stopping background Docker cache refresh thread")
    
    # Set signal to stop
    stop_background_thread.set()
    
    # If no thread is active, exit immediately
    if background_refresh_thread is None:
        logger.debug("No background thread to stop")
        return
    
    try:
        # Copy thread reference for safety
        thread_to_join = background_refresh_thread
        
        # Delete thread reference immediately to avoid an assertion in gevent.threading._ForkHooks
        # This must happen BEFORE the thread join
        background_refresh_thread = None
        
        # Ensure the cache flag is reset
        with cache_lock:
            docker_cache['bg_refresh_running'] = False
        
        # In Gevent-environment simply use greenlet.kill()
        if HAS_GEVENT and not thread_to_join.dead:
            try:
                thread_to_join.kill(block=False)
            except (AttributeError, RuntimeError) as e:
                # Runtime errors (greenlet kill failures, invalid greenlet state)
                logger.error(f"Runtime error killing greenlet: {e}", exc_info=True)
        # In normal thread environment wait for thread
        elif not HAS_GEVENT and thread_to_join.is_alive():
            try:
                # Max 1 second wait - extended wait time can lead to blocking
                thread_to_join.join(timeout=1.0)
                
                # Warning if thread does not end
                if thread_to_join.is_alive():
                    logger.warning("Background thread did not terminate within timeout")
            except (RuntimeError, AttributeError) as e:
                # Runtime errors (thread join failures, invalid thread state)
                logger.error(f"Runtime error while joining background thread: {e}", exc_info=True)
    except (AttributeError, RuntimeError, TypeError) as e:
        # Runtime/data errors (thread cleanup failures, invalid thread attributes)
        logger.error(f"Error during thread cleanup: {e}", exc_info=True)


def mech_decay_worker(logger):
    """
    Background worker for mech power decay calculation.

    SINGLE POINT OF TRUTH: progress_service.get_state()

    This worker simply calls get_state() every 30 seconds. The actual decay
    calculation happens in progress_service, which is the single source of truth.
    Both Discord Bot and Web UI can call get_state() - it's idempotent!
    """
    logger.info("Starting mech decay background worker")

    thread_name = threading.current_thread().name if hasattr(threading.current_thread(), 'name') else "Greenlet"
    logger.debug(f"Mech decay worker running in thread '{thread_name}'")

    try:
        while not stop_mech_decay_thread.is_set():
            try:
                # SINGLE POINT OF TRUTH: Call progress_service.get_state()
                # This triggers on-demand decay calculation
                from services.mech.progress_service import get_progress_service
                mech_service = get_progress_service()

                # get_state() triggers apply_decay_on_demand()
                mech_state = mech_service.get_state()

                # Log if offline (Power = 0) for debugging
                if mech_state.is_offline:
                    logger.info(f"[MECH_DECAY] Mech is OFFLINE (Power: $0.00) - offline animation active")
                else:
                    logger.debug(f"[MECH_DECAY] Power decay calculated: ${mech_state.power_current:.2f}")

                # Wait for the configured time, but check regularly for stop signal
                check_interval = min(MECH_DECAY_INTERVAL, 5)  # Max 5 seconds without checking stop signal
                remaining_time = MECH_DECAY_INTERVAL

                while remaining_time > 0 and not stop_mech_decay_thread.is_set():
                    wait_time = min(check_interval, remaining_time)
                    if HAS_GEVENT:
                        gevent.sleep(wait_time)
                    else:
                        time.sleep(wait_time)
                    remaining_time -= wait_time

            except (ImportError, AttributeError, RuntimeError) as e:
                # Service dependency errors (mech service unavailable, tick_decay failures)
                logger.error(f"Service error in mech decay worker: {str(e)}", exc_info=True)
                # In case of errors, wait briefly and try again
                for _ in range(5):  # 5x1 second instead of once 5 seconds
                    if stop_mech_decay_thread.is_set():
                        break
                    if HAS_GEVENT:
                        gevent.sleep(1)
                    else:
                        time.sleep(1)
    except (AttributeError, RuntimeError) as e:
        # Runtime errors (thread/event errors, gevent issues)
        logger.error(f"Runtime error in mech decay worker thread: {e}", exc_info=True)
    finally:
        logger.info("Mech decay background worker stopped")


def start_mech_decay_background(logger):
    """Starts the background thread for mech power decay calculation"""
    global mech_decay_thread, stop_mech_decay_thread

    # Check if thread is already running
    if mech_decay_thread:
        if (HAS_GEVENT and not mech_decay_thread.dead) or \
           (not HAS_GEVENT and mech_decay_thread.is_alive()):
            logger.debug("Mech decay background thread already running")
            return

    # Start a new thread only if the previous one is no longer running
    stop_mech_decay_thread.clear()

    # Thread creation with Gevent compatibility
    mech_decay_thread = create_thread(
        mech_decay_worker,
        (logger,),
        daemon=True,
        name="MechDecayWorker"
    )

    # Start the thread
    if HAS_GEVENT:
        mech_decay_thread.start_later(0)
    else:
        mech_decay_thread.start()

    logger.info("Started mech decay background thread")


def stop_mech_decay_background(logger):
    """Stops the background thread for mech power decay calculation"""
    global mech_decay_thread, stop_mech_decay_thread

    logger.info("Stopping mech decay background thread")

    # Set signal to stop
    stop_mech_decay_thread.set()

    # If no thread is active, exit immediately
    if mech_decay_thread is None:
        logger.debug("No mech decay thread to stop")
        return

    try:
        # Copy thread reference for safety
        thread_to_join = mech_decay_thread

        # Delete thread reference immediately to avoid assertion in gevent.threading._ForkHooks
        mech_decay_thread = None

        # In Gevent environment simply use greenlet.kill()
        if HAS_GEVENT and not thread_to_join.dead:
            try:
                thread_to_join.kill(block=False)
            except (AttributeError, RuntimeError) as e:
                # Runtime errors (greenlet kill failures, invalid greenlet state)
                logger.error(f"Runtime error killing mech decay greenlet: {e}", exc_info=True)
        # In normal thread environment wait for thread
        elif not HAS_GEVENT and thread_to_join.is_alive():
            try:
                # Max 1 second wait
                thread_to_join.join(timeout=1.0)

                # Warning if thread does not end
                if thread_to_join.is_alive():
                    logger.warning("Mech decay thread did not terminate within timeout")
            except (RuntimeError, AttributeError) as e:
                # Runtime errors (thread join failures, invalid thread state)
                logger.error(f"Runtime error while joining mech decay thread: {e}", exc_info=True)
    except (AttributeError, RuntimeError, TypeError) as e:
        # Runtime/data errors (thread cleanup failures, invalid thread attributes)
        logger.error(f"Error during mech decay thread cleanup: {e}", exc_info=True)


def set_initial_password_from_env():
    # This function is called at module level, so current_app might not be available.
    # Using a dedicated logger or print for errors here.
    init_pass_logger = logging.getLogger("set_initial_password_helper")
    # Basic configuration for this logger if not configured elsewhere
    if not init_pass_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        init_pass_logger.addHandler(handler)
        init_pass_logger.setLevel(logging.INFO)

    env_password = os.environ.get('DDC_ADMIN_PASSWORD')
    if not env_password:
        init_pass_logger.debug("DDC_ADMIN_PASSWORD not set, skipping initial password setup.")
        return
    try:
        # Attempt to import config_loader dynamically, as it might also be refactored
        from services.config.config_service import load_config, save_config
        
        config_path_check = os.path.join(_PROJECT_ROOT_HELPER, "config", "config.json")
        init_pass_logger.info(f"Attempting to load config from: {config_path_check} for initial password set.")

        config = load_config() # Assumes load_config knows its path or is configured
        current_hash = config.get('web_ui_password_hash')
        
        # Check if password is the default "admin" or not set
        # The original check was: check_password_hash(current_hash, 'admin')
        # This requires a hash to be present. A safer check is if it's None or if it matches 'admin'.
        is_default_or_unset = False
        if current_hash is None:
            is_default_or_unset = True
        else:
            try:
                if check_password_hash(current_hash, 'admin'):
                    is_default_or_unset = True
            except (ValueError, TypeError) as e_hash_check:
                # Data errors (malformed hash, invalid hash format)
                init_pass_logger.warning(f"Data error checking password hash (possibly malformed): {e_hash_check}. Assuming it needs to be reset if env var is present.")
                is_default_or_unset = True # Opt to reset if unsure

        if is_default_or_unset:
            init_pass_logger.info("Setting initial Web UI password from DDC_ADMIN_PASSWORD env var...")
            config['web_ui_password_hash'] = generate_password_hash(env_password, method="pbkdf2:sha256")
            save_config(config) # Assumes save_config knows its path or is configured
            init_pass_logger.info("Web UI password hash has been updated from environment variable.")
        else:
            init_pass_logger.debug("Web UI password already set to a non-default value. Skipping update from env var.")
            
    except ImportError as e_imp:
        # Import errors (config service unavailable)
        init_pass_logger.error(f"Import error loading config service for initial password set: {e_imp}", exc_info=True)
    except FileNotFoundError as e_fnf:
        # File I/O errors (config file not found)
        init_pass_logger.error(f"Config file not found during initial password set: {e_fnf}", exc_info=True)
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
        # Data/service errors (invalid config data, hash generation failures, save failures)
        init_pass_logger.error(f"Error setting initial password: {e}", exc_info=True) 