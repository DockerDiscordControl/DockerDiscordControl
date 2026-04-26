# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Security related Flask hooks."""

from __future__ import annotations

import os
import time

from flask import Flask, Response, jsonify, request, session

# Idle session timeout: clear sessions inactive for longer than this many seconds.
# Configurable via DDC_SESSION_IDLE_TIMEOUT (defaults to 30 min).
try:
    _SESSION_IDLE_TIMEOUT_SECONDS = max(60, int(os.environ.get("DDC_SESSION_IDLE_TIMEOUT", "1800")))
except (TypeError, ValueError):
    _SESSION_IDLE_TIMEOUT_SECONDS = 1800

_IDLE_EXEMPT_PATHS = ("/static/", "/health", "/logout")


def install_security_handlers(app: Flask) -> None:
    """Register before/after request handlers for security headers."""

    @app.before_request
    def enforce_session_security():
        session.permanent = True
        if request.is_secure:
            app.config["SESSION_COOKIE_SECURE"] = True

        if any(request.path == p or request.path.startswith(p) for p in _IDLE_EXEMPT_PATHS):
            return None

        now = time.time()
        last_activity = session.get("last_activity")
        if last_activity is not None and (now - last_activity) > _SESSION_IDLE_TIMEOUT_SECONDS:
            session.clear()
            response = jsonify({
                "error": "session_idle_timeout",
                "message": "Session expired due to inactivity. Please re-authenticate.",
            })
            response.status_code = 401
            response.headers["WWW-Authenticate"] = 'Basic realm="DDC"'
            return response
        session["last_activity"] = now
        return None

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        if request.path.endswith(".js"):
            response.headers["Content-Type"] = "application/javascript"
        elif request.path.endswith(".css"):
            response.headers["Content-Type"] = "text/css"

        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; "
            "img-src 'self' data: blob: https://cdn.buymeacoffee.com https://*.paypal.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
        )
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
