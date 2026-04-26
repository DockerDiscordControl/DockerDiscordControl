#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Container/Status/Diagnostics Service Tests     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for container/status/diagnostics services:
- services.web.container_log_service
- services.web.container_refresh_service
- services.status.status_cache_service
- services.web.diagnostics_service

The tests use ``tmp_path`` to exercise the file-based log readers with
real on-disk fixtures and ``unittest.mock`` to stub out Docker SDK,
helper modules, and singletons used by the services. They never touch
the real Docker daemon or the production filesystem under ``/app``.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure the real ``docker`` package is loaded so that ``docker.errors``
# inside the services resolves to real exception classes.
import docker  # noqa: F401
import docker.errors  # noqa: F401


# --------------------------------------------------------------------------- #
# container_log_service                                                       #
# --------------------------------------------------------------------------- #
from services.web.container_log_service import (
    ActionLogRequest,
    ClearLogRequest,
    ContainerLogRequest,
    ContainerLogService,
    FilteredLogRequest,
    LogResult,
    LogType,
    get_container_log_service,
)


class TestContainerLogServiceBasics:
    """Initialization and configuration."""

    def test_log_paths_dictionary_has_all_expected_keys(self):
        service = ContainerLogService()
        assert set(service.log_paths.keys()) == {"bot", "discord", "webui", "application"}
        # Every path entry should contain at least one Docker path and one dev path
        for entries in service.log_paths.values():
            assert len(entries) >= 2
            assert all(isinstance(p, str) and p for p in entries)

    def test_default_container_name(self):
        service = ContainerLogService()
        assert service.default_container == "dockerdiscordcontrol"

    def test_singleton_returns_same_instance(self):
        # Reset the module-level singleton so this test is deterministic
        import services.web.container_log_service as mod
        mod._container_log_service = None

        first = get_container_log_service()
        second = get_container_log_service()
        assert first is second
        assert isinstance(first, ContainerLogService)


class TestReadLogFile:
    """Tests for ``ContainerLogService._read_log_file``."""

    def test_returns_none_when_file_missing(self, tmp_path):
        service = ContainerLogService()
        missing = tmp_path / "does-not-exist.log"
        assert service._read_log_file(str(missing), 100) is None

    def test_reads_full_content_when_lines_below_limit(self, tmp_path):
        service = ContainerLogService()
        log_file = tmp_path / "short.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        out = service._read_log_file(str(log_file), 100)
        assert out == "line1\nline2\nline3\n"

    def test_returns_only_last_max_lines_when_exceeds_limit(self, tmp_path):
        service = ContainerLogService()
        log_file = tmp_path / "big.log"
        log_file.write_text("\n".join(f"line{i}" for i in range(100)) + "\n", encoding="utf-8")

        out = service._read_log_file(str(log_file), 5)
        # Should yield the LAST 5 lines (line95..line99)
        assert out is not None
        lines = [l for l in out.splitlines() if l]
        assert lines == [f"line{i}" for i in range(95, 100)]

    def test_handles_empty_file(self, tmp_path):
        service = ContainerLogService()
        log_file = tmp_path / "empty.log"
        log_file.write_text("", encoding="utf-8")
        assert service._read_log_file(str(log_file), 50) == ""

    def test_handles_invalid_utf8_gracefully(self, tmp_path):
        service = ContainerLogService()
        log_file = tmp_path / "bin.log"
        log_file.write_bytes(b"valid\n\xff\xfe garbage\n")
        out = service._read_log_file(str(log_file), 10)
        assert out is not None
        assert "valid" in out

    def test_io_error_returns_none(self, tmp_path):
        service = ContainerLogService()
        log_file = tmp_path / "x.log"
        log_file.write_text("content\n", encoding="utf-8")

        with patch("services.web.container_log_service.open",
                   side_effect=PermissionError("denied"), create=True):
            assert service._read_log_file(str(log_file), 10) is None


