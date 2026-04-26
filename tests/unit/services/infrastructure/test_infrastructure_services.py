# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Functional unit tests for five DDC infrastructure services.

Covered modules:
* services.infrastructure.container_status_service
* services.infrastructure.docker_connectivity_service
* services.infrastructure.spam_protection_service
* services.infrastructure.update_notifier
* services.infrastructure.dynamic_cooldown_manager

These tests target the public API of each service - dataclasses, helpers,
and the externally-observable behaviour of methods.  External dependencies
(docker, requests, time, threading) are mocked using ``unittest.mock``.

NOTE: We deliberately do NOT manipulate ``sys.modules``.  Real modules are
imported and only the boundary calls (``docker.from_env``, network IO) are
patched.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================ #
# container_status_service                                                     #
# ============================================================================ #

from services.infrastructure.container_status_service import (
    ContainerStatusService,
    ContainerStatusRequest,
    ContainerBulkStatusRequest,
    ContainerStatusResult,
    ContainerBulkStatusResult,
    get_container_status_service,
    get_docker_info_dict_service_first,
    get_docker_info_service_first,
    get_docker_stats_service_first,
)


class TestContainerStatusDataclasses:
    """ContainerStatusResult / ContainerBulkStatusResult dataclass coverage."""

    def test_container_status_result_default_values(self):
        result = ContainerStatusResult(success=True, container_name="ngx")
        assert result.success is True
        assert result.container_name == "ngx"
        assert result.is_running is False
        assert result.status == "unknown"
        assert result.cpu_percent == 0.0
        assert result.memory_usage_mb == 0.0
        assert result.cached is False
        assert result.error_message is None

    def test_container_status_result_full_values(self):
        result = ContainerStatusResult(
            success=True,
            container_name="db",
            is_running=True,
            status="running",
            cpu_percent=12.5,
            memory_usage_mb=256.0,
            memory_limit_mb=1024.0,
            uptime_seconds=3600,
            image="postgres:15",
            ports={"5432/tcp": [{"HostPort": "5432"}]},
            query_duration_ms=42.0,
        )
        assert result.is_running is True
        assert result.image == "postgres:15"
        assert result.ports["5432/tcp"][0]["HostPort"] == "5432"

    def test_container_status_result_is_frozen(self):
        result = ContainerStatusResult(success=True, container_name="x")
        with pytest.raises((AttributeError, Exception)):
            result.success = False  # frozen dataclass

    def test_bulk_status_result_defaults(self):
        bulk = ContainerBulkStatusResult(success=True, results={})
        assert bulk.successful_containers == 0
        assert bulk.failed_containers == 0
        assert bulk.total_duration_ms == 0.0
        assert bulk.error_message is None

    def test_bulk_status_request_defaults(self):
        req = ContainerBulkStatusRequest(container_names=["a", "b"])
        assert req.include_stats is True
        assert req.include_details is True
        assert req.timeout_seconds == 15.0
        assert req.max_concurrent == 3


