# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from __future__ import annotations

import os

from app.web.config import build_config, resolve_secret_key


def test_resolve_secret_key_generates_secure_default(monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    key = resolve_secret_key(os.environ)
    assert len(key) == 64
    assert key != "fallback-secret-key-for-dev-if-not-set"


def test_build_config_respects_overrides(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    config = build_config(os.environ, {"CUSTOM": "VALUE"})

    assert config["LOG_LEVEL"] == "DEBUG"
    assert config["CUSTOM"] == "VALUE"
    assert config["SECRET_KEY"]
    # config.json in the config directory - DDC_CONFIG_DIR when set (tests/conftest.py
    # sets it). This used to assert ".../config/config.json", pinning a value that
    # ignored the variable; see utils/config_paths.py.
    assert config["CONFIG_FILE"] == os.path.join(os.environ["DDC_CONFIG_DIR"], "config.json")
