# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import json
from pathlib import Path

import pytest

from services.mech.progress import get_progress_runtime, reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache


@pytest.fixture(autouse=True)
def reset_runtime_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    yield
    reset_progress_runtime()
    clear_progress_paths_cache()
    monkeypatch.delenv("DDC_PROGRESS_DATA_DIR", raising=False)


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_runtime_seeds_default_configuration(tmp_path):
    runtime = get_progress_runtime()
    default_cfg = {"timezone": "UTC", "example": 1}

    runtime.configure_defaults(default_cfg)

    config_path = runtime.paths.config_file
    assert config_path.exists(), "Config file should be created automatically"
    assert _read_config(config_path) == default_cfg


def test_runtime_recovers_from_invalid_json(tmp_path):
    runtime = get_progress_runtime()
    default_cfg = {"timezone": "UTC", "value": 42}
    runtime.configure_defaults(default_cfg)

    config_path = runtime.paths.config_file
    config_path.write_text("not-json", encoding="utf-8")

    loaded = runtime.load_config(refresh=True)
    assert loaded == default_cfg
    assert _read_config(config_path) == default_cfg


def test_runtime_timezone_fallback(tmp_path):
    runtime = get_progress_runtime()
    runtime.configure_defaults({"timezone": "UTC"})

    config_path = runtime.paths.config_file
    config_data = _read_config(config_path)
    config_data["timezone"] = "Mars/OlympusMons"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    tz = runtime.timezone(refresh=True)
    assert tz.key == "Europe/Zurich"