class TestGetWebuiLogs:
    """Exercises file-fallback path for webui log retrieval."""

    def test_reads_from_first_existing_path(self, tmp_path):
        service = ContainerLogService()
        webui_log = tmp_path / "webui_error.log"
        webui_log.write_text("webui-error-line-1\nwebui-error-line-2\n", encoding="utf-8")

        # Inject our temp file as the first candidate path.
        service.log_paths["webui"] = [str(webui_log), "/non/existent/fallback"]

        result = service._get_webui_logs(max_lines=50)
        assert isinstance(result, LogResult)
        assert result.success is True
        assert "webui-error-line-1" in (result.content or "")

    def test_falls_back_to_container_filtering_when_no_files(self):
        service = ContainerLogService()
        service.log_paths["webui"] = ["/no/such/file/a", "/no/such/file/b"]

        with patch.object(
            service, "_get_container_logs_sync",
            return_value="2025 GET /index HTTP/1.1\nnoise line\nflask startup\n",
        ) as mock_sync:
            result = service._get_webui_logs(max_lines=10)
        assert mock_sync.called
        assert result.success is True
        # Filtered content must contain at least one matching webui keyword
        assert "GET /" in (result.content or "") or "flask" in (result.content or "")

    def test_empty_file_falls_through_to_filter(self, tmp_path):
        service = ContainerLogService()
        empty = tmp_path / "webui_empty.log"
        empty.write_text("", encoding="utf-8")
        service.log_paths["webui"] = [str(empty)]

        with patch.object(
            service, "_get_container_logs_sync",
            return_value="some flask line\nGET / HTTP/1.1\n",
        ):
            result = service._get_webui_logs(max_lines=10)
        assert result.success is True


class TestFilteredLogsDispatch:
    """Tests for the ``get_filtered_logs`` dispatch method."""

    def test_unsupported_log_type_returns_400(self):
        service = ContainerLogService()
        # Hand-craft a fake LogType-like object with .value to avoid an enum assertion
        fake = MagicMock(spec=LogType)
        fake.value = "weird"
        # Force the if/elif chain to fall through
        request = FilteredLogRequest(log_type=fake, max_lines=10)
        result = service.get_filtered_logs(request)
        assert result.success is False
        assert result.status_code == 400

    def test_dispatches_to_bot(self, tmp_path):
        service = ContainerLogService()
        f = tmp_path / "bot.log"
        f.write_text("bot ready\n", encoding="utf-8")
        service.log_paths["bot"] = [str(f)]

        result = service.get_filtered_logs(FilteredLogRequest(log_type=LogType.BOT, max_lines=10))
        assert result.success is True
        assert "bot ready" in (result.content or "")

    def test_dispatches_to_discord(self, tmp_path):
        service = ContainerLogService()
        f = tmp_path / "discord.log"
        f.write_text("discord guild connected\n", encoding="utf-8")
        service.log_paths["discord"] = [str(f)]

        result = service.get_filtered_logs(FilteredLogRequest(log_type=LogType.DISCORD, max_lines=10))
        assert result.success is True

    def test_dispatches_to_application(self, tmp_path):
        service = ContainerLogService()
        f = tmp_path / "supervisord.log"
        f.write_text("INFO Starting supervisord\n", encoding="utf-8")
        service.log_paths["application"] = [str(f)]

        result = service.get_filtered_logs(FilteredLogRequest(log_type=LogType.APPLICATION, max_lines=10))
        assert result.success is True


class TestGetContainerLogs:
    """Tests for ``get_container_logs``."""

    def test_invalid_container_name_returns_400(self):
        service = ContainerLogService()
        with patch.object(service, "_validate_container_name", return_value=False):
            result = service.get_container_logs(ContainerLogRequest(container_name="bad name"))
        assert result.success is False
        assert result.status_code == 400

    def test_missing_container_returns_404(self):
        service = ContainerLogService()
        with patch.object(service, "_validate_container_name", return_value=True), \
             patch.object(service, "_get_container_logs_sync", return_value=None):
            result = service.get_container_logs(ContainerLogRequest(container_name="ghost"))
        assert result.success is False
        assert result.status_code == 404

    def test_successful_container_logs(self):
        service = ContainerLogService()
        with patch.object(service, "_validate_container_name", return_value=True), \
             patch.object(service, "_get_container_logs_sync", return_value="hello world"):
            result = service.get_container_logs(ContainerLogRequest(container_name="ddc"))
        assert result.success is True
        assert result.content == "hello world"


class TestClearLogs:
    def test_clear_logs_returns_success_message(self):
        service = ContainerLogService()
        result = service.clear_logs(ClearLogRequest(log_type="container"))
        assert result.success is True
        assert result.data is not None
        assert "Container" in result.data["message"]


