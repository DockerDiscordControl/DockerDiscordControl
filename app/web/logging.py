"""Logging configuration utilities for the web application."""

from __future__ import annotations

import logging


class ConsumePowerLogFilter(logging.Filter):
    """Filter chatty power consumption traces when not in debug mode."""

    def __init__(self, debug_mode: bool) -> None:
        super().__init__()
        self._debug_mode = debug_mode

    def filter(self, record: logging.LogRecord) -> bool:
        if self._debug_mode:
            return True

        message_sources = [
            record.getMessage() if hasattr(record, "getMessage") else "",
            getattr(record, "message", ""),
            str(record),
            str(getattr(record, "args", "")),
            str(getattr(record, "msg", "")),
        ]

        if any("consume-power" in source for source in message_sources) and record.levelno <= logging.INFO:
            return False
        return True


def configure_logging(app) -> ConsumePowerLogFilter:
    """Configure the Flask logger and install the noise filter across loggers."""
    log_level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    app.logger.setLevel(log_level)

    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(log_level)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]")
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)

    filter_instance = ConsumePowerLogFilter(debug_mode=log_level == logging.DEBUG)
    for logger_name in ["", "werkzeug", "gunicorn.access", "gunicorn.error", "flask.app", "app.blueprints.main_routes", "__main__"]:
        logging.getLogger(logger_name).addFilter(filter_instance)

    if filter_instance._debug_mode:
        app.logger.info("ConsumePowerLogFilter installed but DISABLED (DEBUG mode - showing all logs)")
    else:
        app.logger.info("ConsumePowerLogFilter installed and ACTIVE (INFO mode - filtering consume-power noise)")

    return filter_instance
