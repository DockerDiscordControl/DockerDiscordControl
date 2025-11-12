"""Security related Flask hooks."""

from __future__ import annotations

from flask import Flask, Response, request, session


def install_security_handlers(app: Flask) -> None:
    """Register before/after request handlers for security headers."""

    @app.before_request
    def enforce_session_security():
        session.permanent = True
        if request.is_secure:
            app.config["SESSION_COOKIE_SECURE"] = True

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