class TestGetContainerLogsSync:
    """Cover ``_get_container_logs_sync`` and surrounding error handling."""

    def _make_mock_docker(self, *, raise_get=None, container_logs=b"hello logs"):
        """Build a mocked ``docker`` module compatible with the implementation."""
        fake_docker = MagicMock()
        # Real exception classes are required so ``except`` clauses match.
        fake_docker.errors = docker.errors

        client = MagicMock()
        if raise_get is not None:
            client.containers.get.side_effect = raise_get
        else:
            container = MagicMock()
            container.logs.return_value = container_logs
            client.containers.get.return_value = container
        fake_docker.DockerClient.return_value = client
        return fake_docker, client

    def test_returns_decoded_log_text(self):
        service = ContainerLogService()
        fake_docker, client = self._make_mock_docker(container_logs=b"line A\nline B\n")
        with patch.dict("sys.modules", {"docker": fake_docker}):
            out = service._get_container_logs_sync("ddc", 100)
        assert out == "line A\nline B\n"
        client.close.assert_called_once()

    def test_handles_not_found(self):
        service = ContainerLogService()
        fake_docker, client = self._make_mock_docker(
            raise_get=docker.errors.NotFound("missing"))
        with patch.dict("sys.modules", {"docker": fake_docker}):
            assert service._get_container_logs_sync("ghost", 50) is None
        client.close.assert_called_once()

    def test_handles_api_error(self):
        service = ContainerLogService()
        fake_docker, client = self._make_mock_docker(
            raise_get=docker.errors.APIError("boom"))
        with patch.dict("sys.modules", {"docker": fake_docker}):
            assert service._get_container_logs_sync("ddc", 50) is None
        client.close.assert_called_once()

    def test_handles_outer_exception(self):
        service = ContainerLogService()
        fake_docker = MagicMock()
        fake_docker.errors = docker.errors
        fake_docker.DockerClient.side_effect = RuntimeError("can't connect")
        with patch.dict("sys.modules", {"docker": fake_docker}):
            assert service._get_container_logs_sync("ddc", 50) is None


class TestValidateContainerName:
    def test_valid_name(self):
        service = ContainerLogService()
        assert service._validate_container_name("dockerdiscordcontrol") is True
        assert service._validate_container_name("ddc-bot_1.0") is True

    def test_invalid_name(self):
        service = ContainerLogService()
        assert service._validate_container_name("bad name with spaces") is False
        assert service._validate_container_name("rm -rf /") is False

    def test_fallback_when_helper_missing(self):
        service = ContainerLogService()
        # Force the helper import to ImportError to hit the regex fallback.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "utils.common_helpers":
                raise ImportError("boom")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            assert service._validate_container_name("ddc_1") is True
            assert service._validate_container_name("bad name") is False


class TestFilteredContainerLogsHelper:
    """Exercise ``_get_filtered_container_logs`` directly."""

    def test_returns_no_logs_message_when_no_match(self):
        service = ContainerLogService()
        with patch.object(service, "_get_container_logs_sync",
                          return_value="totally unrelated content\nmore unrelated\n"):
            result = service._get_filtered_container_logs(10, ["xyzzy"], "no match")
        assert result.success is True
        assert result.content == "no match"

    def test_returns_404_when_container_missing(self):
        service = ContainerLogService()
        with patch.object(service, "_get_container_logs_sync", return_value=None):
            result = service._get_filtered_container_logs(10, ["x"], "no match")
        assert result.success is False
        assert result.status_code == 404


class TestActionLogs:
    def test_get_action_logs_text_uses_helper(self):
        service = ContainerLogService()
        with patch("services.infrastructure.action_logger.get_action_logs_text",
                   return_value="action text"):
            result = service.get_action_logs(ActionLogRequest(format_type="text", limit=10))
        assert result.success is True
        assert result.content == "action text"

    def test_get_action_logs_text_returns_placeholder_when_empty(self):
        service = ContainerLogService()
        with patch("services.infrastructure.action_logger.get_action_logs_text",
                   return_value=""):
            result = service.get_action_logs(ActionLogRequest(format_type="text", limit=10))
        assert result.success is True
        assert "No action logs available" in (result.content or "")

    def test_get_action_logs_json(self):
        service = ContainerLogService()
        fake_logs = [{"a": 1}, {"a": 2}]
        with patch("services.infrastructure.action_logger.get_action_logs_json",
                   return_value=fake_logs):
            result = service.get_action_logs(ActionLogRequest(format_type="json", limit=10))
        assert result.success is True
        assert result.data is not None
        assert result.data["count"] == 2
        assert result.data["logs"] == fake_logs


