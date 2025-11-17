# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Helpers for verifying the action logger configuration."""

from __future__ import annotations

from flask import Flask

from app.utils.web_helpers import setup_action_logger


def ensure_action_logger(app: Flask) -> None:
    """Verify the action logger wiring within an application context."""
    with app.app_context():
        setup_action_logger(app)
