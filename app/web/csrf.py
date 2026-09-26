# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""CSRF protection for the Web UI.

Flask-WTF's :class:`CSRFProtect` validates every state-changing request
(POST/PUT/PATCH/DELETE) on every route. The Web UI authenticates with HTTP
Basic auth, which the browser attaches automatically - so without this check
any web page could make the admin's browser change the configuration.

The client side lives in ``_base.html``: it reads the token from
``<meta name="csrf-token">``, adds the ``X-CSRFToken`` header to same-origin
``fetch()`` calls and a hidden ``csrf_token`` field to POST forms. Pages that
do not extend ``_base.html`` (``setup.html``) embed the token themselves.

One route is exempt, and only one: ``POST /security/2fa/disable``, the way out
of the second factor (app/blueprints/two_factor_routes.py). Over plain HTTP
with 2FA on, no page can hand out a token, and the request carries its own
proof against forgery - a current code no other site can know. Everything else
needs the token: nothing outside the browser UI posts to the web server (the
bot talks to the services directly, not over HTTP).
"""

from __future__ import annotations
from utils.logging_utils import get_module_logger

import logging
from html import escape

from flask import Flask, jsonify, request

logger = get_module_logger('csrf')

CSRF_ERROR_MESSAGE = "Session expired - please reload the page and try again."

# Flask-WTF's error descriptions -> machine-readable ``reason`` in the JSON response. The
# client turns it into a translated text (ddcServerErrorMessage() in _base.html).
_CSRF_REASONS = {
    "The CSRF token is missing.": "missing",
    "The CSRF session token is missing.": "session_missing",
    "The CSRF token has expired.": "expired",
    "The CSRF token is invalid.": "invalid",
    "The CSRF tokens do not match.": "invalid",
}
# English text per reason, for API clients and the HTML error page
_CSRF_REASON_TEXTS = {
    "missing": "The request carried no security token, so nothing was saved.",
    "session_missing": "Your browser did not send the DDC session cookie, so nothing was saved.",
    "expired": "Your session has expired, so nothing was saved.",
    "invalid": "The page's security token does not match your session, so nothing was saved.",
}
_CSRF_HINT = ("Reload the page and try again. If this keeps happening, another web app on the "
              "same host may be overwriting the session cookie, or the browser blocks cookies "
              "for this site.")


def csrf_error_reason(description) -> str:
    """Map a CSRFError description to missing / session_missing / expired / invalid."""
    return _CSRF_REASONS.get(str(description or ""), "invalid")


def _is_browser_navigation() -> bool:
    """True for a native form submit / page load, False for fetch()/XHR/API calls."""
    fetch_mode = request.headers.get("Sec-Fetch-Mode", "").lower()
    if fetch_mode:
        return fetch_mode == "navigate"
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return False
    return "text/html" in request.headers.get("Accept", "")


def _handle_csrf_error(error):
    """Explain a rejected token instead of Werkzeug's generic 400 page."""
    description = getattr(error, "description", error)
    reason = csrf_error_reason(description)
    message = f"{_CSRF_REASON_TEXTS[reason]} {_CSRF_HINT}"
    logger.warning(
        "CSRF validation failed for %s %s: %s (reason=%s)",
        request.method, request.path, description, reason,
    )
    if not _is_browser_navigation():
        # ``reason`` lets the UI show a translated text; ``error``/``message`` stay English
        # for other clients.
        response = jsonify({
            "success": False,
            "error": message,
            "message": message,
            "csrf_error": True,
            "reason": reason,
        })
        response.status_code = 400
        return response

    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Session expired</title></head>"
        "<body style=\"font-family: sans-serif; background: #030603; color: #fff; padding: 2rem;\">"
        f"<h1>Session expired</h1><p>{escape(message)}</p>"
        "<p><a href=\"/\" style=\"color: #61dafb;\">Back to the configuration</a></p>"
        "</body></html>"
    )
    return body, 400, {"Content-Type": "text/html; charset=utf-8"}


def install_csrf_protection(app: Flask) -> None:
    """Initialize Flask-WTF CSRFProtect for all routes and register its error handler."""
    try:
        from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
    except ImportError:
        # Flask-WTF not installed yet (older image): provide a no-op helper
        # so templates that reference ``csrf_token()`` still render.
        app.jinja_env.globals.setdefault("csrf_token", lambda: "")
        # A security control must never degrade quietly: Flask-WTF is pinned in both
        # requirements files, so reaching this means a broken image or install (V2 review B6).
        logger.critical("Flask-WTF is not installed — CSRF protection is DISABLED for every "
                        "route. Reinstall the dependencies (requirements.prod.txt) before "
                        "exposing this instance.")
        return

    csrf = CSRFProtect()
    csrf.init_app(app)
    app.extensions["ddc_csrf"] = csrf
    app.jinja_env.globals.setdefault("csrf_token", generate_csrf)
    app.register_error_handler(CSRFError, _handle_csrf_error)

    logger.info("CSRF protection initialized for all routes")