# --------------------------------------------------------------------------- #
# container_refresh_service                                                   #
# --------------------------------------------------------------------------- #
from services.web.container_refresh_service import (
    ContainerRefreshRequest,
    ContainerRefreshResult,
    ContainerRefreshService,
    get_container_refresh_service,
)


class TestContainerRefreshService:
    def _make_dependencies(self, container_count=3, error=None, timestamp=None):
        """Create a mock dependencies dict similar to ``_initialize_dependencies``."""
        get_live = MagicMock(return_value=([MagicMock()] * container_count, error))
        ts = timestamp if timestamp is not None else 1700000000.0
        cache = {"global_timestamp": ts}
        load_config = MagicMock(return_value={"timezone": "UTC"})
        return {
            "success": True,
            "get_docker_containers_live": get_live,
            "docker_cache": cache,
            "load_config": load_config,
            "log_user_action": MagicMock(),
        }

    def test_singleton_returns_same_instance(self):
        import services.web.container_refresh_service as mod
        mod._container_refresh_service = None
        a = get_container_refresh_service()
        b = get_container_refresh_service()
        assert a is b
        assert isinstance(a, ContainerRefreshService)

    def test_refresh_success_path(self):
        service = ContainerRefreshService()
        deps = self._make_dependencies(container_count=5)
        with patch.object(service, "_initialize_dependencies", return_value=deps), \
             patch.object(service, "_log_refresh_action"):
            result = service.refresh_containers(ContainerRefreshRequest())

        assert isinstance(result, ContainerRefreshResult)
        assert result.success is True
        assert result.container_count == 5
        assert result.timestamp == 1700000000.0
        assert result.formatted_time and "2023" in result.formatted_time

    def test_refresh_dependency_initialization_failure(self):
        service = ContainerRefreshService()
        with patch.object(service, "_initialize_dependencies",
                          return_value={"success": False, "error": "boom"}):
            result = service.refresh_containers(ContainerRefreshRequest())
        assert result.success is False
        assert "boom" in (result.error or "")

    def test_refresh_docker_failure(self):
        service = ContainerRefreshService()
        deps = self._make_dependencies(error="api fail")
        with patch.object(service, "_initialize_dependencies", return_value=deps):
            result = service.refresh_containers(ContainerRefreshRequest())
        assert result.success is False
        assert result.message == "Container refresh failed"

    def test_get_formatted_timestamp_with_known_timezone(self):
        service = ContainerRefreshService()
        deps = self._make_dependencies(timestamp=1700000000.0)
        out = service._get_formatted_timestamp(deps)
        assert out["timestamp"] == 1700000000.0
        assert isinstance(out["formatted_time"], str)
        assert "UTC" in out["formatted_time"]

    def test_get_formatted_timestamp_handles_missing_timezone_key(self):
        service = ContainerRefreshService()
        deps = self._make_dependencies()
        deps["load_config"] = MagicMock(return_value={})  # default Europe/Berlin
        out = service._get_formatted_timestamp(deps)
        assert "formatted_time" in out
        assert isinstance(out["formatted_time"], str)


# --------------------------------------------------------------------------- #
# status_cache_service                                                        #
# --------------------------------------------------------------------------- #


