# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Security related Flask hooks."""

from __future__ import annotations

import logging
import os
import time

from flask import Flask, Response, jsonify, request, session

# Idle session timeout: clear sessions inactive for longer than this many seconds.
# Configurable via DDC_SESSION_IDLE_TIMEOUT (defaults to 30 min).
try:
    _SESSION_IDLE_TIMEOUT_SECONDS = max(60, int(os.environ.get("DDC_SESSION_IDLE_TIMEOUT", "1800")))
except (TypeError, ValueError):
    _SESSION_IDLE_TIMEOUT_SECONDS = 1800

logger = logging.getLogger("ddc.web.security")

_IDLE_EXEMPT_PATHS = ("/static/", "/health", "/logout", "/login")


PROXY_SOCKET = "/run/ddc-proxy/docker.sock"
RAW_DOCKER_SOCKET = "/var/run/docker.sock"


def raw_docker_socket_open() -> bool:
    """True when DDC goes through the allowlist proxy AND could open the raw socket itself.

    Then the proxy binds nothing: a PGID equal to the socket's group, a socket
    of mode 666 on the host, or a socket group that is the proxy user's own
    (review 2026-09-27). The operator chose a loud warning over refusing to
    start, so the entrypoint logs it and the panel shows it for as long as it
    holds. Asked of the operating system, for the process that serves the page.
    """
    via_proxy = os.environ.get("DOCKER_HOST", "") == f"unix://{PROXY_SOCKET}"
    return (via_proxy and os.path.exists(RAW_DOCKER_SOCKET)
            and os.access(RAW_DOCKER_SOCKET, os.R_OK | os.W_OK))


def install_security_handlers(app: Flask) -> None:
    """Register before/after request handlers for security headers."""

    @app.context_processor
    def raw_socket_notice():
        from app.auth import session_user

        # Only for somebody logged in - it tells how this installation is weak.
        return {"raw_docker_socket_open": session_user() is not None and raw_docker_socket_open()}

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
            # Since the form login (2026-09-23) this timeout is real for a
            # form user: session.clear() drops the auth marker too, and the
            # next request lands on /login. It stays weaker for a browser that
            # logged in with HTTP Basic - still a fallback by operator
            # decision - because such a browser replays its credentials for
            # the same realm by itself, and no server can make it stop. With
            # 2FA on, both cases end at a fresh code. Saying otherwise would
            # be reporting a control that did not happen.
            logger.info("Session went idle after %ss; the session state was cleared",
                        _SESSION_IDLE_TIMEOUT_SECONDS)
            response = jsonify({
                "error": "session_idle_timeout",
                "message": ("This session was idle for too long and its state was "
                            "cleared. The next page asks you to log in again; a "
                            "browser that was logged in with HTTP Basic may send "
                            "its stored credentials by itself."),
            })
            response.status_code = 401
            response.headers["WWW-Authenticate"] = 'Basic realm="DDC"'
            return response
        session["last_activity"] = now
        return None

    @app.after_request
    def one_answer_per_response(response: Response) -> Response:
        """A redirect is a whole instruction; it must not also be a challenge.

        flask_httpauth puts WWW-Authenticate on whatever its error handler
        returns unless the header is already there (HTTPAuth.error_handler),
        and DDC's handler answers a browser with a redirect to the login form.
        So the response said two different things - "go to the form" and "send
        me HTTP Basic" - and a browser that holds credentials for this host
        takes the second every time and never sees the form.

        THAT IS A LOGOUT, a few clicks later. Credentials given to a challenge
        are replayed only for paths at or below the one that asked, so a
        challenge sent from /security/2fa leaves the browser logged in there
        and nowhere else: the operator answered it on the second-factor page
        and was at the login form again the moment he clicked back to "/"
        (26/Sep 00:13, his own log).

        A 401 keeps its challenge - there it IS the answer, and a script has
        nothing else to go on. Only 3xx loses it.
        """
        if 300 <= response.status_code < 400:
            response.headers.pop("WWW-Authenticate", None)
        return response

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
