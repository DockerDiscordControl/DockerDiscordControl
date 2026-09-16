# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package F (F3 follow-up) - a missing or failing psutil
degrades the performance stats instead of breaking the endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.web.performance_stats_service import PerformanceStatsService


@pytest.fixture
def svc(monkeypatch):
    service = PerformanceStatsService()
    # Keep the other collectors cheap and deterministic
    for name in ("_get_config_cache_stats", "_get_docker_cache_stats", "_get_scheduler_stats"):
        monkeypatch.setattr(service, name, lambda: {})
    return service


def test_missing_psutil_degrades_memory_sections(svc):
    with patch.dict("sys.modules", {"psutil": None}):  # import psutil -> ImportError
        result = svc.get_performance_stats()
    assert result.success is True
    assert "error" in result.performance_data["system_memory"]
    assert "error" in result.performance_data["process_memory"]


def test_psutil_oserror_degrades_system_memory(svc):
    fake_psutil = MagicMock()
    fake_psutil.virtual_memory.side_effect = OSError("/proc/meminfo unreadable")
    with patch.dict("sys.modules", {"psutil": fake_psutil}):
        stats = svc._get_system_memory_stats()
    assert "unreadable" in stats["error"]


@pytest.mark.parametrize("exc", [ImportError("gone"), OSError("io"), RuntimeError("boom")])
def test_collector_errors_return_failed_result(svc, monkeypatch, exc):
    def _raise():
        raise exc

    monkeypatch.setattr(svc, "_get_scheduler_stats", _raise)
    result = svc.get_performance_stats()  # must not raise
    assert result.success is False
    assert "Error collecting performance statistics" in result.error
