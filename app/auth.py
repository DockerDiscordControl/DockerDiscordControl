# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import current_app, jsonify, request
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash
from services.config.config_service import load_config
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import threading
import time
import discord

auth = HTTPBasicAuth()

# --- Verified-credential cache -------------------------------------------------------------
#
# HTTP Basic Auth sends the credentials with EVERY request, so verify_password() ran the full
# key derivation every time: measured in the production container, 85.6 ms per check, while an
# unauthenticated request (/health) takes 2.2 ms. 70 routes carry @auth.login_required, so the
# panel paid ~85 ms before doing any actual work.
#
# What this cache does NOT do: it does not lower the iteration count (still 600,000) and it does
# not help an attacker. Only a credential that has ALREADY been verified is stored, so a wrong
# password never finds an entry and keeps paying the full 85.6 ms - brute-force cost is
# unchanged.
#
# The stored password hash is part of the cache key. Changing the Web UI password produces a new
# hash, which makes every existing entry unreachable immediately - without relying on some
# invalidation hook being called from both write paths (ConfigService.change_web_ui_password()
# and /setup). That matters here because the bot token's encryption key is derived from this
# same hash.
#
# The password itself is never kept: entries are keyed by an HMAC over (user, password, hash)
# under a key that is random per process and never persisted.
_CREDENTIAL_CACHE_TTL_SECONDS = 60.0
_CREDENTIAL_CACHE_MAX_ENTRIES = 32
_credential_cache = {}
_credential_cache_lock = threading.Lock()
_credential_cache_key = os.urandom(32)


def _credential_fingerprint(username, password, stored_hash):
    """HMAC over the three parts, length-prefixed so ("ab","c") and ("a","bc") differ."""
    mac = hmac.new(_credential_cache_key, digestmod=hashlib.sha256)
    for part in (username, password, stored_hash):
        encoded = part.encode("utf-8")
        mac.update(len(encoded).to_bytes(4, "big"))
        mac.update(encoded)
    return mac.digest()


def _cached_credential_is_valid(fingerprint):
    now = time.monotonic()
    with _credential_cache_lock:
        expires_at = _credential_cache.get(fingerprint)
        if expires_at is None:
            return False
        if expires_at <= now:
            _credential_cache.pop(fingerprint, None)
            return False
        return True


def _remember_verified_credential(fingerprint):
    now = time.monotonic()
    with _credential_cache_lock:
        for key, expires_at in list(_credential_cache.items()):
            if expires_at <= now:
                del _credential_cache[key]
        # Bounded: an attacker guessing usernames must not be able to grow this without limit.
        if len(_credential_cache) >= _CREDENTIAL_CACHE_MAX_ENTRIES:
            oldest = min(_credential_cache, key=_credential_cache.get)
            del _credential_cache[oldest]
        _credential_cache[fingerprint] = now + _CREDENTIAL_CACHE_TTL_SECONDS


def clear_credential_cache():
    """Drop all cached verifications (used by the tests; safe to call at any time)."""
    with _credential_cache_lock:
        _credential_cache.clear()


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

# Stricter limiter for the first-time-setup endpoint. While no password is
# configured, /setup accepts admin/setup as a bootstrap credential — without
# this limit an attacker could brute-force the bootstrap window.
setup_limiter = SimpleRateLimiter(limit=5, per_seconds=60)


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

        client_ip = request.remote_addr

        # Setup endpoint gets its own tight limit (5 req/min) — applies to GET
        # and POST regardless of Authorization header so unauthenticated probes
        # are also throttled.
        if request.path.startswith('/setup'):
            if setup_limiter.is_rate_limited(client_ip):
                app.logger.warning(f"Setup rate limit exceeded from IP: {client_ip}")
                return jsonify(error="Too many setup attempts. Please try again later."), 429
            return None

        # General auth-rate-limit for everything that ships an Authorization header.
        if 'Authorization' in request.headers:
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
    elif username == stored_user:
        if isinstance(password, str) and isinstance(stored_hash, str):
            fingerprint = _credential_fingerprint(username, password, stored_hash)
            if _cached_credential_is_valid(fingerprint):
                return username
            if check_password_hash(stored_hash, password):
                _remember_verified_credential(fingerprint)
                return username
        elif check_password_hash(stored_hash, password):
            # Non-string input (should not happen via flask_httpauth) - verify, but never cache.
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
                "message": "First Time Setup Required",
                "error": "No admin password configured yet",
                "setup_url": "/setup"
            }), 401
    except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        pass  # Continue with normal auth error

    return jsonify(message="Authentication Required"), status