class TestStatusCacheService:
    @pytest.fixture
    def fake_inner(self):
        """A fake ContainerStatusService used as the pass-through target."""
        inner = MagicMock()
        inner.get_formatted_status = MagicMock(return_value=None)
        inner.set_formatted_status = MagicMock()
        inner.get_all_formatted_statuses = MagicMock(return_value={})
        inner.clear_cache = MagicMock()
        inner.invalidate_container = MagicMock(return_value=False)
        inner.get_cache_stats = MagicMock(return_value={"total_entries": 0})
        return inner

    @pytest.fixture
    def cache_service(self, fake_inner):
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_inner,
        ):
            from services.status.status_cache_service import StatusCacheService
            svc = StatusCacheService()
            svc._container_status_service = fake_inner
            return svc

    def test_singleton(self, fake_inner):
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_inner,
        ):
            import services.status.status_cache_service as mod
            mod._status_cache_service = None
            from services.status.status_cache_service import (
                StatusCacheService,
                get_status_cache_service,
            )
            a = get_status_cache_service()
            b = get_status_cache_service()
            assert a is b
            assert isinstance(a, StatusCacheService)

    def test_set_then_get_returns_data(self, cache_service, fake_inner):
        cache_service.set("c1", {"data": ("running",), "timestamp": datetime.now(timezone.utc)})
        assert fake_inner.set_formatted_status.called

        fake_inner.get_formatted_status.return_value = {
            "data": ("running",),
            "timestamp": datetime.now(timezone.utc),
        }
        out = cache_service.get("c1")
        assert out is not None
        assert out["data"] == ("running",)

    def test_get_returns_none_for_missing(self, cache_service, fake_inner):
        fake_inner.get_formatted_status.return_value = None
        assert cache_service.get("missing") is None

    def test_set_uses_default_timestamp(self, cache_service, fake_inner):
        cache_service.set("c2", {"data": "x"})
        # Last positional/keyword call should have a real datetime
        args, kwargs = fake_inner.set_formatted_status.call_args
        # call signature: (name, data, timestamp)
        ts = args[2]
        assert isinstance(ts, datetime)

    def test_set_error_caches_error_state(self, cache_service, fake_inner):
        cache_service.set_error("c3", "something failed")
        fake_inner.set_formatted_status.assert_called_once()
        kwargs = fake_inner.set_formatted_status.call_args.kwargs
        assert kwargs.get("error") == "something failed"

    def test_set_error_default_message(self, cache_service, fake_inner):
        cache_service.set_error("c4")
        kwargs = fake_inner.set_formatted_status.call_args.kwargs
        assert kwargs.get("error") == "Status check failed"

    def test_clear_calls_through(self, cache_service, fake_inner):
        cache_service.clear()
        fake_inner.clear_cache.assert_called_once()

    def test_remove_passes_through(self, cache_service, fake_inner):
        fake_inner.invalidate_container.return_value = True
        assert cache_service.remove("c5") is True
        fake_inner.invalidate_container.return_value = False
        assert cache_service.remove("c5") is False

    def test_copy_returns_dict(self, cache_service, fake_inner):
        fake_inner.get_all_formatted_statuses.return_value = {"a": {"x": 1}}
        out = cache_service.copy()
        assert out == {"a": {"x": 1}}

    def test_items_lists_tuples(self, cache_service, fake_inner):
        fake_inner.get_all_formatted_statuses.return_value = {"a": {"x": 1}, "b": {"y": 2}}
        items = cache_service.items()
        assert isinstance(items, list)
        assert {k for k, _ in items} == {"a", "b"}

    def test_is_cache_valid_always_true(self, cache_service):
        assert cache_service._is_cache_valid({"timestamp": datetime.now(timezone.utc)}) is True

    def test_get_cache_age_for_display_seconds(self, cache_service):
        ts = datetime.now(timezone.utc) - timedelta(seconds=10)
        assert cache_service.get_cache_age_for_display(ts).endswith("s ago")

    def test_get_cache_age_for_display_minutes(self, cache_service):
        ts = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert cache_service.get_cache_age_for_display(ts).endswith("m ago")

    def test_get_cache_age_for_display_hours(self, cache_service):
        ts = datetime.now(timezone.utc) - timedelta(hours=3)
        assert cache_service.get_cache_age_for_display(ts).endswith("h ago")

    def test_get_cache_age_naive_timestamp_assumed_utc(self, cache_service):
        ts = datetime.utcnow() - timedelta(seconds=5)  # naive
        out = cache_service.get_cache_age_for_display(ts)
        assert "ago" in out

    def test_bulk_set_calls_set_for_each(self, cache_service, fake_inner):
        now = datetime.now(timezone.utc)
        cache_service.bulk_set({
            "c1": ("d1", now),
            "c2": ("d2", now),
        })
        assert fake_inner.set_formatted_status.call_count == 2

    def test_get_stats_passes_through(self, cache_service, fake_inner):
        fake_inner.get_cache_stats.return_value = {"total_entries": 7}
        out = cache_service.get_stats()
        assert out == {"total_entries": 7}


# --------------------------------------------------------------------------- #
# diagnostics_service                                                         #
# --------------------------------------------------------------------------- #
from services.web.diagnostics_service import (
    DebugModeRequest,
    DebugStatusRequest,
    DiagnosticsResult,
    DiagnosticsService,
    PortDiagnosticsRequest,
    get_diagnostics_service,
)


