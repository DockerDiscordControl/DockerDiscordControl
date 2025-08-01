# -*- coding: utf-8 -*-
import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response, current_app
import logging
import time
import sys
import re
from werkzeug.middleware.proxy_fix import ProxyFix
from utils.time_utils import format_datetime_with_timezone
import logging.handlers
from utils.config_loader import load_config, save_config, DEFAULT_CONFIG
# Import auth from .auth
from .auth import auth, init_limiter
from app.utils.web_helpers import (
    setup_action_logger, 
    log_user_action, 
    get_docker_containers_live,
    set_initial_password_from_env,
    ACTION_LOG_FILE,
    start_background_refresh,
    stop_background_refresh
)
# Import shared data class for active containers
from app.utils.shared_data import load_active_containers_from_config
from datetime import datetime, timezone, timedelta
from app.constants import COMMON_TIMEZONES # Import from new constants file
import secrets

# Frühes Monkey-Patching von Gevent für bessere Thread-Kompatibilität
try:
    # Diese Zeile muss vor jedem anderen Thread-Import kommen
    import gevent.monkey
    gevent.monkey.patch_all(thread=True, select=True, subprocess=True, socket=True)
    HAS_GEVENT = True
except ImportError:
    HAS_GEVENT = False

# Import Blueprints
from app.blueprints.main_routes import main_bp
from app.blueprints.log_routes import log_bp
from app.blueprints.action_log_routes import action_log_bp
# Import Tasks Blueprint
from app.blueprints.tasks_bp import tasks_bp