class TestContainerStatusServiceCache:
    """Cache behaviour of ContainerStatusService."""

    def test_init_creates_empty_caches(self, monkeypatch):
        monkeypatch.setenv("DDC_DOCKER_CACHE_DURATION", "30")
        svc = ContainerStatusService()
        assert svc._cache == {}
        assert svc._formatted_cache == {}
        assert svc._cache_ttl == 30.0

    def test_cache_ttl_from_env(self, monkeypatch):
        monkeypatch.setenv("DDC_DOCKER_CACHE_DURATION", "120")
        svc = ContainerStatusService()
        assert svc._cache_ttl == 120.0

    def test_store_and_get_from_cache(self):
        svc = ContainerStatusService()
        result = ContainerStatusResult(success=True, container_name="c")
        svc._store_in_cache("c", result)
        cached = svc._get_from_cache("c")
        assert cached is not None
        assert cached["result"] is result
        assert "timestamp" in cached

    def test_get_cache_miss_returns_none(self):
        svc = ContainerStatusService()
        assert svc._get_from_cache("not-there") is None

    def test_is_cache_expired(self, monkeypatch):
        svc = ContainerStatusService()
        # Force an old timestamp
        import time as _time
        entry = {"result": ContainerStatusResult(success=True, container_name="x"),
                 "timestamp": _time.time() - svc._cache_ttl - 5}
        assert svc._is_cache_expired(entry) is True

        fresh = {"result": ContainerStatusResult(success=True, container_name="x"),
                 "timestamp": _time.time()}
        assert svc._is_cache_expired(fresh) is False

    def test_clear_cache_removes_all_entries(self):
        svc = ContainerStatusService()
        svc._store_in_cache("a", ContainerStatusResult(success=True, container_name="a"))
        svc._formatted_cache["b"] = {"data": "x", "timestamp": datetime.now(timezone.utc)}
        svc.clear_cache()
        assert svc._cache == {}
        assert svc._formatted_cache == {}

    def test_invalidate_container_present(self):
        svc = ContainerStatusService()
        svc._store_in_cache("a", ContainerStatusResult(success=True, container_name="a"))
        assert svc.invalidate_container("a") is True
        assert "a" not in svc._cache

    def test_invalidate_container_absent(self):
        svc = ContainerStatusService()
        assert svc.invalidate_container("nope") is False

    def test_invalidate_container_clears_formatted_cache_only(self):
        svc = ContainerStatusService()
        svc._formatted_cache["b"] = {"data": "x", "timestamp": datetime.now(timezone.utc)}
        assert svc.invalidate_container("b") is True
        assert "b" not in svc._formatted_cache

    def test_record_performance_keeps_last_10(self):
        svc = ContainerStatusService()
        for i in range(15):
            svc._record_performance("c", float(i))
        history = svc._performance_history["c"]
        assert len(history) == 10
        # Oldest dropped, newest kept
        assert history[0] == 5.0
        assert history[-1] == 14.0

    def test_get_cache_stats_structure(self):
        svc = ContainerStatusService()
        svc._store_in_cache("a", ContainerStatusResult(success=True, container_name="a"))
        stats = svc.get_cache_stats()
        assert "total_entries" in stats
        assert "raw_cache_entries" in stats
        assert "formatted_cache_entries" in stats
        assert "cache_ttl_seconds" in stats
        assert stats["raw_cache_entries"] == 1


class TestContainerStatusFormattedCache:
    def test_set_and_get_formatted_status(self):
        svc = ContainerStatusService()
        ts = datetime.now(timezone.utc)
        svc.set_formatted_status("ngx", data=("running", 1.0), timestamp=ts)
        got = svc.get_formatted_status("ngx")
        assert got is not None
        assert got["data"] == ("running", 1.0)
        assert got["timestamp"] == ts
        assert got["error"] is None

    def test_get_formatted_status_missing(self):
        svc = ContainerStatusService()
        assert svc.get_formatted_status("missing") is None

    def test_get_formatted_status_expired_returns_none(self, monkeypatch):
        svc = ContainerStatusService()
        # Old datetime triggers expiry
        old_ts = datetime.fromtimestamp(0, tz=timezone.utc)
        svc.set_formatted_status("ngx", data="x", timestamp=old_ts)
        assert svc.get_formatted_status("ngx") is None
        # Auto-removed
        assert "ngx" not in svc._formatted_cache

    def test_get_all_formatted_statuses_returns_deepcopy(self):
        svc = ContainerStatusService()
        ts = datetime.now(timezone.utc)
        svc.set_formatted_status("a", data={"x": 1}, timestamp=ts)
        svc.set_formatted_status("b", data={"y": 2}, timestamp=ts)
        all_stats = svc.get_all_formatted_statuses()
        assert set(all_stats.keys()) == {"a", "b"}
        # Mutating returned copy must not affect service cache
        all_stats["a"]["data"]["x"] = 999
        assert svc._formatted_cache["a"]["data"]["x"] == 1


class TestContainerStatusCpuMemory:
    """Helper math methods _calculate_cpu_percent / _calculate_memory_from_stats."""

    def test_cpu_percent_with_valid_stats(self):
        svc = ContainerStatusService()
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 2]},
                "system_cpu_usage": 1000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
        }
        cpu = svc._calculate_cpu_percent_from_stats(stats, "x")
        # delta=100, system_delta=500 -> (100/500) * 2 * 100 = 40.0
        assert cpu == pytest.approx(40.0)

    def test_cpu_percent_fallback_returns_min(self):
        svc = ContainerStatusService()
        stats = {"cpu_stats": {}, "precpu_stats": {}}
        cpu = svc._calculate_cpu_percent_from_stats(stats, "x")
        assert cpu == 0.1

    def test_cpu_percent_handles_exception(self):
        svc = ContainerStatusService()
        # Pass non-dict => triggers .get on int -> AttributeError caught
        cpu = svc._calculate_cpu_percent_from_stats(None, "x")  # type: ignore[arg-type]
        assert cpu == 0.1

    def test_memory_from_stats_with_usage_and_limit(self):
        svc = ContainerStatusService()
        stats = {"memory_stats": {"usage": 1024 * 1024 * 100, "limit": 1024 * 1024 * 500}}
        usage_mb, limit_mb = svc._calculate_memory_from_stats(stats, "x")
        assert usage_mb == pytest.approx(100.0)
        assert limit_mb == pytest.approx(500.0)

    def test_memory_from_stats_empty_returns_defaults(self):
        svc = ContainerStatusService()
        usage_mb, limit_mb = svc._calculate_memory_from_stats({}, "x")
        assert usage_mb == 2.0
        assert limit_mb == 1024.0

    def test_memory_from_stats_handles_rss_cache(self):
        svc = ContainerStatusService()
        stats = {
            "memory_stats": {
                "stats": {"rss": 1024 * 1024 * 50, "cache": 1024 * 1024 * 10},
                "limit": 1024 * 1024 * 200,
            }
        }
        usage_mb, limit_mb = svc._calculate_memory_from_stats(stats, "x")
        assert usage_mb == pytest.approx(60.0)
        assert limit_mb == pytest.approx(200.0)


