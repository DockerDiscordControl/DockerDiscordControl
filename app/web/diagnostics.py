"""Startup diagnostics for the web application."""

from __future__ import annotations

from flask import Flask

from app.utils.port_diagnostics import log_port_diagnostics


def run_startup_diagnostics(app: Flask) -> None:
    """Refresh debug status and execute port diagnostics inside the app context."""
    with app.app_context():
        try:
            from utils.logging_utils import refresh_debug_status

            debug_status = refresh_debug_status()
            app.logger.info("Application startup: Debug mode is %s", "ENABLED" if debug_status else "DISABLED")
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
            app.logger.error("Error refreshing debug status on application startup: %s", exc, exc_info=True)

        try:
            app.logger.info("Running port diagnostics...")
            log_port_diagnostics()
        except (RuntimeError) as e:
            app.logger.error("Error running port diagnostics: %s", exc, exc_info=True)
