# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup diagnostics for the web application."""

from __future__ import annotations

from flask import Flask


def run_startup_diagnostics(app: Flask) -> None:
    """Refresh debug status inside the app context.

    Note: Port diagnostics are intentionally NOT run here because the web
    server (Waitress) has not started listening yet at this point.  The port
    check is performed later during the Discord bot startup step
    (app/bot/startup_steps/diagnostics.py) when the web server is already up.
    """
    with app.app_context():
        try:
            from utils.logging_utils import refresh_debug_status

            debug_status = refresh_debug_status()
            app.logger.info("Application startup: Debug mode is %s", "ENABLED" if debug_status else "DISABLED")
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
            app.logger.error("Error refreshing debug status on application startup: %s", e, exc_info=True)