class TestDiagnosticsService:
    def test_singleton(self):
        import services.web.diagnostics_service as mod
        mod._diagnostics_service = None
        a = get_diagnostics_service()
        b = get_diagnostics_service()
        assert a is b
        assert isinstance(a, DiagnosticsService)

    @pytest.mark.parametrize("inp,expected", [
        (None, 10),       # default fallback
        (5, 5),           # accepts integer
        ("15", 15),       # accepts numeric string
        (-3, 1),          # clamps below 1
        (120, 60),        # clamps above 60
        ("garbage", 10),  # non-numeric string falls back to default
    ])
    def test_validate_debug_duration(self, inp, expected):
        service = DiagnosticsService()
        assert service._validate_debug_duration(inp) == expected

    def test_format_debug_status_enabled(self):
        service = DiagnosticsService()
        expiry = time.time() + 600
        out = service._format_debug_status(True, expiry, 605.5)
        assert out["is_enabled"] is True
        assert out["expiry_formatted"]
        assert "10m" in out["remaining_formatted"]

    def test_format_debug_status_disabled(self):
        service = DiagnosticsService()
        out = service._format_debug_status(False, 0.0, 0.0)
        assert out["is_enabled"] is False
        assert out["remaining_formatted"] == ""
        assert out["expiry_formatted"] == ""

    def test_enable_temp_debug_success(self):
        service = DiagnosticsService()
        future = time.time() + 600
        with patch("utils.logging_utils.enable_temporary_debug",
                   return_value=(True, future)), \
             patch.object(service, "_log_debug_action"):
            result = service.enable_temp_debug(DebugModeRequest(duration_minutes=10))
        assert isinstance(result, DiagnosticsResult)
        assert result.success is True
        assert result.data["duration_minutes"] == 10
        assert result.data["expiry"] == future

    def test_enable_temp_debug_helper_returns_false(self):
        service = DiagnosticsService()
        with patch("utils.logging_utils.enable_temporary_debug",
                   return_value=(False, 0)):
            result = service.enable_temp_debug(DebugModeRequest(duration_minutes=10))
        assert result.success is False
        assert result.status_code == 500

    def test_disable_temp_debug_success(self):
        service = DiagnosticsService()
        with patch("utils.logging_utils.disable_temporary_debug", return_value=True), \
             patch.object(service, "_log_debug_action"):
            result = service.disable_temp_debug(DebugModeRequest())
        assert result.success is True
        assert "disabled" in result.data["message"].lower()

    def test_disable_temp_debug_helper_returns_false(self):
        service = DiagnosticsService()
        with patch("utils.logging_utils.disable_temporary_debug", return_value=False):
            result = service.disable_temp_debug(DebugModeRequest())
        assert result.success is False
        assert result.status_code == 500

    def test_get_debug_status_enabled(self):
        service = DiagnosticsService()
        expiry = time.time() + 300
        with patch("utils.logging_utils.get_temporary_debug_status",
                   return_value=(True, expiry, 305.0)):
            result = service.get_debug_status(DebugStatusRequest())
        assert result.success is True
        assert result.data["is_enabled"] is True
        assert "5m" in result.data["remaining_formatted"]

    def test_get_debug_status_disabled(self):
        service = DiagnosticsService()
        with patch("utils.logging_utils.get_temporary_debug_status",
                   return_value=(False, 0.0, 0.0)):
            result = service.get_debug_status(DebugStatusRequest())
        assert result.success is True
        assert result.data["is_enabled"] is False

    def test_run_port_diagnostics(self):
        service = DiagnosticsService()
        fake_report = {"port_5000": "open", "host": "0.0.0.0"}
        with patch("app.utils.port_diagnostics.run_port_diagnostics",
                   return_value=fake_report):
            result = service.run_port_diagnostics(PortDiagnosticsRequest())
        assert result.success is True
        assert result.data["diagnostics"] == fake_report

    def test_log_debug_action_swallows_import_errors(self):
        service = DiagnosticsService()
        # Force the import inside ``_log_debug_action`` to raise
        with patch.dict("sys.modules", {"services.infrastructure.action_logger": None}):
            # Should not raise
            service._log_debug_action("ENABLE", "Test")
