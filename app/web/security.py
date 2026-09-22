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

    # Version shown in the page footer (_base.html). DDC_VERSION is set by the Dockerfile;
    # without it (dev checkout) the footer shows no version.
    version = (os.environ.get("DDC_VERSION") or "").strip().lstrip("vV")
    app.jinja_env.globals.setdefault("ddc_version", f"v{version}" if version else "")

    @app.before_request
    def enforce_session_security():
        # No per-request change of app.config["SESSION_COOKIE_SECURE"] here: app.config is
        # global, so the first HTTPS request would switch it on for every later plain-HTTP
        # client too, whose browser then drops the cookie and every save fails the CSRF check.
        session.permanent = True

        if any(request.path == p or request.path.startswith(p) for p in _IDLE_EXEMPT_PATHS):
            return None

        now = time.time()
        last_activity = session.get("last_activity")
        if last_activity is not None and (now - last_activity) > _SESSION_IDLE_TIMEOUT_SECONDS:
            # Keep the CSRF token: the open page still carries it in its meta tag, and
            # dropping it would make every save fail until the page is reloaded.
            csrf_token = session.get("csrf_token")
            session.clear()
            if csrf_token:
                session["csrf_token"] = csrf_token
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
