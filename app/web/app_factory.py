"""Application factory orchestration for the Flask web UI."""

from __future__ import annotations

import logging
import os
from typing import Mapping, Optional

from flask import Flask

from .action_logger import ensure_action_logger
from .background import register_background_services
from .blueprints import register_blueprints
from .compat import initialize_gevent
from .config import build_config
from .diagnostics import run_startup_diagnostics
from .extensions import configure_proxy, init_rate_limiting
from .logging import configure_logging
from .routes import register_routes
from .security import install_security_handlers


def create_app(test_config: Optional[Mapping[str, object]] = None) -> Flask:
    """Create and configure the Flask application instance."""
    bootstrap_logger = logging.getLogger("app.web.bootstrap")
    initialize_gevent(bootstrap_logger)

    app = Flask(__name__)
    config = build_config(os.environ, test_config)
    app.config.update(config)

    configure_logging(app)
    initialize_gevent(app.logger)

    configure_proxy(app)
    init_rate_limiting(app)
    register_blueprints(app)
    install_security_handlers(app)
    run_startup_diagnostics(app)
    ensure_action_logger(app)
    register_background_services(app)
    register_routes(app)

    return app