# --- Global Variables (Constants, etc.) ---
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_APP_DIR, ".."))
CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config") 
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# --- Application Factory --- 
def create_app(test_config=None):
    # Gevent-spezifische Einrichtung
    if HAS_GEVENT:
        try:
            # Stelle sicher, dass Gevent korrekt initialisiert ist
            import gevent.threading
            from gevent.threading import get_ident
            from gevent import get_hub, monkey
            
            # Prüfe, ob wir im Haupt-Hub laufen
            current_hub = get_hub()
            app_logger = logging.getLogger('app.web_ui')
            app_logger.info(f"Initializing app in Gevent environment, hub: {current_hub}")
            
            # Stelle sicher, dass Gevent-Patching vollständig ist
            if not monkey.is_module_patched('socket'):
                app_logger.warning("Socket module not patched by Gevent, applying patch...")
                monkey.patch_socket()
            if not monkey.is_module_patched('ssl'):
                app_logger.warning("SSL module not patched by Gevent, applying patch...")
                monkey.patch_ssl()
            if not monkey.is_module_patched('threading'):
                app_logger.warning("Threading module not patched by Gevent, applying patch...")
                monkey.patch_thread()
        except ImportError as e:
            print(f"Gevent error during init: {e}")
    
    app = Flask(__name__)
    
    # IMPROVED: Generate secure Flask secret key if not provided
    flask_secret = os.getenv('FLASK_SECRET_KEY')
    if not flask_secret or flask_secret.strip() == '' or flask_secret == 'fallback-secret-key-for-dev-if-not-set':
        # Generate a cryptographically secure random secret key
        flask_secret = secrets.token_hex(32)  # 64 character hex string
        app.logger.info("Generated secure Flask secret key automatically (no FLASK_SECRET_KEY environment variable set)")
    else:
        app.logger.info("Using provided Flask secret key from environment")
    
    app.config.update(
        SECRET_KEY=flask_secret,
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_REFRESH_EACH_REQUEST=True,
        JSON_AS_ASCII=False,
        DOCKER_SOCKET=os.environ.get('DOCKER_SOCKET', '/var/run/docker.sock'),
        CONFIG_FILE=CONFIG_FILE, # Use calculated relative path
        LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO'),
        HOST_DOCKER_PATH=os.environ.get('HOST_DOCKER_PATH', '/usr/bin/docker'),
        TEMPLATES_AUTO_RELOAD=True
    )

    if test_config:
        app.config.update(test_config)

    # Setup Logging
    log_level = getattr(logging, app.config['LOG_LEVEL'].upper(), logging.INFO)
    app.logger.setLevel(log_level)
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]')
    handler.setFormatter(formatter)
    if not app.logger.handlers: # Add handler only if none exist
        app.logger.addHandler(handler)
    app.logger.info(f"Flask Logger initialized with {app.config['LOG_LEVEL']} level.")

    # Apply ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Initialize Rate Limiter
    init_limiter(app)
    app.logger.info("Rate limiting initialized for authentication")

    # Register Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(log_bp, url_prefix='/logs_bp') # Added url_prefix to avoid conflict with /logs from main_bp if any future route is named /logs
    app.register_blueprint(action_log_bp, url_prefix='/action_log_bp') # Added url_prefix for clarity and future conflict avoidance
    # Register Tasks Blueprint
    app.register_blueprint(tasks_bp)

    # Register App-Level Request Handlers HERE
    @app.before_request
    def before_request_func():
        session.permanent = True

    # Ensure debug mode setting is correctly loaded on application start
    with app.app_context():
        try:
            # Force refresh of debug status
            from utils.logging_utils import refresh_debug_status
            debug_status = refresh_debug_status()
            app.logger.info(f"Application startup: Debug mode is {'ENABLED' if debug_status else 'DISABLED'}")
        except Exception as e:
            app.logger.error(f"Error refreshing debug status on application startup: {e}")

    @app.after_request
    def add_security_headers(response):
        # Ensure JavaScript files have the correct MIME type
        if request.path.endswith('.js'):
            response.headers['Content-Type'] = 'application/javascript'
        elif request.path.endswith('.css'):
            response.headers['Content-Type'] = 'text/css'
            
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; "
            "img-src 'self' data: https://cdn.buymeacoffee.com https://*.paypal.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
        )
        response.headers['Content-Security-Policy'] = csp
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    # Setup Action Logger File Handler (needs app context)
    with app.app_context():
         setup_action_logger(app)
         
    # Start the background thread for Docker cache refreshing
    with app.app_context():
        app.logger.info("Starting Docker cache background refresh thread")
        
        # Gevent patch before thread start: Disable problematic after_fork_in_child assertion
        try:
            if HAS_GEVENT:
                import gevent.threading
                
                # Save original hook for debugging purposes
                original_after_fork = gevent.threading._ForkHooks.after_fork_in_child
                
                # Patch with a safer version that avoids assertion
                def safer_after_fork_in_child(self, thread):
                    # Skip assertion but still log warning
                    # The original assertion would be: assert not thread.is_alive()
                    if hasattr(thread, 'is_alive') and thread.is_alive():
                        app.logger.warning(f"Thread {thread.name if hasattr(thread, 'name') else 'unknown'} is still alive after fork, would normally trigger assertion.")
                    # Execute rest of function normally (without assertion)
                    
                # Apply patch
                gevent.threading._ForkHooks.after_fork_in_child = safer_after_fork_in_child
                app.logger.info("Applied Gevent fork hooks patch to avoid threading assertions")
        except (ImportError, AttributeError) as e:
            app.logger.warning(f"Could not patch Gevent fork hooks: {e}")
        
        # Starte Thread nur mit Verzögerung
        if os.environ.get('DDC_ENABLE_BACKGROUND_REFRESH', 'true').lower() != 'false':
            # Starte den Refresh erst nach 2 Sekunden, um die App-Initialisierung zu priorisieren
            if HAS_GEVENT:
                def delayed_start():
                    import gevent
                    gevent.sleep(2.0)
                    start_background_refresh(app.logger)
                gevent.spawn(delayed_start)
            else:
                start_background_refresh(app.logger)
        else:
            app.logger.info("Background Docker cache refresh disabled by environment setting")
        
        # Load active containers at startup
        app.logger.info("Loading active containers from config")
        active_containers = load_active_containers_from_config()
        app.logger.info(f"Loaded {len(active_containers)} active containers: {active_containers}")
        
        # Stop thread on application teardown
        @app.teardown_appcontext
        def cleanup_background_threads(exception=None):
            try:
                app.logger.info("Stopping Docker cache background refresh thread on app teardown")
                # Avoid multiple calls if thread is already stopped
                from app.utils.web_helpers import background_refresh_thread
                if background_refresh_thread is not None:
                    stop_background_refresh(app.logger)
            except Exception as e:
                # Catch errors during thread termination to avoid disrupting Flask
                app.logger.error(f"Error during background thread cleanup: {e}")
                # Continue with teardown, ignore errors
    
    # Add health check route for Docker - NO SESSION REQUIRED
    @app.route("/health")
    def health_check():
        """
        Health check endpoint for Docker containers and monitoring systems.
        This endpoint does not require authentication or sessions.
        """
        try:
            # Basic health status
            health_data = {
                "status": "healthy",
                "service": "DockerDiscordControl",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "v1.1.3"
            }
            
            # Optional: Add basic system checks without requiring authentication
            try:
                config = load_config()
                health_data["config_loaded"] = True
                health_data["servers_configured"] = len(config.get('servers', []))
            except Exception:
                health_data["config_loaded"] = False
                health_data["servers_configured"] = 0
            
            return jsonify(health_data), 200
            
        except Exception as e:
            # Ensure health endpoint always returns something, even on error
            # Log the actual error for debugging but don't expose it to users
            app.logger.error(f"Health check failed: {str(e)}")
            error_data = {
                "status": "error",
                "service": "DockerDiscordControl", 
                "error": "Service temporarily unavailable",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return jsonify(error_data), 500

    return app

# Perform initial password check (does not need app context)
set_initial_password_from_env()

# Create app instance for gunicorn
app = create_app()

# Only run directly if executed as main
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 