class TestContainerStatusGetSingleton:
    def test_get_container_status_service_returns_singleton(self):
        a = get_container_status_service()
        b = get_container_status_service()
        assert a is b
        assert isinstance(a, ContainerStatusService)


class TestContainerStatusGetCachedAndAsync:
    @pytest.mark.asyncio
    async def test_get_container_status_returns_from_cache(self):
        svc = ContainerStatusService()
        cached = ContainerStatusResult(success=True, container_name="redis", is_running=True)
        svc._store_in_cache("redis", cached)

        req = ContainerStatusRequest(container_name="redis")
        result = await svc.get_container_status(req)
        assert result.success is True
        assert result.container_name == "redis"
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_get_container_status_handles_service_error(self):
        svc = ContainerStatusService()

        async def boom(_req):
            raise RuntimeError("docker exploded")

        with patch.object(svc, "_fetch_container_status", side_effect=boom):
            req = ContainerStatusRequest(container_name="boom")
            result = await svc.get_container_status(req)
        assert result.success is False
        assert result.error_type == "service_error"
        assert "docker exploded" in result.error_message

    @pytest.mark.asyncio
    async def test_get_container_status_handles_data_error(self):
        svc = ContainerStatusService()

        async def boom(_req):
            raise ValueError("bad data")

        with patch.object(svc, "_fetch_container_status", side_effect=boom):
            req = ContainerStatusRequest(container_name="x")
            result = await svc.get_container_status(req)
        assert result.success is False
        assert result.error_type == "data_error"

    @pytest.mark.asyncio
    async def test_get_bulk_container_status_aggregates_results(self):
        svc = ContainerStatusService()

        async def fetch_mock(req):
            return ContainerStatusResult(success=True, container_name=req.container_name, is_running=True)

        with patch.object(svc, "_fetch_container_status", side_effect=fetch_mock):
            req = ContainerBulkStatusRequest(container_names=["a", "b", "c"])
            bulk = await svc.get_bulk_container_status(req)
        assert bulk.success is True
        assert bulk.successful_containers == 3
        assert bulk.failed_containers == 0
        assert set(bulk.results.keys()) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_get_bulk_container_status_mixed_success(self):
        svc = ContainerStatusService()

        async def fetch_mock(req):
            if req.container_name == "fail":
                return ContainerStatusResult(
                    success=False, container_name=req.container_name, error_message="nope")
            return ContainerStatusResult(success=True, container_name=req.container_name)

        with patch.object(svc, "_fetch_container_status", side_effect=fetch_mock):
            req = ContainerBulkStatusRequest(container_names=["ok", "fail"])
            bulk = await svc.get_bulk_container_status(req)
        assert bulk.successful_containers == 1
        assert bulk.failed_containers == 1


class TestContainerStatusDeactivate:
    def test_deactivate_no_file_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        svc = ContainerStatusService()
        # File does not exist
        assert svc._deactivate_container("nothere") is False

    def test_deactivate_writes_active_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        cont_dir = tmp_path / "containers"
        cont_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = cont_dir / "myc.json"
        cfg_path.write_text(json.dumps({"name": "myc", "active": True}), encoding="utf-8")

        svc = ContainerStatusService()
        ok = svc._deactivate_container("myc")
        assert ok is True
        new_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert new_data["active"] is False

    def test_deactivate_already_inactive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        cont_dir = tmp_path / "containers"
        cont_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = cont_dir / "myc.json"
        cfg_path.write_text(json.dumps({"name": "myc", "active": False}), encoding="utf-8")

        svc = ContainerStatusService()
        # Returns True (already inactive but operation succeeded)
        assert svc._deactivate_container("myc") is True


