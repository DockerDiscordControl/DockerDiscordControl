# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Extension initialisation for the web app."""

from __future__ import annotations

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth import init_limiter


def configure_proxy(app: Flask) -> None:
    """Wrap the WSGI app with :class:`ProxyFix` for reverse proxy deployments."""
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)  # type: ignore[assignment]


def init_rate_limiting(app: Flask) -> None:
    """Initialise the authentication rate limiter."""
    init_limiter(app)
    app.logger.info("Rate limiting initialized for authentication")
