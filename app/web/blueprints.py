"""Blueprint registration helpers."""

from __future__ import annotations

from flask import Flask

from app.blueprints.action_log_routes import action_log_bp
from app.blueprints.log_routes import log_bp
from app.blueprints.main_routes import main_bp
from app.blueprints.security_routes import security_bp
from app.blueprints.tasks_bp import tasks_bp


def register_blueprints(app: Flask) -> None:
    """Attach all blueprints with their configured prefixes."""
    app.register_blueprint(main_bp)
    app.register_blueprint(log_bp, url_prefix="/logs_bp")
    app.register_blueprint(action_log_bp, url_prefix="/action_log_bp")
    app.register_blueprint(tasks_bp)
    app.register_blueprint(security_bp)