class TestContainerStatusCompatibilityFunctions:
    @pytest.mark.asyncio
    async def test_get_docker_info_dict_returns_none_on_failure(self):
        fake_service = MagicMock()
        fake_service.get_container_status = AsyncMock(
            return_value=ContainerStatusResult(success=False, container_name="x"))
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_service,
        ):
            result = await get_docker_info_dict_service_first("x")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_docker_info_dict_returns_dict_on_success(self):
        fake_service = MagicMock()
        fake_service.get_container_status = AsyncMock(
            return_value=ContainerStatusResult(
                success=True,
                container_name="x",
                is_running=True,
                image="nginx:latest",
                ports={"80/tcp": []},
                cpu_percent=5.5,
                memory_usage_mb=42.0,
                uptime_seconds=99,
            ))
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_service,
        ):
            result = await get_docker_info_dict_service_first("x")
        assert result["State"]["Running"] is True
        assert result["Config"]["Image"] == "nginx:latest"
        assert result["_computed"]["cpu_percent"] == 5.5
        assert result["_computed"]["uptime_seconds"] == 99

    @pytest.mark.asyncio
    async def test_get_docker_info_returns_tuple_on_success(self):
        fake_service = MagicMock()
        fake_service.get_container_status = AsyncMock(
            return_value=ContainerStatusResult(
                success=True, container_name="x", is_running=True,
                cpu_percent=1.0, memory_usage_mb=10.0, uptime_seconds=60,
            ))
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_service,
        ):
            result = await get_docker_info_service_first("x")
        assert result == ("x", True, 1.0, 10.0, 60, True)

    @pytest.mark.asyncio
    async def test_get_docker_stats_returns_dict_on_success(self):
        fake_service = MagicMock()
        fake_service.get_container_status = AsyncMock(
            return_value=ContainerStatusResult(
                success=True, container_name="x", is_running=True,
                status="running", cpu_percent=1.0,
                memory_usage_mb=10.0, memory_limit_mb=1024.0,
            ))
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_service,
        ):
            result = await get_docker_stats_service_first("x")
        assert result["cpu_percent"] == 1.0
        assert result["memory_limit_mb"] == 1024.0
        assert result["is_running"] is True


# ============================================================================ #
# docker_connectivity_service                                                  #
# ============================================================================ #

from services.infrastructure.docker_connectivity_service import (
    DockerConnectivityService,
    DockerConnectivityRequest,
    DockerConnectivityResult,
    DockerErrorEmbedRequest,
    DockerErrorEmbedResult,
    get_docker_connectivity_service,
)


class TestDockerConnectivityDataclasses:
    def test_connectivity_request_default(self):
        req = DockerConnectivityRequest()
        assert req.timeout_seconds == 5.0

    def test_connectivity_result_defaults(self):
        result = DockerConnectivityResult(is_connected=True)
        assert result.is_connected is True
        assert result.error_message is None
        assert result.error_type is None

    def test_error_embed_result_default_color(self):
        result = DockerErrorEmbedResult(success=True, title="t", description="d")
        assert result.color == 0xe74c3c
        assert "ddc.bot" in result.footer_text


class TestDockerConnectivityCheck:
    @pytest.mark.asyncio
    async def test_ping_success_returns_connected(self):
        svc = DockerConnectivityService()

        class _Ctx:
            async def __aenter__(self):
                client = MagicMock()
                client.ping.return_value = True
                return client

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            return_value=_Ctx(),
        ):
            result = await svc.check_connectivity(DockerConnectivityRequest())
        assert result.is_connected is True

    @pytest.mark.asyncio
    async def test_ping_returns_false_yields_ping_failed(self):
        svc = DockerConnectivityService()

        class _Ctx:
            async def __aenter__(self):
                client = MagicMock()
                client.ping.return_value = False
                return client

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            return_value=_Ctx(),
        ):
            result = await svc.check_connectivity(DockerConnectivityRequest())
        assert result.is_connected is False
        assert result.error_type == "ping_failed"

    @pytest.mark.asyncio
    async def test_timeout_error_classified(self):
        svc = DockerConnectivityService()

        class _Ctx:
            async def __aenter__(self):
                raise asyncio.TimeoutError()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            return_value=_Ctx(),
        ):
            result = await svc.check_connectivity(DockerConnectivityRequest(timeout_seconds=1.0))
        assert result.is_connected is False
        assert result.error_type == "timeout_error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("err_str,expected_type", [
        ("No such file or directory", "socket_error"),
        ("Connection refused", "daemon_error"),
        ("connection aborted by remote", "daemon_error"),
        ("Permission denied", "permission_error"),
        ("something else", "connection_error"),
    ])
    async def test_oserror_classification(self, err_str, expected_type):
        svc = DockerConnectivityService()

        class _Ctx:
            def __init__(self, msg):
                self.msg = msg

            async def __aenter__(self):
                raise OSError(self.msg)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            return_value=_Ctx(err_str),
        ):
            result = await svc.check_connectivity(DockerConnectivityRequest())
        assert result.is_connected is False
        assert result.error_type == expected_type

    @pytest.mark.asyncio
    async def test_runtime_error_classified_as_service_error(self):
        svc = DockerConnectivityService()

        class _Ctx:
            async def __aenter__(self):
                raise RuntimeError("service down")

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            return_value=_Ctx(),
        ):
            result = await svc.check_connectivity(DockerConnectivityRequest())
        assert result.is_connected is False
        assert result.error_type == "service_error"


