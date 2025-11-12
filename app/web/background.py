"""Background service orchestration for the web app."""

from __future__ import annotations

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


def _is_enabled(var_name: str) -> bool:
    return os.environ.get(var_name, "true").lower() != "false"


def register_background_services(app: Flask) -> None:
    """Start background helpers and register teardown hooks."""
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

        @app.teardown_appcontext
        def cleanup_background_threads(exception=None):  # type: ignore[override]
            try:
                app.logger.debug("Stopping background threads on app teardown")

                from app.utils.web_helpers import background_refresh_thread, mech_decay_thread

                if background_refresh_thread is not None:
                    stop_background_refresh(app.logger)

                if mech_decay_thread is not None:
                    stop_mech_decay_background(app.logger)
            except Exception as exc:  # pragma: no cover - defensive logging
                app.logger.error("Error during background thread cleanup: %s", exc)
