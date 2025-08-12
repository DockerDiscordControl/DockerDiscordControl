import os

# --- Gevent Monkey Patching ---
# IMPORTANT: This must be done BEFORE any other modules that might use ssl,
# such as requests, urllib3, or even Flask itself indirectly.
if os.getenv("GUNICORN_WORKER_CLASS", "sync") == "gevent":
    try:
        import gevent.monkey
        gevent.monkey.patch_all()
        print("Gevent monkey patches applied.") # Use print for early feedback
    except ImportError:
        print("Gevent not installed, cannot apply monkey patches.")
    except Exception as e:
        print(f"Error applying Gevent monkey patches: {e}")
# -----------------------------

import multiprocessing
import logging
import atexit
from apscheduler.schedulers.background import BackgroundScheduler

# Assumption: web_ui.py is in the 'app' subdirectory
# Adjust the Python path so we can import modules from 'app'
import sys
sys.path.insert(0, '/app')

# Import necessary functions/objects from the web app
# It's important that these imports do not trigger Flask app initialization at the module level,
# which is handled by Gunicorn itself.
try:
    # Import directly from source modules, not via app.web_ui
    from utils.config_loader import load_config
    from app.utils.web_helpers import get_docker_containers_live 
    # Setup logger
    logging.basicConfig(level=logging.INFO) # Ensure basicConfig is called somewhere
    logger = logging.getLogger("gunicorn.config")
    logger.info("Gunicorn config logger initialized.")
except ImportError as e:
    # Fallback logger 
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.error(f"Error importing required components: {e}.") 
    sys.exit("Critical import error in gunicorn_config.py")


# --- Optimized Gunicorn Configuration for Discord Bot Web UI ---
# RAM-Optimized: Dramatically reduced from 8 workers to 2-3 for realistic usage

# RAM-OPTIMIZED: Single worker for Discord Bot Web UI (prevents duplicate initialization)
# Discord Bot Web UI is low-traffic, single user access - no need for multiple workers
cpu_count = multiprocessing.cpu_count()
# OPTIMIZED: Force single worker to prevent duplicate startup processes
workers = int(os.getenv('GUNICORN_WORKERS', 1))  # Force single worker
logger.info(f"Gunicorn starting with {workers} worker (Discord Bot optimized - prevents duplicate initialization)")

# Address and port Gunicorn should listen on
bind = "0.0.0.0:9374"

# Worker class (gevent for asynchronous workers)
worker_class = "gevent"

# OPTIMIZED: Reduced timeout for faster resource cycling
timeout = int(os.getenv('GUNICORN_TIMEOUT', '45'))  # Reduced from 60s to 45s

# MEMORY-OPTIMIZED: Faster worker recycling to prevent memory leaks
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '300'))  # Reduced from 500 to 300
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '30'))  # Reduced from 50 to 30

# Logging - Gunicorn logs go to stdout/stderr, which Supervisor catches
accesslog = "-"
errorlog = "-"
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# --- Scheduler and Hooks ---
def when_ready(server):
    """Gunicorn Hook: Executed when the master process is ready (before forking workers)."""
    logger.info(f"[Gunicorn Master {os.getpid()}] Server ready. Performing initial cache population...")

    try:
        # Fill initial cache synchronously (keep this part)
        logger.info(f"[Gunicorn Master {os.getpid()}] Performing initial Docker cache update...")
        get_docker_containers_live(logger) # Pass the logger
        logger.info(f"[Gunicorn Master {os.getpid()}] Initial cache update complete.")

    except Exception as e:
        logger.error(f"[Gunicorn Master {os.getpid()}] Error during initial cache population: {e}", exc_info=True)

# --- RAM-OPTIMIZED Gunicorn Server Configuration ---

# Path to WSGI application
wsgi_app = "app.web_ui:create_app()"

# Worker & Threading - HEAVILY OPTIMIZED FOR RAM
# OPTIMIZED: No duplicate worker definition - using optimized_workers from above
worker_class = "gevent"  # Use Gevent for asynchronous processing
worker_connections = 200  # OPTIMIZED: Reduced from 1000 to 200 (Discord Bot usage)
threads = 1  # For Gevent workers: Use 1 thread

# Timeouts - OPTIMIZED (using the configurable timeout from above)
graceful_timeout = 10  # Time workers get to terminate
keepalive = 3  # OPTIMIZED: Reduced from 5s to 3s for faster resource cleanup

# Binding
bind = "0.0.0.0:9374"  # Host:Port for binding
backlog = 512  # OPTIMIZED: Reduced from 2048 to 512

# HTTP Settings - RAM OPTIMIZED (moved to top section)
# max_requests and max_requests_jitter now defined above

# Logging - Always use stdout/stderr for container logging best practices
# This avoids permission issues with log files and integrates with Docker logging
accesslog = "-"
errorlog = "-"

loglevel = (
    os.environ.get('GUNICORN_LOG_LEVEL')
    or os.environ.get('LOGGING_LEVEL')
    or 'info'
).lower()

capture_output = True  # Log stdout/stderr of the application
access_log_format = '%({X-Forwarded-For}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process management
daemon = False  # Don't run as daemon
pidfile = None  # No PID file (managed by Supervisor)
# Note: user and group are handled by supervisord when running as non-root
# Setting these to None allows supervisord to manage the user context
user = None  # User handled by supervisord (runs as 'ddc' user)
group = None  # Group handled by supervisord (runs as 'ddc' group)
umask = 0o022  # More restrictive file permissions mask for security

# Gevent-specific optimizations - RAM OPTIMIZED
gevent_monkey_patching = True  # Enables monkey patching
worker_greenlet_concurrency = 200  # OPTIMIZED: Reduced from 1000 to 200

# OPTIMIZED: Reduced thread pool size for lower RAM usage
def post_fork(server, worker):
    # RAM-optimized thread pool size
    if worker_class == "gevent":
        # OPTIMIZED: Reduced threadpool from 20 to 10
        import gevent.hub
        gevent.hub.get_hub().threadpool_size = 10  # Reduced from 20
        
        try:
            # Adjust the hub for better thread compatibility
            from gevent import monkey
            from gevent.threading import _ForkHooks
            
            # Safe hooks for better thread compatibility
            original_after_fork = _ForkHooks.after_fork_in_child
            
            def safer_after_fork_in_child(self):
                # Override the assert check - fixed parameter signature
                pass
                
            # Replace the hook method
            _ForkHooks.after_fork_in_child = safer_after_fork_in_child
            
            # Provide worker info
            worker.log.info(f"RAM-optimized Gevent worker (threadpool: 10, connections: 200)")
        except (ImportError, AttributeError) as e:
            worker.log.warning(f"Could not patch Gevent fork hooks: {e}")

# Pre-initialization before worker start
def pre_exec(server):
    server.log.info("Initializing RAM-optimized server (pre-exec)")

# Dynamic settings based on environment variables
if os.environ.get('DDC_DISABLE_CACHE_LOCKS', '').lower() == 'true':
    os.environ['DDC_CACHE_LOCKS_DISABLED'] = 'true'
    server_socket = "/tmp/gunicorn.sock" 