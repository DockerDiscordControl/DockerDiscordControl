# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Background service orchestration for the web app."""

from __future__ import annotations

import atexit
import os

from flask import Flask

from app.utils.shared_data import load_active_containers_from_config
from app.utils.web_helpers import (
    start_background_refresh,
    start_mech_decay_background,
    stop_background_refresh,
    stop_mech_decay_background,
)

from .compat import HAS_GEVENT, apply_gevent_fork_workaround, spawn_delayed

# The stop hook is process-wide; create_app() can run more than once (tests), so register it once.
_shutdown_hook_registered = False


def _is_enabled(var_name: str) -> bool:
    return os.environ.get(var_name, "true").lower() != "false"


def _stop_background_threads(logger) -> None:
    """Stop the background helpers when the process shuts down."""
    try:
        logger.debug("Stopping background threads on shutdown")

        from app.utils.web_helpers import background_refresh_thread, mech_decay_thread

        if background_refresh_thread is not None:
            stop_background_refresh(logger)

        if mech_decay_thread is not None:
            stop_mech_decay_background(logger)
    except (IOError, OSError, PermissionError, RuntimeError) as e:
        logger.error("Error during background thread cleanup: %s", e, exc_info=True)


def register_background_services(app: Flask) -> None:
    """Start background helpers and register the shutdown hook that stops them."""
    global _shutdown_hook_registered

    apply_gevent_fork_workaround(app.logger)

    with app.app_context():
        app.logger.info("Starting Docker cache background refresh thread")

        if _is_enabled("DDC_ENABLE_BACKGROUND_REFRESH"):
            if HAS_GEVENT:
                spawn_delayed(2.0, start_background_refresh, app.logger)
            else:
                start_background_refresh(app.logger)
        else:
            app.logger.info("Background Docker cache refresh disabled by environment setting")

        app.logger.info("Loading active containers from config")
        active_containers = load_active_containers_from_config()
        app.logger.info("Loaded %d active containers: %s", len(active_containers), active_containers)

        if _is_enabled("DDC_ENABLE_MECH_DECAY"):
            if HAS_GEVENT:
                spawn_delayed(2.0, start_mech_decay_background, app.logger)
            else:
                start_mech_decay_background(app.logger)
        else:
            app.logger.info("Mech decay background task disabled by environment setting")

    # Stop the threads only on real shutdown. This used to be a teardown_appcontext hook,
    # which Flask runs after EVERY request: it killed the mech decay worker for good and
    # made each page load restart the Docker cache thread.
    if not _shutdown_hook_registered:
        atexit.register(_stop_background_threads, app.logger)
        _shutdown_hook_registered = True
