# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""CSRF-protection foundation for the Web UI.

Flask-WTF's :class:`CSRFProtect` middleware is wired up here, but every
blueprint is exempted by default. This provides the *infrastructure* (token
generation, ``csrf_token()`` template helper, X-CSRFToken header support)
without breaking the existing UI which does not yet attach tokens to its
POST requests.

Removing the per-blueprint ``@csrf.exempt`` is the follow-up work item: each
form template needs ``{{ csrf_token() }}`` and each AJAX call needs the
``X-CSRFToken`` header from the ``<meta name="csrf-token">`` tag in
``_base.html``.
"""

from __future__ import annotations

import logging

from flask import Flask

logger = logging.getLogger("app.web.csrf")


def install_csrf_protection(app: Flask) -> None:
    """Initialize Flask-WTF CSRFProtect with all current blueprints exempt."""
    try:
        from flask_wtf.csrf import CSRFProtect, generate_csrf
    except ImportError:
        # Flask-WTF not installed yet (older image): provide a no-op helper
        # so templates that reference ``csrf_token()`` still render.
        app.jinja_env.globals.setdefault("csrf_token", lambda: "")
        logger.warning("Flask-WTF not installed — CSRF protection disabled")
        return

    csrf = CSRFProtect()
    csrf.init_app(app)
    app.extensions["ddc_csrf"] = csrf
    app.jinja_env.globals.setdefault("csrf_token", generate_csrf)

    # Exempt every registered blueprint until the templates/AJAX layer is
    # updated to send the token. Removing this loop is the enforcement step.
    exempt_count = 0
    for name, blueprint in app.blueprints.items():
        try:
            csrf.exempt(blueprint)
            exempt_count += 1
        except (AttributeError, TypeError) as exc:
            logger.warning("Could not exempt blueprint %s: %s", name, exc)

    logger.info(
        "CSRF protection initialized: %d blueprint(s) exempt by default", exempt_count
    )