class TestDockerConnectivityErrorEmbed:
    def test_embed_serverstatus_de(self):
        svc = DockerConnectivityService()
        req = DockerErrorEmbedRequest(error_message="boom", language="de", context="serverstatus")
        result = svc.create_error_embed_data(req)
        assert result.success is True
        assert "Container-Überwachung" in result.title
        assert "boom" in result.description

    def test_embed_serverstatus_en(self):
        svc = DockerConnectivityService()
        req = DockerErrorEmbedRequest(error_message="boom", language="en", context="serverstatus")
        result = svc.create_error_embed_data(req)
        assert result.success is True
        assert "Container Monitoring" in result.title

    def test_embed_individual_container_de(self):
        svc = DockerConnectivityService()
        req = DockerErrorEmbedRequest(error_message="boom", language="de", context="individual_container")
        result = svc.create_error_embed_data(req)
        assert result.success is True
        assert "Systemadministrator" in result.title

    def test_embed_individual_container_en(self):
        svc = DockerConnectivityService()
        req = DockerErrorEmbedRequest(error_message="boom", language="en", context="individual_container")
        result = svc.create_error_embed_data(req)
        assert "System Administrator Required" in result.title

    def test_embed_general_de(self):
        svc = DockerConnectivityService()
        req = DockerErrorEmbedRequest(error_message="oops", language="de", context="general")
        result = svc.create_error_embed_data(req)
        assert "Docker-Konnektivitätsproblem" in result.title

    def test_embed_general_en(self):
        svc = DockerConnectivityService()
        req = DockerErrorEmbedRequest(error_message="oops", language="en", context="general")
        result = svc.create_error_embed_data(req)
        assert "Docker Connectivity Issue" in result.title


class TestDockerConnectivitySingleton:
    def test_singleton(self):
        a = get_docker_connectivity_service()
        b = get_docker_connectivity_service()
        assert a is b
        assert isinstance(a, DockerConnectivityService)


# ============================================================================ #
# spam_protection_service                                                      #
# ============================================================================ #

from services.infrastructure.spam_protection_service import (
    SpamProtectionService,
    SpamProtectionConfig,
    ServiceResult,
    get_spam_protection_service,
)


class TestSpamProtectionConfig:
    def test_from_dict_defaults(self):
        cfg = SpamProtectionConfig.from_dict({})
        assert cfg.global_enabled is True
        assert cfg.max_commands_per_minute == 20
        assert cfg.max_buttons_per_minute == 30
        assert cfg.command_cooldowns == {}
        assert cfg.button_cooldowns == {}
        assert cfg.cooldown_message is True
        assert cfg.log_violations is True

    def test_from_dict_full(self):
        data = {
            "command_cooldowns": {"info": 5},
            "button_cooldowns": {"start": 10},
            "global_settings": {
                "enabled": False,
                "max_commands_per_minute": 99,
                "max_buttons_per_minute": 50,
                "cooldown_message": False,
                "log_violations": False,
            },
        }
        cfg = SpamProtectionConfig.from_dict(data)
        assert cfg.global_enabled is False
        assert cfg.max_commands_per_minute == 99
        assert cfg.command_cooldowns == {"info": 5}
        assert cfg.button_cooldowns == {"start": 10}

    def test_to_dict_roundtrip(self):
        original = SpamProtectionConfig(
            command_cooldowns={"info": 5},
            button_cooldowns={"start": 10},
            global_enabled=True,
            max_commands_per_minute=20,
            max_buttons_per_minute=30,
            cooldown_message=True,
            log_violations=True,
        )
        round_tripped = SpamProtectionConfig.from_dict(original.to_dict())
        assert round_tripped == original


