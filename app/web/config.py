# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Configuration helpers for the Flask web application."""

from __future__ import annotations

import os
import secrets
from datetime import timedelta
from typing import Mapping, MutableMapping, Optional

DEFAULTS = {
    "SESSION_COOKIE_SECURE": False,
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SAMESITE": "Lax",
    "PERMANENT_SESSION_LIFETIME": timedelta(days=30),
    "SESSION_REFRESH_EACH_REQUEST": True,
    "JSON_AS_ASCII": False,
    "DOCKER_SOCKET": "/var/run/docker.sock",
    "LOG_LEVEL": "INFO",
    "HOST_DOCKER_PATH": "/usr/bin/docker",
    "TEMPLATES_AUTO_RELOAD": True,
}


def resolve_secret_key(env: Mapping[str, str]) -> str:
    """Return a robust Flask secret key, generating one when absent."""
    candidate = env.get("FLASK_SECRET_KEY", "").strip()
    if not candidate or candidate == "fallback-secret-key-for-dev-if-not-set":
        return secrets.token_hex(32)
    return candidate


from pathlib import Path

def build_config(env: Mapping[str, str], overrides: Optional[Mapping[str, object]] = None) -> MutableMapping[str, object]:
    """Construct the Flask configuration dictionary."""
    config: MutableMapping[str, object] = dict(DEFAULTS)
    # Robust absolute path relative to project root
    try:
        project_root = Path(__file__).parents[2]
    except Exception:
        project_root = Path(".")
        
    config.update(
        SECRET_KEY=resolve_secret_key(env),
        DOCKER_SOCKET=env.get("DOCKER_SOCKET", DEFAULTS["DOCKER_SOCKET"]),
        LOG_LEVEL=env.get("LOG_LEVEL", DEFAULTS["LOG_LEVEL"]),
        HOST_DOCKER_PATH=env.get("HOST_DOCKER_PATH", DEFAULTS["HOST_DOCKER_PATH"]),
        CONFIG_FILE=str(project_root / "config" / "config.json"),
    )

    if overrides:
        config.update(overrides)

    return config
