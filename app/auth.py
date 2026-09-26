# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import current_app, jsonify, redirect, request, session, url_for
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

# The session key that carries a finished form login, and what it holds.
#
# Not a flag: the value is a BINDING to the stored password hash, the same way
# the second factor binds its own marker (app/blueprints/two_factor_routes.py).
# A flag would outlive a password change - the one moment every session has to
# end - and a cookie is client-side, so "any truthy value" would be a hole.
SESSION_AUTH_KEY = "web_authenticated"


def password_binding():
    """sha256 of the stored password hash, or None when none is configured.

    None means no session can be valid: on a fresh install, or when config/
    could not be read, the panel is not open to anybody holding a cookie.
    """
    stored = (load_config() or {}).get("web_ui_password_hash")
    if not stored:
        return None
    return hashlib.sha256(stored.encode()).hexdigest()[:24]


def session_user():
    """The user this session is logged in as, or None.

    Outside a request context there is no session, and asking for one raises;
    an auth check that cannot see a session simply has none.
    """
    try:
        marker = session.get(SESSION_AUTH_KEY)
    except RuntimeError:
        return None
    if not marker:
        return None
    binding = password_binding()
    if binding is None or not hmac.compare_digest(str(marker), binding):
        return None
    return (load_config() or {}).get("web_ui_user", "admin")


class SessionOrBasicAuth(HTTPBasicAuth):
    """HTTP Basic, plus a finished form login.

    login_required() calls authenticate() and nothing else, so this one method
    is the whole hook: all 75 @auth.login_required decorators stay as they are
    and current_user() goes on working. Basic stays as the fallback (operator
    decision 2026-09-23) so curl, scripts and the Unraid integrations that pass
    -u admin:... keep working.
    """

    def authenticate(self, auth, stored_password):
        user = session_user()
        if user is not None:
            return user
        return super().authenticate(auth, stored_password)


auth = SessionOrBasicAuth()

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

# Second-factor codes (v3.0): six digits and three valid codes per window mean
# ~330,000 guesses on average for whoever already has the password - braked
# like the setup bootstrap, 5 attempts per minute and address.
two_factor_limiter = SimpleRateLimiter(limit=5, per_seconds=60)


def init_limiter(app):
    """Initializes rate limiting for login attempts"""
    @app.before_request
    def check_auth_rate_limit():
        # Exclude static resources from rate limiting
        if request.path.startswith('/static/'):
            return None

        # Exclude status endpoints from rate limiting (they need frequent access).
        # /health only while it carries no credentials: the container probe sends
        # none, but a caller with Basic auth gets the detailed answer only for the
        # right password - until 2026-09-26 that made /health an unbraked way to
        # test passwords. With an Authorization header it falls through to the
        # auth limit below, like every other route.
        if request.path.startswith('/api/donation/status'):
            return None
        if request.path.startswith('/health') and 'Authorization' not in request.headers:
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

def setup_is_closed(config):
    """Why first-time setup may not run now - or None if it may. A missing hash
    means EITHER a fresh install or a config that could not be read; auth.py
    refuses the first-run LOGIN then, and these routes WRITE the password."""
    read_errors = config.get('config_read_errors')
    if read_errors:
        current_app.logger.error(
            "SECURITY: /setup asked while the configuration could not be read (%s) - a read "
            "error, not a fresh install. Check the permissions on config/ (user 'ddc').",
            "; ".join(str(error) for error in read_errors))
        return 'The configuration could not be read; see the DDC log. Setup stays closed.'
    if config.get('web_ui_password_hash') is not None:
        return 'Setup is not allowed when password is already configured'
    return None


@auth.verify_password
def verify_password(username, password):
    logger = current_app.logger
    config = load_config()
    stored_user = config.get('web_ui_user', "admin")
    stored_hash = config.get('web_ui_password_hash')

    if stored_hash is None:
        # A missing hash has TWO causes, and they look the same: a fresh
        # installation - or a configuration that could not be read.
        # _load_json_file returns the default in both cases
        # (config_service.py:710-727). In the second case admin/setup would be
        # open on a long-established installation, behind the 70 routes with
        # @auth.login_required - and nobody notices, because the login works.
        # The write path is already defended against exactly this loss
        # (config_service.py:385-386); the read path was not.
        read_errors = config.get('config_read_errors')
        if read_errors:
            logger.error(
                "SECURITY: The configuration could not be read (%s). That is a read "
                "error, not a fresh install - the admin/setup first-time login stays "
                "closed. Check the permissions on config/ (the app runs as user 'ddc').",
                "; ".join(str(e) for e in read_errors)
            )
            return None

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

def _wants_json():
    """Same split the second factor uses, and for the same reason."""
    return (request.is_json or request.path.startswith("/api/")
            or request.accept_mimetypes.best == "application/json")


@auth.error_handler
def auth_error(status):
    """Enhanced auth error handler with Unraid-friendly setup instructions."""
    from services.config.config_service import load_config

    # Check if this is a first-time setup issue
    try:
        config = load_config()
        if config.get('web_ui_password_hash') is None:
            if config.get('config_read_errors'):
                # The configuration exists but cannot be parsed. Sending the
                # operator to /setup now would be a dead end - nothing can be done
                # there while config/ is unreadable. Since verify_password closes
                # this case, this message is the only hint the operator gets; it
                # must name the real reason.
                return jsonify({
                    "message": "Configuration Unreadable",
                    "error": "A configuration file exists, but it could not be read",
                    "hint": "Check the permissions on config/ - the application runs as user 'ddc'"
                }), 401
            return jsonify({
                "message": "First Time Setup Required",
                "error": "No admin password configured yet",
                "setup_url": "/setup"
            }), 401
    except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        pass  # Continue with normal auth error

    # A browser gets the form; a fetch() gets the 401 it can read. Answering a
    # fetch with a redirect to an HTML page makes it fail on something
    # unrelated - the panel would report a parse error for a login problem.
    if not _wants_json():
        return redirect(url_for("login.login_page", next=request.full_path.rstrip("?")))
    return jsonify(message="Authentication Required"), status
