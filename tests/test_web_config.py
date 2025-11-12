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
    assert config["CONFIG_FILE"].endswith(os.path.join("config", "config.json"))
