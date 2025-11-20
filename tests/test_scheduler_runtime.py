# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import os
import time
from pathlib import Path

import pytest

from services.scheduling import get_scheduler_runtime, reset_scheduler_runtime


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch, tmp_path):
    """Ensure each test gets a fresh runtime rooted in a temporary directory."""

    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    reset_scheduler_runtime()
    yield
    reset_scheduler_runtime()


def test_scheduler_runtime_uses_env_override(tmp_path):
    runtime = get_scheduler_runtime()

    expected_path = Path(tmp_path) / "tasks.json"
    assert runtime.tasks_file_path == expected_path

    runtime.ensure_layout()
    assert expected_path.parent.exists()


def test_scheduler_runtime_cache_roundtrip():
    runtime = get_scheduler_runtime()

    runtime.replace_tasks_cache({"alpha": object()})
    assert "alpha" in runtime.tasks_cache

    runtime.clear_tasks_cache()
    assert runtime.tasks_cache == {}

    runtime.update_container_cache("alpha", [object()], timestamp=123.0)
    assert runtime.container_tasks_cache["alpha"]
    assert runtime.container_cache_timestamp == pytest.approx(123.0)

    runtime.clear_container_cache()
    assert runtime.container_tasks_cache == {}
    assert runtime.container_cache_timestamp == 0.0


def test_scheduler_runtime_file_modification_detection(tmp_path):
    runtime = get_scheduler_runtime()
    tasks_file = runtime.tasks_file_path

    assert not runtime.is_tasks_file_modified()

    tasks_file.write_text("[]", encoding="utf-8")
    assert runtime.is_tasks_file_modified()
    assert not runtime.is_tasks_file_modified()

    time.sleep(0.01)
    tasks_file.write_text("[{}]", encoding="utf-8")
    assert runtime.is_tasks_file_modified()


def test_scheduler_runtime_timezone_cache():
    runtime = get_scheduler_runtime()
    runtime.clear_timezone_cache()

    tz1 = runtime.get_timezone("Europe/Zurich")
    tz2 = runtime.get_timezone("Europe/Zurich")
    assert tz1 is tz2

    fallback = runtime.get_timezone("Invalid/Zone")
    from pytz import UTC

    assert fallback is UTC