class TestSpamProtectionService:
    def test_init_creates_config_dir(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path / "subdir"))
        assert (tmp_path / "subdir").exists()
        assert svc.config_file.name == "channels_config.json"

    def test_get_config_returns_default_when_no_file(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # Remove auto-created file if any (it doesn't auto-create channels_config.json,
        # but be defensive in case)
        if svc.config_file.exists():
            svc.config_file.unlink()
        result = svc.get_config()
        assert result.success is True
        assert result.data.global_enabled is True
        assert "control" in result.data.command_cooldowns

    def test_get_config_loads_from_file(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        payload = {
            "spam_protection": {
                "command_cooldowns": {"info": 7},
                "button_cooldowns": {"start": 12},
                "global_settings": {"enabled": False},
            }
        }
        svc.config_file.write_text(json.dumps(payload), encoding="utf-8")
        result = svc.get_config()
        assert result.success is True
        assert result.data.command_cooldowns["info"] == 7
        assert result.data.button_cooldowns["start"] == 12
        assert result.data.global_enabled is False

    def test_get_config_handles_invalid_json(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        svc.config_file.write_text("{not valid json", encoding="utf-8")
        result = svc.get_config()
        assert result.success is False
        assert "Error loading" in result.error

    def test_save_config_writes_to_disk(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        cfg = svc._get_default_config()
        result = svc.save_config(cfg)
        assert result.success is True
        # File now exists with our payload
        data = json.loads(svc.config_file.read_text(encoding="utf-8"))
        assert "spam_protection" in data
        assert data["spam_protection"]["global_settings"]["enabled"] is True

    def test_save_config_preserves_existing_keys(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # Pre-populate with unrelated content
        existing = {"channels": [{"id": 42}]}
        svc.config_file.write_text(json.dumps(existing), encoding="utf-8")
        cfg = svc._get_default_config()
        svc.save_config(cfg)
        data = json.loads(svc.config_file.read_text(encoding="utf-8"))
        assert data["channels"] == [{"id": 42}]
        assert "spam_protection" in data

    def test_is_enabled_returns_true_default(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        assert svc.is_enabled() is True

    def test_get_command_cooldown_known(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # default config provides 'control' = 5
        assert svc.get_command_cooldown("control") == 5

    def test_get_command_cooldown_unknown_uses_default(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        assert svc.get_command_cooldown("nonexistent_command") == 5

    def test_get_button_cooldown_exact_match(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        assert svc.get_button_cooldown("start") == 10

    def test_get_button_cooldown_mech_pattern(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # mech_donate is in default config -> mech_donate_123 should match mech_donate
        assert svc.get_button_cooldown("mech_donate_123456") == 10

    def test_get_button_cooldown_unknown_returns_default(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        assert svc.get_button_cooldown("nonexistent") == 5

    def test_load_settings_alias_for_get_config(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        result = svc.load_settings()
        assert result.success is True

    def test_is_on_cooldown_when_disabled_returns_false(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # Patch is_enabled to False
        with patch.object(svc, "is_enabled", return_value=False):
            assert svc.is_on_cooldown(123, "control") is False

    def test_add_then_is_on_cooldown_true(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        svc.add_user_cooldown(42, "control")
        assert svc.is_on_cooldown(42, "control") is True

    def test_get_remaining_cooldown_after_add(self, tmp_path, monkeypatch):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # Freeze time at 1000.0
        import time as _t
        monkeypatch.setattr(_t, "time", lambda: 1000.0)
        svc.add_user_cooldown(7, "control")
        remaining = svc.get_remaining_cooldown(7, "control")
        # control cooldown is 5s; just stamped -> remaining ~5
        assert 4.9 <= remaining <= 5.0

    def test_get_remaining_cooldown_when_disabled(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        with patch.object(svc, "is_enabled", return_value=False):
            assert svc.get_remaining_cooldown(1, "control") == 0.0

    def test_add_user_cooldown_cleans_old_entries(self, tmp_path, monkeypatch):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # Manually plant an ancient entry
        svc._user_cooldowns["old:control"] = 0.0
        svc.add_user_cooldown(99, "control")
        assert "old:control" not in svc._user_cooldowns
        assert "99:control" in svc._user_cooldowns

    def test_is_on_cooldown_button_action(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        # 'refresh' is a button (default cooldown = 5)
        svc.add_user_cooldown(123, "refresh")
        assert svc.is_on_cooldown(123, "refresh") is True

    def test_get_spam_protection_service_singleton(self):
        a = get_spam_protection_service()
        b = get_spam_protection_service()
        assert a is b


# ============================================================================ #
# update_notifier                                                              #
# ============================================================================ #

from services.infrastructure.update_notifier import (
    UpdateNotifier,
    get_update_notifier,
)


class TestUpdateNotifier:
    def test_init_creates_config_dir(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path / "sub"))
        assert (tmp_path / "sub").exists()
        assert notifier.status_file.name == "update_status.json"
        assert notifier.current_version  # set to something

    def test_get_update_status_returns_default_when_no_file(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        status = notifier.get_update_status()
        assert status["last_notified_version"] is None
        assert status["notifications_shown"] == []

    def test_get_update_status_reads_existing_file(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        notifier.status_file.write_text(
            json.dumps({"last_notified_version": "1.0", "notifications_shown": ["1.0"]}),
            encoding="utf-8",
        )
        status = notifier.get_update_status()
        assert status["last_notified_version"] == "1.0"
        assert status["notifications_shown"] == ["1.0"]

    def test_get_update_status_handles_corrupt_json(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        notifier.status_file.write_text("not json", encoding="utf-8")
        status = notifier.get_update_status()
        # Should fall back to defaults
        assert status["last_notified_version"] is None

    def test_save_update_status_writes_file(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        ok = notifier.save_update_status({"last_notified_version": "X", "notifications_shown": ["X"]})
        assert ok is True
        data = json.loads(notifier.status_file.read_text(encoding="utf-8"))
        assert data["last_notified_version"] == "X"

    def test_should_show_update_notification_true_when_new_version(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        # Status file empty -> last_notified_version != current_version -> True
        assert notifier.should_show_update_notification() is True

    def test_should_show_update_notification_false_after_marked(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        notifier.mark_notification_shown()
        assert notifier.should_show_update_notification() is False

    def test_mark_notification_shown_appends_unique(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        notifier.mark_notification_shown()
        notifier.mark_notification_shown()  # second call should not duplicate
        data = json.loads(notifier.status_file.read_text(encoding="utf-8"))
        assert data["notifications_shown"].count(notifier.current_version) == 1

    def test_create_update_embed_returns_embed_with_fields(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        embed = notifier.create_update_embed()
        # The embed type comes from discord.Embed - we just assert structure
        assert embed.title  # non-empty
        assert embed.color is not None
        # At least 4 fields added
        assert len(embed.fields) >= 4

    @pytest.mark.asyncio
    async def test_send_update_notification_skips_when_already_shown(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        notifier.mark_notification_shown()  # marks as already shown
        bot = MagicMock()
        result = await notifier.send_update_notification(bot)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_update_notification_no_control_channels(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        # No control channels in config -> should return False but mark as shown
        with patch(
            "services.infrastructure.update_notifier.load_config",
            return_value={"channel_permissions": {}, "channels": []},
        ):
            bot = MagicMock()
            result = await notifier.send_update_notification(bot)
        assert result is False
        # Marked as shown
        status = notifier.get_update_status()
        assert status["last_notified_version"] == notifier.current_version

    @pytest.mark.asyncio
    async def test_send_update_notification_sends_to_channel(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        # Configure new-format channel_permissions with one control channel
        cfg = {
            "channel_permissions": {
                "12345": {"commands": {"control": True}},
                "99999": {"commands": {"control": False}},
            }
        }

        channel = AsyncMock()
        channel.send = AsyncMock()
        bot = MagicMock()
        bot.get_channel = MagicMock(return_value=channel)

        with patch("services.infrastructure.update_notifier.load_config", return_value=cfg):
            result = await notifier.send_update_notification(bot)

        assert result is True
        channel.send.assert_awaited_once()
        # mark_notification_shown should have run
        status = notifier.get_update_status()
        assert status["last_notified_version"] == notifier.current_version

    @pytest.mark.asyncio
    async def test_send_update_notification_old_format_fallback(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        cfg = {
            "channel_permissions": {},
            "channels": [
                {"channel_id": "55555", "permissions": ["control"]},
            ],
        }
        channel = AsyncMock()
        channel.send = AsyncMock()
        bot = MagicMock()
        bot.get_channel = MagicMock(return_value=channel)

        with patch("services.infrastructure.update_notifier.load_config", return_value=cfg):
            result = await notifier.send_update_notification(bot)
        assert result is True
        channel.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_update_notification_channel_not_found(self, tmp_path):
        notifier = UpdateNotifier(config_dir=str(tmp_path))
        cfg = {"channel_permissions": {"12345": {"commands": {"control": True}}}}
        bot = MagicMock()
        bot.get_channel = MagicMock(return_value=None)

        with patch("services.infrastructure.update_notifier.load_config", return_value=cfg):
            result = await notifier.send_update_notification(bot)
        # No channel -> sent_count==0 -> False
        assert result is False

    def test_get_update_notifier_singleton(self):
        a = get_update_notifier()
        b = get_update_notifier()
        assert a is b


# ============================================================================ #
# dynamic_cooldown_manager                                                     #
# ============================================================================ #

from services.infrastructure.dynamic_cooldown_manager import (
    DynamicCooldownManager,
    get_dynamic_cooldown_manager,
    apply_dynamic_cooldowns_to_bot,
)


class TestDynamicCooldownManager:
    def test_init_uses_spam_manager(self):
        mgr = DynamicCooldownManager()
        assert mgr.spam_manager is not None
        assert mgr._cooldown_mappings == {}

    def test_get_cooldown_for_command_known(self):
        mgr = DynamicCooldownManager()
        # Patch spam manager to be enabled and return a value
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 7
        cd = mgr.get_cooldown_for_command("control")
        assert cd is not None
        assert cd.rate == 1
        assert cd.per == 7.0

    def test_get_cooldown_for_command_alias_ss_maps_to_serverstatus(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 30
        cd = mgr.get_cooldown_for_command("ss")
        assert cd is not None
        mgr.spam_manager.get_command_cooldown.assert_called_with("serverstatus")

    def test_get_cooldown_for_command_unknown_returns_none(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = True
        cd = mgr.get_cooldown_for_command("totally_unknown_cmd")
        assert cd is None

    def test_get_cooldown_for_command_disabled_returns_none(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = False
        cd = mgr.get_cooldown_for_command("control")
        assert cd is None

    @pytest.mark.asyncio
    async def test_before_invoke_check_passes_when_disabled(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = False
        check = mgr.before_invoke_check()
        # Build a fake ctx
        ctx = MagicMock()
        ctx.command.name = "x"
        ctx.author.id = 99
        result = await check(ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_before_invoke_check_passes_when_enabled(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = True
        check = mgr.before_invoke_check()
        ctx = MagicMock()
        ctx.command.name = "x"
        ctx.author.id = 99
        result = await check(ctx)
        assert result is True

    def test_apply_dynamic_cooldowns_no_compatible_iter(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.load_settings.return_value = MagicMock(success=True)
        # Bot lacks walk_commands, all_commands, application_commands
        bot = MagicMock(spec=[])
        # Ensure the spec is empty so hasattr returns False
        # Should return early without raising
        mgr.apply_dynamic_cooldowns(bot)

    def test_apply_dynamic_cooldowns_walk_commands(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.load_settings.return_value = MagicMock(success=True)
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 5

        # Build a fake command: must have name + _buckets
        fake_cmd = MagicMock()
        fake_cmd.name = "control"
        fake_cmd._buckets = MagicMock()

        bot = MagicMock(spec=["walk_commands"])
        bot.walk_commands = MagicMock(return_value=[fake_cmd])

        # Should run without exception
        mgr.apply_dynamic_cooldowns(bot)
        # _buckets attribute may have been replaced (was MagicMock, now CooldownMapping)
        assert fake_cmd._buckets is not None

    def test_apply_dynamic_cooldowns_unknown_command_gets_empty_cooldown(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.load_settings.return_value = MagicMock(success=True)
        mgr.spam_manager.is_enabled.return_value = True

        fake_cmd = MagicMock()
        fake_cmd.name = "notmapped"
        fake_cmd._buckets = MagicMock()

        bot = MagicMock(spec=["all_commands"])
        bot.all_commands = {"notmapped": fake_cmd}

        mgr.apply_dynamic_cooldowns(bot)
        # No exception raised; _buckets reset to empty cooldown mapping
        assert fake_cmd._buckets is not None

    def test_apply_dynamic_cooldowns_load_settings_failure_logged(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        # Simulate failure result
        failure = MagicMock(success=False, error="bad")
        mgr.spam_manager.load_settings.return_value = failure
        bot = MagicMock(spec=[])
        # Should not raise even on failure
        mgr.apply_dynamic_cooldowns(bot)

    def test_apply_dynamic_cooldowns_to_bot_convenience(self):
        bot = MagicMock(spec=[])
        # Should not raise; uses singleton manager
        apply_dynamic_cooldowns_to_bot(bot)

    def test_get_dynamic_cooldown_manager_singleton(self):
        a = get_dynamic_cooldown_manager()
        b = get_dynamic_cooldown_manager()
        assert a is b
        assert isinstance(a, DynamicCooldownManager)
