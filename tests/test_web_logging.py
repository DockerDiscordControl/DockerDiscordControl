# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from __future__ import annotations

import logging

from flask import Flask

from app.web.logging import ConsumePowerLogFilter, configure_logging


def test_consume_power_filter_respects_debug_state():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="consume-power event",
        args=(),
        exc_info=None,
    )

    assert not ConsumePowerLogFilter(debug_mode=False).filter(record)
    assert ConsumePowerLogFilter(debug_mode=True).filter(record)


def test_configure_logging_installs_stream_handler():
    app = Flask(__name__)
    app.config["LOG_LEVEL"] = "INFO"

    filter_instance = configure_logging(app)

    assert isinstance(filter_instance, ConsumePowerLogFilter)
    assert any(isinstance(handler, logging.StreamHandler) for handler in app.logger.handlers)
