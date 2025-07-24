# -*- coding: utf-8 -*-
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
from typing import Optional, List, Dict, Any, Tuple

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

# Improved cache configuration
# Default: 75 seconds cache duration to match DockerControlCog cache
DEFAULT_CACHE_DURATION = int(os.environ.get('DDC_DOCKER_CACHE_DURATION', 75))
# Minimum time between Docker API requests in seconds
DOCKER_QUERY_COOLDOWN = float(os.environ.get('DDC_DOCKER_QUERY_COOLDOWN', 1.0))
# Maximum age for container data before forced update in seconds
MAX_CACHE_AGE = int(os.environ.get('DDC_DOCKER_MAX_CACHE_AGE', 150))
# Flag to enable background refresh
ENABLE_BACKGROUND_REFRESH = os.environ.get('DDC_ENABLE_BACKGROUND_REFRESH', 'true').lower() == 'true'
# Background refresh interval (more frequent than Discord bot queries)
BACKGROUND_REFRESH_INTERVAL = int(os.environ.get('DDC_BACKGROUND_REFRESH_INTERVAL', 30))

# Extended cache structure with TTL and container-specific timestamps
docker_cache = {
    'global_timestamp': None,         # Timestamp of last complete refresh
    'containers': [],                 # List of container data
    'error': None,                    # Last error
    'container_timestamps': {},       # Timestamp per container
    'container_hashes': {},           # Hash per container to detect changes
    'bg_refresh_running': False,      # Flag for background refresh
    'priority_containers': set()      # Set of containers with higher refresh priority
}
cache_lock = GLock()  # Use Gevent-compatible lock
last_docker_query_time = 0
background_refresh_thread = None
stop_background_thread = create_event()  # Use Gevent-compatible event

# Initialize the logger instance that will be configured by setup_action_logger
action_logger = logging.getLogger('user_actions')

# --- Helper Functions ---
def setup_action_logger(app_instance):
    """
    Checks if the central action logger from utils.action_logger is correctly initialized.
    This function no longer initializes the logger itself, but only tries to use it.
    """
    try:
        # Import the central logger
        from utils.action_logger import user_action_logger, _ACTION_LOG_FILE
        
        # Check if the configuration was successful
        if not any(isinstance(h, logging.FileHandler) for h in user_action_logger.handlers):
            app_instance.logger.warning("Action logger has no FileHandler configured! Check utils/action_logger.py")
        else:
            app_instance.logger.info(f"Action logger verified: Logging to {_ACTION_LOG_FILE}")
            
        return user_action_logger
    except ImportError as e:
        app_instance.logger.error(f"Failed to import user_action_logger from utils.action_logger: {e}")
        return logging.getLogger('user_actions')  # Fallback
    except Exception as e:
        app_instance.logger.error(f"Unexpected error checking action logger: {e}")
        return logging.getLogger('user_actions')  # Fallback

def log_user_action(action: str, target: str, source: str = "Web UI", details: str = ""):
    """Log user actions for audit purposes in the Web UI.
    
    This is a wrapper around the central log_user_action function that maintains
    the original parameter style for backward compatibility with Web UI code.
    """
    try:
        # Import here to avoid circular imports
        from utils.action_logger import log_user_action as central_log_user_action
        
        # Get the current user if available
        user = "System"
        if flask.has_request_context() and hasattr(flask.g, "user"):
            user = getattr(flask.g, "user", "Unknown Web User")
        
        # Call the central function with our parameters
        central_log_user_action(
            action=action,
            target=target,
            user=user,
            source=source,
            details=details
        )
    except Exception as e:
        app_logger = logging.getLogger('ddc.app')
        app_logger.error(f"Error in log_user_action: {e}")
        # Try to log directly as fallback
        try:
            user_action_logger = logging.getLogger('user_actions')
            if user_action_logger:
                user_logger_msg = f"{action}|{target}|Web UI|{source}|{details}"
                user_action_logger.info(user_logger_msg)
        except:
            pass

def hash_container_data(container_data):
    """Creates a simple hash of container data to detect changes"""
    try:
        # Create a hash from relevant fields
        hash_input = f"{container_data.get('id', '')}-{container_data.get('status', '')}-{container_data.get('image', '')}"
        return hash(hash_input)
    except Exception:
        # In case of errors, return a random hash, which leads to reevaluation
        return time.time()

