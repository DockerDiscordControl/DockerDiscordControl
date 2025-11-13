# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import current_app, jsonify, request
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash
from services.config.config_service import load_config
from datetime import datetime, timedelta, timezone
import threading

auth = HTTPBasicAuth()

# Simple internal rate limiter implementation
class SimpleRateLimiter:
    def __init__(self, limit=5, per_seconds=60):
        self.limit = limit
        self.window = per_seconds
        self.ip_dict = {}
        self.lock = threading.Lock()
    
    def is_rate_limited(self, ip):
        """Checks if an IP has exceeded the rate limit"""
        now = datetime.now(timezone.utc)
        with self.lock:
            # Delete old entries
            self.cleanup_old_entries(now)
            
            # Initialize if IP is not in dict
            if ip not in self.ip_dict:
                self.ip_dict[ip] = []
            
            # Count the number of requests in the last period
            count = len(self.ip_dict[ip])
            
            # If the limit is already reached, reject
            if count >= self.limit:
                return True
            
            # Otherwise add request and allow
            self.ip_dict[ip].append(now)
            return False
    
    def cleanup_old_entries(self, now):
        """Removes old entries from the rate limiter"""
        cutoff = now - timedelta(seconds=self.window)
        for ip in list(self.ip_dict.keys()):
            # Only keep timestamps that are within the window
            self.ip_dict[ip] = [ts for ts in self.ip_dict[ip] if ts > cutoff]
            # Remove empty lists
            if not self.ip_dict[ip]:
                del self.ip_dict[ip]

# Global rate limiter - reasonable for normal usage
auth_limiter = SimpleRateLimiter(limit=100, per_seconds=60)  # 100 requests per minute

def init_limiter(app):
    """Initializes rate limiting for login attempts"""
    @app.before_request
    def check_auth_rate_limit():
        # Exclude static resources from rate limiting
        if request.path.startswith('/static/'):
            return None
            
        # Exclude status endpoints from rate limiting (they need frequent access)
        if request.path.startswith('/api/donation/status') or request.path.startswith('/health'):
            return None
            
        # Only limit authentication requests (but allow setup page)
        if 'Authorization' in request.headers and not request.path.startswith('/setup'):
            client_ip = request.remote_addr
            if auth_limiter.is_rate_limited(client_ip):
                app.logger.warning(f"Rate limit exceeded for auth from IP: {client_ip}")
                return jsonify(error="Too many login attempts. Please try again later."), 429

@auth.verify_password
def verify_password(username, password):
    logger = current_app.logger
    config = load_config()
    stored_user = config.get('web_ui_user', "admin") 
    stored_hash = config.get('web_ui_password_hash')
    
    if stored_hash is None:
        # FIRST TIME SETUP: Allow special setup password for initial configuration
        if username == "admin" and password == "setup":
            logger.info("FIRST TIME SETUP: Setup mode activated with temporary credentials")
            # Set a flag that this is setup mode
            from flask import session
            session['setup_mode'] = True
            return username
        
        # SECURITY FIX: Never fall back to default credentials for normal access
        logger.error("SECURITY: No password hash configured - authentication disabled for safety")
        logger.error("FIRST TIME SETUP: Use admin/setup to access setup page, then set your password")
        return None  # Fail securely - no authentication possible without configured password
    elif username == stored_user and check_password_hash(stored_hash, password):
        return username 
    logger.warning(f"Failed login attempt for user: {username}")
    return None

@auth.error_handler
def auth_error(status):
    """Enhanced auth error handler with Unraid-friendly setup instructions."""
    from services.config.config_service import load_config
    
    # Check if this is a first-time setup issue
    try:
        config = load_config()
        if config.get('web_ui_password_hash') is None:
            return jsonify({
                "message": "🚀 First Time Setup Required - DockerDiscordControl",
                "error": "No admin password configured yet",
                "setup_options": {
                    "easy_setup": {
                        "description": "🎯 RECOMMENDED: Web-based setup",
                        "action": "Visit /setup in your browser for easy configuration",
                        "url": "/setup"
                    },
                    "temp_credentials": {
                        "description": "🔑 Or use temporary credentials",
                        "username": "admin",
                        "password": "setup",
                        "note": "Works only for first-time setup"
                    },
                    "advanced": {
                        "description": "⚙️ Environment variable method",
                        "method": "Set DDC_ADMIN_PASSWORD environment variable and restart"
                    }
                }
            }), 401
    except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        pass  # Continue with normal auth error
    
    return jsonify(message="Authentication Required"), status 