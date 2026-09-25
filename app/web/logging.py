# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Logging configuration utilities for the web application."""

from __future__ import annotations

import logging
import re

# werkzeug's access line, e.g.
#   127.0.0.1 - - [25/Sep/2026 10:28:58] "GET /health HTTP/1.1" 200 -
# The path is matched to its end so that /health-history and /healthcheck-report
# - which are somebody asking a question, not the poll - are left alone.
_THE_HEALTH_POLL = re.compile(r'"GET /health(?:\?\S*)? HTTP/[\d.]+"\s+(\d{3})')


class HealthCheckLogFilter(logging.Filter):
    """Drop the access line for a health check that passed.

    Self-signed TLS cannot be served by waitress, so the panel runs on
    werkzeug's threaded server - and werkzeug logs an access line for every
    request where waitress logged none. With HEALTHCHECK --interval=30s in the
    Dockerfile that is about 2,880 identical lines a day, none of which says
    anything that was not already true.

    A health check that FAILS is kept, and is close to the most important line
    in the file: it is the moment before Docker restarts the container. So is
    every other request - somebody reaching the panel is worth knowing about.
    This drops the poll talking to itself, nothing else.
    """

    def __init__(self, debug_mode: bool) -> None:
        super().__init__()
        self._debug_mode = debug_mode

    def filter(self, record: logging.LogRecord) -> bool:
        if self._debug_mode:
            return True

        match = _THE_HEALTH_POLL.search(record.getMessage())
        if match is None:
            return True
        return not match.group(1).startswith("2")


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
    health_filter = HealthCheckLogFilter(debug_mode=log_level == logging.DEBUG)
    for logger_name in ["", "werkzeug", "gunicorn.access", "gunicorn.error", "flask.app", "app.blueprints.main_routes", "__main__"]:
        logging.getLogger(logger_name).addFilter(filter_instance)
        logging.getLogger(logger_name).addFilter(health_filter)

    if filter_instance._debug_mode:
        app.logger.info("ConsumePowerLogFilter installed but DISABLED (DEBUG mode - showing all logs)")
    else:
        app.logger.info("ConsumePowerLogFilter installed and ACTIVE (INFO mode - filtering consume-power noise)")

    return filter_instance