def get_docker_containers_live(logger, force_refresh: bool = False, container_name: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
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
                return list(docker_cache['containers']), docker_cache['error']
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
            # If the container is not found, return all
            return list(docker_cache['containers']), docker_cache['error']
        else:
            return list(docker_cache['containers']), docker_cache['error']

def update_docker_cache(logger):
    """Updates the Docker container cache with current data"""
    global last_docker_query_time, docker_cache
    
    logger.info("Updating Docker cache")
    last_docker_query_time = time.time()  # Update query time immediately
    
    client = None
    try:
        client = docker.from_env()
        
        # Retrieve either all containers or just a specific one
        containers_to_process = client.containers.list(all=True)
        
        # Process containers and update cache
        with cache_lock:
            # Empty the list for a complete refresh
            docker_cache['containers'] = []
            
            current_time = time.time()
            for container in containers_to_process:
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
            logger.info(f"Docker cache updated with {container_count} containers.")
            
    except docker.errors.DockerException as e_outer:
        error_msg = f"Docker connection error during live query: {str(e_outer)}"
        logger.error(error_msg)
        with cache_lock:
            docker_cache['error'] = error_msg
    except Exception as e_general:
        error_msg = f"Unexpected error during live query: {str(e_general)}"
        logger.error(error_msg, exc_info=True)
        with cache_lock:
            docker_cache['error'] = error_msg
    finally:
        if client:
            try:
                client.close()
            except Exception as close_err:
                logger.debug(f"Error closing Docker client after live query: {close_err}")

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
                    
            except Exception as e:
                logger.error(f"Error in background refresh worker: {str(e)}", exc_info=True)
                # In case of errors, wait briefly and try again
                # Also use smaller interval here for better response to stop signal
                for _ in range(5): # 5x1 second instead of once 5 seconds
                    if stop_background_thread.is_set():
                        break
                    if HAS_GEVENT:
                        gevent.sleep(1)
                    else:
                        time.sleep(1)
    except Exception as e:
        logger.error(f"Unexpected error in background worker thread: {e}", exc_info=True)
    finally:
        with cache_lock:
            docker_cache['bg_refresh_running'] = False
        logger.info("Background Docker cache refresh worker stopped")

def start_background_refresh(logger):
    """Starts the background thread for cache updates"""
    global background_refresh_thread, stop_background_thread
    
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
            except Exception as e:
                logger.error(f"Error killing greenlet: {e}")
        # In normal thread environment wait for thread
        elif not HAS_GEVENT and thread_to_join.is_alive():
            try:
                # Max 1 second wait - extended wait time can lead to blocking
                thread_to_join.join(timeout=1.0)
                
                # Warning if thread does not end
                if thread_to_join.is_alive():
                    logger.warning("Background thread did not terminate within timeout")
            except Exception as e:
                logger.error(f"Error while joining background thread: {e}")
    except Exception as e:
        logger.error(f"Error during thread cleanup: {e}")

def set_container_priority(container_name, is_priority=True):
    """Sets the priority for a container"""
    with cache_lock:
        if is_priority:
            docker_cache['priority_containers'].add(container_name)
        elif container_name in docker_cache['priority_containers']:
            docker_cache['priority_containers'].remove(container_name)

def invalidate_container_cache(container_name=None):
    """Invalidates the cache for one or all containers"""
    with cache_lock:
        if container_name:
            # Remove timestamp for specific container
            if container_name in docker_cache['container_timestamps']:
                del docker_cache['container_timestamps'][container_name]
            if container_name in docker_cache['container_hashes']:
                del docker_cache['container_hashes'][container_name]
        else:
            # Invalidate the entire cache
            docker_cache['global_timestamp'] = None
            docker_cache['container_timestamps'] = {}
            docker_cache['container_hashes'] = {}

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
        from utils.config_loader import load_config, save_config
        
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
            except Exception as e_hash_check: # Handle cases where hash might be malformed
                init_pass_logger.warning(f"Could not check current password hash (possibly malformed): {e_hash_check}. Assuming it needs to be reset if env var is present.")
                is_default_or_unset = True # Opt to reset if unsure

        if is_default_or_unset:
            init_pass_logger.info("Setting initial Web UI password from DDC_ADMIN_PASSWORD env var...")
            config['web_ui_password_hash'] = generate_password_hash(env_password, method="pbkdf2:sha256")
            save_config(config) # Assumes save_config knows its path or is configured
            init_pass_logger.info("Web UI password hash has been updated from environment variable.")
        else:
            init_pass_logger.debug("Web UI password already set to a non-default value. Skipping update from env var.")
            
    except ImportError as e_imp:
        init_pass_logger.error(f"Could not import config_loader for initial password set: {e_imp}")
    except FileNotFoundError as e_fnf:
        init_pass_logger.error(f"Config file not found during initial password set: {e_fnf}")
    except Exception as e:
        init_pass_logger.error(f"Error setting initial password: {e}", exc_info=True) 