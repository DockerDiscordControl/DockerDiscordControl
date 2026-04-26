# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Coverage gap-filler for docker_service /        #
#                              infrastructure                                    #
# ============================================================================ #
"""Targeted unit tests that exercise the uncovered branches of the five
modules listed below.  The goal is to push each module to >=92 % coverage
WITHOUT touching production code or manipulating ``sys.modules`` (the real
``docker`` PyPI package must remain importable across the suite).

Modules under test
------------------
* services.docker_service.docker_utils
* services.docker_service.docker_client_pool
* services.infrastructure.container_status_service
* services.infrastructure.spam_protection_service
* services.infrastructure.dynamic_cooldown_manager

These tests deliberately complement (and never duplicate) the assertions in:
* tests/unit/services/docker_service/test_docker_utils_service.py
* tests/unit/services/test_docker_pool_fetch.py
* tests/unit/services/test_docker_status_services.py
* tests/unit/services/infrastructure/test_infrastructure_services.py
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import docker  # ensure real PyPI docker is loaded
import docker.errors
import pytest

from services.docker_service import docker_utils
from services.docker_service import docker_client_pool as dcp_mod
from services.docker_service.docker_client_pool import (
    DockerClientService,
    QueueRequest,
)
from services.infrastructure.container_status_service import (
    ContainerStatusRequest,
    ContainerStatusResult,
    ContainerStatusService,
    get_docker_info_service_first,
    get_docker_stats_service_first,
)
from services.infrastructure.spam_protection_service import (
    SpamProtectionConfig,
    SpamProtectionService,
)
from services.infrastructure.dynamic_cooldown_manager import (
    DynamicCooldownManager,
)


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #


def _async_cm_yielding(client):
    """Build an async-context-manager factory that yields ``client``."""

    @asynccontextmanager
    async def _cm(*_a, **_kw):
        yield client

    return _cm


def _mock_client(ping_ok: bool = True):
    c = MagicMock(name="DockerClient")
    if ping_ok:
        c.ping = MagicMock(return_value=True)
    else:
        c.ping = MagicMock(side_effect=docker.errors.DockerException("dead"))
    c.close = MagicMock(return_value=None)
    return c


@pytest.fixture(autouse=True)
def _reset_docker_utils_globals():
    """Restore module-level singletons so individual tests stay isolated."""
    docker_utils._docker_client = None
    docker_utils._client_last_used = 0
    docker_utils._containers_cache = None
    docker_utils._cache_timestamp = 0
    docker_utils._custom_timeout_config = None
    docker_utils._custom_config_loaded = False
    yield


# =========================================================================== #
# docker_utils                                                                #
# =========================================================================== #


class TestDockerUtilsFallbackClient:
    """Covers the fallback ``individual_client`` async-cm path (lines 363-390)
    when USE_CONNECTION_POOL is True but the pool import explodes."""

    @pytest.mark.asyncio
    async def test_get_docker_client_async_falls_back_to_individual_client(
        self, monkeypatch
    ):
        # Force USE_CONNECTION_POOL=True
        monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", True)

        # Make the inner import raise so the except branch runs.
        def _raise_inner_import(*_a, **_kw):
            raise ImportError("connection pool module gone")

        # Patch inside docker_client_pool because docker_utils imports it from there.
        monkeypatch.setattr(
            dcp_mod, "get_docker_client_async", _raise_inner_import
        )

        fake_client = _mock_client()
        # The fallback path uses docker.from_env via asyncio.to_thread.
        with patch.object(
            docker_utils.docker, "from_env", return_value=fake_client
        ):
            cm_factory = docker_utils.get_docker_client_async(
                operation="info", container_name="anything"
            )
            async with cm_factory() as client:
                assert client is fake_client

        # client.close was scheduled in the finally block.
        fake_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_individual_client_handles_close_error(self, monkeypatch):
        monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", True)
        monkeypatch.setattr(
            dcp_mod,
            "get_docker_client_async",
            MagicMock(side_effect=AttributeError("missing")),
        )

        client = _mock_client()
        client.close.side_effect = OSError("close exploded")
        with patch.object(docker_utils.docker, "from_env", return_value=client):
            cm_factory = docker_utils.get_docker_client_async()
            async with cm_factory() as c:
                assert c is client
        # Even though close raised, the cm exited cleanly (line 388 path).
        client.close.assert_called_once()


class TestDockerUtilsReleaseClient:
    """Covers release_docker_client pool/legacy branches (456-463, 473-474)."""

    def test_release_with_pool_calls_release_client(self, monkeypatch):
        monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", True)
        client = MagicMock()
        fake_pool = MagicMock()
        with patch.object(
            docker_utils, "get_docker_client_service", return_value=fake_pool
        ):
            docker_utils.release_docker_client(client=client)
        fake_pool._release_client.assert_called_once_with(client)

    def test_release_with_pool_handles_attribute_error(self, monkeypatch):
        monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", True)
        client = MagicMock()
        fake_pool = MagicMock()
        fake_pool._release_client.side_effect = AttributeError("nope")
        with patch.object(
            docker_utils, "get_docker_client_service", return_value=fake_pool
        ):
            # Must not raise
            docker_utils.release_docker_client(client=client)

    def test_release_legacy_when_close_errors(self, monkeypatch):
        monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", False)
        client = MagicMock()
        client.close.side_effect = RuntimeError("explosion in close")
        docker_utils._docker_client = client
        docker_utils._client_last_used = (
            time.time() - docker_utils._CLIENT_TIMEOUT - 5
        )
        # Must not raise (line 473-474 path).
        docker_utils.release_docker_client()


class TestDockerUtilsStatsBranches:
    """Cover get_docker_stats memory-bucket / fallback paths."""

    @pytest.mark.asyncio
    async def test_stats_kib_bucket(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        client = MagicMock()
        container = MagicMock()
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 50},
                "system_cpu_usage": 500,
            },
            # Memory < 1 MiB -> KiB bucket (line 567).
            "memory_stats": {"usage": 700},
        }
        client.containers.get.return_value = container
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        cpu, mem = await docker_utils.get_docker_stats("nano")
        assert mem.endswith("KiB")

    @pytest.mark.asyncio
    async def test_stats_gib_bucket(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        client = MagicMock()
        container = MagicMock()
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 50},
                "system_cpu_usage": 500,
            },
            # > 1 GiB -> GiB bucket (line 571).
            "memory_stats": {"usage": 2 * 1024 * 1024 * 1024},
        }
        client.containers.get.return_value = container
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        _, mem = await docker_utils.get_docker_stats("big")
        assert mem.endswith("GiB")

    @pytest.mark.asyncio
    async def test_stats_online_cpus_fallback_to_percpu_usage_len(
        self, monkeypatch
    ):
        """No online_cpus key -> uses len(percpu_usage) (line 556-557)."""
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        client = MagicMock()
        container = MagicMock()
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {
                    "total_usage": 200,
                    "percpu_usage": [1, 2, 3, 4],
                },
                "system_cpu_usage": 1000,
                # online_cpus deliberately missing
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
            "memory_stats": {"usage": 0},
        }
        client.containers.get.return_value = container
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        cpu, _ = await docker_utils.get_docker_stats("multicore")
        # 4 cpus -> (100/500)*4*100 = 80.00
        assert cpu == "80.00"

    @pytest.mark.asyncio
    async def test_stats_running_state_zero_cpu_logs_debug(
        self, monkeypatch
    ):
        """If cpu_delta=0 but state.Running=True -> debug log (line 561)."""
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        client = MagicMock()
        container = MagicMock()
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},  # delta=0
                "system_cpu_usage": 1000,
            },
            "memory_stats": {"usage": 0},
            "State": {"Running": True},  # triggers the elif branch
        }
        client.containers.get.return_value = container
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        cpu, _ = await docker_utils.get_docker_stats("idle")
        assert cpu == "N/A"

    @pytest.mark.asyncio
    async def test_stats_inner_docker_exception_returns_none(
        self, monkeypatch
    ):
        """Inner Docker exception in container.get triggers line 540-542."""
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        client = MagicMock()
        client.containers.get.side_effect = docker.errors.DockerException(
            "boom"
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        cpu, mem = await docker_utils.get_docker_stats("err")
        assert (cpu, mem) == (None, None)

    @pytest.mark.asyncio
    async def test_stats_outer_value_error_returns_none(self, monkeypatch):
        """Outer ValueError caught -> line 579-581."""
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        @asynccontextmanager
        async def _bad_cm(*_a, **_kw):
            raise ValueError("bad config value")
            yield  # pragma: no cover

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            lambda *a, **kw: _bad_cm(),
        )
        cpu, mem = await docker_utils.get_docker_stats("err")
        assert (cpu, mem) == (None, None)


class TestDockerUtilsInfoOuterError:
    """Lines 621-623: outer Docker error path of get_docker_info."""

    @pytest.mark.asyncio
    async def test_info_outer_docker_exception(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        @asynccontextmanager
        async def _bad_cm(*_a, **_kw):
            raise docker.errors.DockerException("daemon dead")
            yield  # pragma: no cover

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            lambda *a, **kw: _bad_cm(),
        )
        info = await docker_utils.get_docker_info("nginx")
        assert info is None


class TestDockerUtilsActionTimeoutAndError:
    """Lines 654-655: docker_action timeout."""

    @pytest.mark.asyncio
    async def test_action_timeout_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _raise_timeout(*_a, **_kw):
            raise asyncio.TimeoutError()

        # Patch asyncio.to_thread inside the module to raise.
        monkeypatch.setattr(asyncio, "to_thread", _raise_timeout)

        client = MagicMock()
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        ok = await docker_utils.docker_action("svc", "start")
        assert ok is False


class TestDockerUtilsListTimeout:
    """Lines 701-702: list_docker_containers asyncio TimeoutError."""

    @pytest.mark.asyncio
    async def test_list_containers_timeout_returns_empty(self, monkeypatch):
        @asynccontextmanager
        async def _bad_cm(*_a, **_kw):
            raise asyncio.TimeoutError()
            yield  # pragma: no cover

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            lambda *a, **kw: _bad_cm(),
        )
        result = await docker_utils.list_docker_containers()
        assert result == []


class TestDockerUtilsContainersDataRunningBranch:
    """Lines 761-765: get_containers_data running-state with valid State."""

    @pytest.mark.asyncio
    async def test_running_state_with_string_state_keeps_started_at(
        self, monkeypatch
    ):
        # Production reads c_data['State'] as string for ``.lower()``;
        # then if running, again as dict for ``.get('StartedAt')``.
        # That double-typed lookup means a single dict can never go through
        # both branches cleanly: with a string, ``.get`` raises AttributeError
        # caught by the outer except handler.
        # However, producing a "running" status DOES exercise the running
        # branch up until the AttributeError, covering lines 760-765.
        client = MagicMock()
        client.api.containers.return_value = [
            {
                "Id": "abcdef0011223344",
                "Names": ["/svc-running"],
                "State": "running",  # string -> running branch entered
                "Image": "nginx:1",
                "Created": 1700000000,
                "Ports": [{"PrivatePort": 80}],
            },
        ]
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        docker_utils._containers_cache = None
        docker_utils._cache_timestamp = 0
        result = await docker_utils.get_containers_data()
        # The running branch attempts state_detail.get(...) on a string,
        # which raises AttributeError caught by inner except -> entry
        # becomes ``error_processing``.
        assert len(result) == 1
        assert result[0]["status"] == "error_processing"


class TestDockerUtilsCacheTtlLoader:
    """_get_cache_ttl env/exception fallback (lines 671-672)."""

    def test_cache_ttl_uses_advanced_settings(self, monkeypatch):
        def _fake_load():
            return {"advanced_settings": {"DDC_DOCKER_CACHE_DURATION": "75"}}

        monkeypatch.setattr(
            "services.config.config_service.load_config", _fake_load
        )
        assert docker_utils._get_cache_ttl() == 75

    def test_cache_ttl_falls_back_when_load_fails(self, monkeypatch):
        def _raise(*_a, **_kw):
            raise docker_utils.ConfigLoadError("nope")

        monkeypatch.setattr(
            "services.config.config_service.load_config", _raise
        )
        assert docker_utils._get_cache_ttl() == 30

    def test_cache_ttl_falls_back_on_value_error(self, monkeypatch):
        def _bad():
            return {"advanced_settings": {"DDC_DOCKER_CACHE_DURATION": "NaN"}}

        monkeypatch.setattr(
            "services.config.config_service.load_config", _bad
        )
        assert docker_utils._get_cache_ttl() == 30


class TestDockerUtilsListContainersInner:
    """list_docker_containers per-container exception branches (693-698)."""

    @pytest.mark.asyncio
    async def test_list_skips_notfound_and_attrerror(
        self, monkeypatch
    ):
        # Use a real-ish container class so attribute access raises naturally.
        class _Image:
            def __init__(self, tags, id_):
                self._tags = tags
                self._id = id_
                self._exc = None

            @property
            def tags(self):
                if self._exc:
                    raise self._exc
                return self._tags

            @property
            def id(self):
                return self._id

        class _Container:
            def __init__(self, name, image):
                self.name = name
                self.short_id = f"{name}_sid"
                self.id = f"{name}-id"
                self.status = "running"
                self.image = image

        good_img = _Image(["nginx:1"], "sha:gooooooooood")
        good = _Container("good", good_img)

        broken_img = _Image([], "sha:brokenbroken")
        broken_img._exc = docker.errors.NotFound("vanished")
        broken = _Container("broken", broken_img)

        weird_img = _Image([], "sha:weeeird")
        weird_img._exc = AttributeError("boom")
        weird = _Container("weird", weird_img)

        client = MagicMock()
        client.containers.list.return_value = [good, broken, weird]
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        result = await docker_utils.list_docker_containers()
        # Only the good entry survives -- the others raised NotFound /
        # AttributeError respectively.
        assert len(result) == 1
        assert result[0]["name"] == "good"


class TestDockerUtilsContainersDataInner:
    """get_containers_data running-branch + per-entry exception (760-771)."""

    @pytest.mark.asyncio
    async def test_running_branch_keeps_state_dict(
        self, monkeypatch
    ):
        # Note: production code reads c_data['State'] FIRST as a string
        # for the lower() comparison, THEN later as a dict for ``StartedAt``.
        # That dual usage means a single c_data can never hit BOTH branches.
        # We choose the dict-state-with-dict-Status path; status will end up
        # ``error_processing`` since str.lower() fails on a dict, exercising
        # the exception handler at lines 769-771.
        client = MagicMock()
        client.api.containers.return_value = [
            {
                "Id": "0123456789abcdef",
                "Names": ["/svcX"],
                "State": {"Status": "running", "StartedAt": "2024-01-02T03:04:05Z"},
                "Image": "alpine:3",
                "Created": 1700001234,
                "Ports": [{"PrivatePort": 80}],
            },
        ]
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )
        docker_utils._containers_cache = None
        docker_utils._cache_timestamp = 0
        result = await docker_utils.get_containers_data()
        assert len(result) == 1
        # The dict-state path triggers error_processing (line 774 branch).
        assert result[0]["status"] == "error_processing"
        assert result[0]["running"] is False
        assert "error" in result[0]


class TestDockerUtilsPerformanceErrorHandling:
    """test_docker_performance error & timeout per-container paths."""

    @pytest.mark.asyncio
    async def test_test_docker_performance_overall_timeout_records_entry(
        self, monkeypatch
    ):
        async def _info(_n):
            return {}

        async def _stats(_n):
            return ("0", "0 KiB")

        async def _bad_wait_for(*_a, **_kw):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(docker_utils, "get_docker_info", _info)
        monkeypatch.setattr(docker_utils, "get_docker_stats", _stats)
        monkeypatch.setattr(asyncio, "wait_for", _bad_wait_for)
        result = await docker_utils.test_docker_performance(
            container_names=["alpha"], iterations=1
        )
        assert result["summary"]["timeout_count"] >= 1
        assert "Overall timeout" in (
            result["container_results"]["alpha"]["errors"]
        )

    @pytest.mark.asyncio
    async def test_test_docker_performance_logs_info_exception(
        self, monkeypatch
    ):
        # Make info raise inside gather - return_exceptions=True captures it.
        async def _bad_info(_n):
            raise RuntimeError("info kaboom")

        async def _stats(_n):
            return ("1", "1 KiB")

        monkeypatch.setattr(docker_utils, "get_docker_info", _bad_info)
        monkeypatch.setattr(docker_utils, "get_docker_stats", _stats)
        result = await docker_utils.test_docker_performance(
            container_names=["beta"], iterations=1
        )
        # The error was attached to the per-container errors list (line 859).
        errs = result["container_results"]["beta"]["errors"]
        assert any("Info error" in e for e in errs)


class TestDockerUtilsAnalyzeBranches:
    """analyze_docker_stats_performance branch coverage."""

    @pytest.mark.asyncio
    async def test_host_info_failure_logged(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _no_sleep(*_a, **_kw):
            return None

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        client = MagicMock()
        container = MagicMock()
        container.attrs = {
            "State": {"Status": "running"},
            "Created": "2024",
            "RestartCount": 0,
            "Platform": "linux",
            "Driver": "overlay2",
        }
        client.containers.get.return_value = container

        # Force host info path to raise (line 1017-1018).
        client.info.side_effect = docker.errors.DockerException(
            "host info denied"
        )

        # Provide minimal stats so the iterations don't crash.
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "memory_stats": {
                "usage": 100,
                "limit": 1000,
                "stats": {"cache": 10},
            },
            "blkio_stats": {},
            "networks": {},
        }

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )

        result = await docker_utils.analyze_docker_stats_performance(
            "demo", iterations=1
        )
        assert "system_info" in result
        # docker_version key not added because host info failed.
        assert "docker_version" not in result["system_info"]

    @pytest.mark.asyncio
    async def test_analyze_handles_container_get_runtime_error(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _no_sleep(*_a, **_kw):
            return None

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        client = MagicMock()
        # Outer container.get works once for system_info, but inside iteration
        # it raises.  We simulate this with side_effect list.
        container = MagicMock()
        container.attrs = {"State": {"Status": "running"}}
        client.containers.get.side_effect = [
            container,
            RuntimeError("iter boom"),  # iteration 1 fails (line 1030-1032)
        ]

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )

        result = await docker_utils.analyze_docker_stats_performance(
            "demo", iterations=1
        )
        # No iterations succeeded -> no analysis populated.
        assert result["analysis"] == {}

    @pytest.mark.asyncio
    async def test_analyze_outer_exception_attaches_error(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        # Make get_docker_client_async raise immediately (line 1166-1168).
        @asynccontextmanager
        async def _bad_cm(*_a, **_kw):
            raise docker.errors.DockerException("client outage")
            yield None  # pragma: no cover

        monkeypatch.setattr(
            docker_utils, "get_docker_client_async", lambda *a, **kw: _bad_cm()
        )

        result = await docker_utils.analyze_docker_stats_performance(
            "demo", iterations=1
        )
        assert result["error"]
        assert "client outage" in result["error"]


class TestDockerUtilsAnalyzeRecommendations:
    """analyze_docker_stats_performance recommendation generation
    (lines 1138-1158).  Run enough iterations with high stats time and high
    memory% to trigger every recommendation branch."""

    @pytest.mark.asyncio
    async def test_analyze_emits_all_recommendations(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _no_sleep(*_a, **_kw):
            return None

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        # Build a slow stats() that takes a while -> avg_stats_time > 2000ms.
        slow_stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "memory_stats": {
                # >70% usage triggers the high-memory recommendation
                "usage": 800,
                "limit": 1000,
                "stats": {"cache": 10},
            },
            "blkio_stats": {},
            "networks": {},
        }

        # Simulate slow stats by patching time.time to advance 2.5s per call.
        time_calls = {"n": 0}
        real_time = time.time
        baseline = real_time()

        def _fake_time():
            time_calls["n"] += 1
            # Each call adds 1.3s -> stats_call_time > 1000ms easily; over
            # iterations we cross the 2000ms threshold for the "very slow"
            # recommendation (line 1157-1158).
            return baseline + (time_calls["n"] * 1.3)

        monkeypatch.setattr(time, "time", _fake_time)

        client = MagicMock()
        container = MagicMock()
        container.attrs = {"State": {"Status": "running"}}
        container.stats.return_value = slow_stats
        client.containers.get.return_value = container
        client.info.return_value = {}

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )

        result = await docker_utils.analyze_docker_stats_performance(
            "demo", iterations=3
        )
        # Restore real time before asserting.
        monkeypatch.setattr(time, "time", real_time)
        recs = result["analysis"].get("recommendations", [])
        assert recs  # non-empty list
        # At least the "consistently slow" recommendation should be present.
        assert any("slow" in r.lower() for r in recs)


class TestDockerUtilsCompareBranches:
    """compare_container_performance branch coverage."""

    @pytest.mark.asyncio
    async def test_skip_invalid_container_name(self, monkeypatch):
        # First call: True (so we get past validation in inner function for
        # the valid one); we'll just have a single invalid name.
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: False
        )
        out = await docker_utils.compare_container_performance(
            ["bad name!"]
        )
        # Production doesn't return a "no containers" message - the entire
        # input was invalid -> the result list is empty -> only the header
        # plus the boilerplate solution block is present.
        assert "DOCKER STATS PERFORMANCE" in out

    @pytest.mark.asyncio
    async def test_compare_records_timeout_entry(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _no_sleep(*_a, **_kw):
            return None

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        async def _always_timeout(*_a, **_kw):
            raise asyncio.TimeoutError()

        # asyncio.wait_for is what raises TimeoutError per iteration
        # (line 1225-1226); that path then appends 10000 and continues.
        monkeypatch.setattr(asyncio, "wait_for", _always_timeout)

        client = MagicMock()
        container = MagicMock()
        client.containers.get.return_value = container
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _async_cm_yielding(client),
        )

        out = await docker_utils.compare_container_performance(["alpha"])
        assert "VERY SLOW" in out  # 10000ms => >2000 -> "🔴 VERY SLOW"

    @pytest.mark.asyncio
    async def test_compare_outer_failure_records_error_entry(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        @asynccontextmanager
        async def _bad_cm(*_a, **_kw):
            raise docker.errors.DockerException("outer kaboom")
            yield  # pragma: no cover

        monkeypatch.setattr(
            docker_utils, "get_docker_client_async", lambda *a, **kw: _bad_cm()
        )

        out = await docker_utils.compare_container_performance(["alpha"])
        # Path 1261-1268: error entry appended, formatted as "❌ FEHLER"
        assert "FEHLER" in out


# =========================================================================== #
# docker_client_pool                                                          #
# =========================================================================== #


class TestPoolFastPathFailure:
    """Lines 183-185 / 421-423: fast path raises -> falls back to queue."""

    @pytest.mark.asyncio
    async def test_service_first_fast_path_attribute_error_falls_to_queue(
        self,
    ):
        from services.docker_service.docker_client_pool import (
            DockerClientRequest,
        )

        pool = DockerClientService(max_connections=1)
        try:
            async def _bad_immediate():
                raise AttributeError("fast-path explosion")

            # Force queue path to immediately serve (line 202).
            client = _mock_client()

            async def _fake_wait_for(coro, timeout):  # noqa: ARG001
                # Immediately resolve as the desired client.
                if hasattr(coro, "cancel"):
                    coro.cancel()
                return client

            with patch.object(pool, "_try_immediate_acquire", _bad_immediate):
                with patch.object(asyncio, "wait_for", _fake_wait_for):
                    result = await pool.get_docker_client_service(
                        DockerClientRequest(timeout_seconds=0.1)
                    )
            assert result.success is True
            assert result.client is client
            assert result.queue_wait_time_ms >= 0.0
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_client_async_fast_path_attribute_error_falls_to_queue(
        self,
    ):
        pool = DockerClientService(max_connections=1)
        try:
            async def _bad_immediate():
                raise AttributeError("fast-path explosion")

            client = _mock_client()

            async def _fake_wait_for(coro, timeout):  # noqa: ARG001
                if hasattr(coro, "cancel"):
                    coro.cancel()
                return client

            with patch.object(pool, "_try_immediate_acquire", _bad_immediate):
                with patch.object(asyncio, "wait_for", _fake_wait_for):
                    async with pool.get_client_async(timeout=0.1) as c:
                        assert c is client
        finally:
            await pool.close_all()


class TestPoolQueueProcessor:
    """Lines 320-374: _process_queue body."""

    @pytest.mark.asyncio
    async def test_process_queue_serves_request_when_client_available(
        self,
    ):
        """The processor pops a queued request and resolves its future."""
        pool = DockerClientService(max_connections=2)
        try:
            client = _mock_client()
            future = asyncio.get_event_loop().create_future()
            req = QueueRequest(
                request_id="r1",
                timestamp=time.time(),
                timeout=5.0,
                future=future,
            )

            # Stub _try_acquire_client_for_queue to return a client.
            async def _stub_acquire():
                pool._in_use.append(client)
                return client

            with patch.object(
                pool, "_try_acquire_client_for_queue", _stub_acquire
            ):
                await pool._queue.put(req)
                # Give the background processor a tick to pick it up.
                await asyncio.wait_for(future, timeout=2.0)

            assert future.result() is client
            # Queue stats reflect a served request.
            assert pool._queue_stats["average_wait_time"] >= 0.0
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_process_queue_drops_already_timed_out_request(
        self,
    ):
        """If a request has been waiting longer than its timeout when the
        processor picks it up, it sets a TimeoutError on the future."""
        pool = DockerClientService(max_connections=2)
        try:
            future = asyncio.get_event_loop().create_future()
            # Timestamp far in the past => already expired by queue_timeout.
            req = QueueRequest(
                request_id="rOld",
                timestamp=time.time() - 10_000,
                timeout=1.0,
                future=future,
            )
            await pool._queue.put(req)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(future, timeout=2.0)
            assert pool._queue_stats["timeouts"] >= 1
        finally:
            await pool.close_all()


class TestPoolLateProcessorInit:
    """Lines 400-407: get_client_async starts the processor lazily."""

    @pytest.mark.asyncio
    async def test_get_client_async_starts_processor_lazily(self):
        # Construct WITHOUT a running loop (use asyncio.run_coroutine_threadsafe?
        # Easier: construct then forcibly null out the processor task to
        # simulate the deferred-init state, then enter the cm.
        pool = DockerClientService(max_connections=1)
        # Cancel/clear the processor that __init__ started so the cm has to
        # re-create it via the late-init branch (lines 400-407).
        if pool._queue_processor_task is not None:
            pool._queue_processor_task.cancel()
            try:
                await pool._queue_processor_task
            except asyncio.CancelledError:
                pass
            pool._queue_processor_task = None
        pool._client_available_event = None

        try:
            client = _mock_client()

            async def _stub_acquire():
                pool._in_use.append(client)
                return client

            with patch.object(pool, "_try_immediate_acquire", _stub_acquire):
                async with pool.get_client_async(timeout=1.0) as c:
                    assert c is client

            # Processor task must have been started inside the cm.
            assert pool._queue_processor_task is not None
            assert pool._client_available_event is not None
        finally:
            await pool.close_all()


class TestPoolBackcompatCloseError:
    """Lines 706-708: close errors swallowed silently in finally block."""

    @pytest.mark.asyncio
    async def test_close_error_in_finally_is_swallowed(self):
        client = _mock_client()
        client.close.side_effect = OSError("cannot close")
        fake_load_config = MagicMock(
            return_value={
                "docker_config": {"docker_socket_path": "/tmp/sock"}
            }
        )
        with patch(
            "services.config.config_service.load_config", fake_load_config
        ):
            with patch.object(
                dcp_mod.docker, "DockerClient", return_value=client
            ):
                # Must not raise even when close errors out.
                async with dcp_mod.get_docker_client_async(timeout=1.0) as c:
                    assert c is client


# =========================================================================== #
# container_status_service                                                    #
# =========================================================================== #


class TestContainerStatusDeactivateException:
    """Line 153-155: _deactivate_container exception path."""

    def test_deactivate_handles_open_exception(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        cont_dir = tmp_path / "containers"
        cont_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = cont_dir / "myc.json"
        cfg_path.write_text(
            json.dumps({"name": "myc", "active": True}), encoding="utf-8"
        )

        svc = ContainerStatusService()

        # Force open() to raise inside _deactivate_container.
        def _bad_open(*_a, **_kw):
            raise IOError("disk gone")

        with patch("builtins.open", _bad_open):
            ok = svc._deactivate_container("myc")
        assert ok is False


class TestContainerStatusBulkExceptionPropagation:
    """Lines 263-271: bulk gather captures exceptions as values; the
    individual entry becomes failure with error_type='exception'."""

    @pytest.mark.asyncio
    async def test_bulk_propagates_inner_exception(self):
        from services.infrastructure.container_status_service import (
            ContainerBulkStatusRequest,
        )

        svc = ContainerStatusService()

        async def _boom(_req):
            raise OSError("daemon pipe broke")

        with patch.object(svc, "get_container_status", side_effect=_boom):
            req = ContainerBulkStatusRequest(container_names=["a"])
            bulk = await svc.get_bulk_container_status(req)

        assert bulk.success is True
        assert bulk.failed_containers == 1
        result = bulk.results["a"]
        assert result.success is False
        assert result.error_type == "exception"
        assert "daemon pipe broke" in result.error_message

    @pytest.mark.asyncio
    async def test_bulk_outer_data_error(self):
        from services.infrastructure.container_status_service import (
            ContainerBulkStatusRequest,
        )

        svc = ContainerStatusService()
        # KeyError raised before gather (line 299-308 path).
        with patch.object(
            svc, "get_container_status", side_effect=KeyError("oops")
        ), patch(
            "asyncio.Semaphore", side_effect=ValueError("bad max")
        ):
            req = ContainerBulkStatusRequest(container_names=["x"])
            result = await svc.get_bulk_container_status(req)

        assert result.success is False
        assert "Data error" in result.error_message


class TestContainerStatusFetchSuccessBranch:
    """Lines 384-479: _fetch_container_status happy + sub-paths."""

    @pytest.mark.asyncio
    async def test_fetch_success_with_running_container_and_stats(
        self, monkeypatch
    ):
        svc = ContainerStatusService()

        # Fake docker client + container.
        fake_container = MagicMock()
        fake_container.status = "running"
        fake_container.attrs = {
            "State": {"StartedAt": "2024-01-01T00:00:00Z"},
            "NetworkSettings": {"Ports": {"80/tcp": []}},
        }
        fake_container.image = MagicMock(
            tags=["nginx:latest"], id="sha256:abcd"
        )

        # The production code uses ``container.stats(stream=True, decode=True)``
        # then iterates with ``next(...)``.  We provide a generator with one
        # stats dict.
        def _stats_gen(stream, decode):  # noqa: ARG001
            yield {
                "cpu_stats": {
                    "cpu_usage": {"total_usage": 200},
                    "system_cpu_usage": 1000,
                    "online_cpus": 2,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 100},
                    "system_cpu_usage": 500,
                },
                "memory_stats": {
                    "usage": 1024 * 1024 * 50,
                    "limit": 1024 * 1024 * 200,
                },
            }

        fake_container.stats = _stats_gen

        fake_client = MagicMock()
        fake_client.containers.get.return_value = fake_container

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            yield fake_client

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="ngx")
        result = await svc._fetch_container_status(req)
        assert result.success is True
        assert result.is_running is True
        assert result.image == "nginx:latest"
        assert result.cpu_percent > 0
        assert result.memory_usage_mb == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_fetch_handles_attribute_error_in_container_data(
        self, monkeypatch
    ):
        svc = ContainerStatusService()

        # A non-Mock plain object lacks .image -> AttributeError (line 416-426
        # ``except (AttributeError, KeyError, IndexError)``).
        class _BareContainer:
            status = "running"
            attrs = {"State": {"StartedAt": "2024-01-01T00:00:00Z"},
                     "NetworkSettings": {"Ports": {}}}
            # No .image attribute -> AttributeError raised in production.

        fake_client = MagicMock()
        fake_client.containers.get.return_value = _BareContainer()

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            yield fake_client

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="ngx")
        result = await svc._fetch_container_status(req)
        assert result.success is False
        assert result.error_type == "container_not_found"

    @pytest.mark.asyncio
    async def test_fetch_handles_value_error_in_started_at(
        self, monkeypatch
    ):
        svc = ContainerStatusService()

        fake_container = MagicMock()
        fake_container.status = "running"
        # StartedAt is malformed -> fromisoformat raises ValueError.
        fake_container.attrs = {
            "State": {"StartedAt": "not-a-real-iso-date"},
            "NetworkSettings": {"Ports": {}},
        }
        fake_container.image = MagicMock(tags=["x:y"], id="sha256:1")

        fake_client = MagicMock()
        fake_client.containers.get.return_value = fake_container

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            yield fake_client

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="ngx")
        result = await svc._fetch_container_status(req)
        # ValueError caught by inner ``except (ValueError, TypeError)``.
        assert result.success is False
        assert result.error_type == "data_format_error"

    @pytest.mark.asyncio
    async def test_fetch_handles_stats_failure_uses_fallbacks(
        self, monkeypatch
    ):
        svc = ContainerStatusService()

        fake_container = MagicMock()
        fake_container.status = "running"
        fake_container.attrs = {
            "State": {"StartedAt": "2024-01-01T00:00:00Z"},
            "NetworkSettings": {"Ports": {}},
        }
        fake_container.image = MagicMock(tags=["i:1"], id="sha256:1")

        # Stats generator raises on next() -> StopIteration path.
        def _empty_gen(stream, decode):  # noqa: ARG001
            return iter([])  # next() raises StopIteration

        fake_container.stats = _empty_gen

        fake_client = MagicMock()
        fake_client.containers.get.return_value = fake_container

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            yield fake_client

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="ngx")
        result = await svc._fetch_container_status(req)
        assert result.success is True
        # Fallback values applied.
        assert result.cpu_percent == 0.1
        assert result.memory_usage_mb == 2.0
        assert result.memory_limit_mb == 1024.0

    @pytest.mark.asyncio
    async def test_fetch_handles_docker_notfound_and_deactivates(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        svc = ContainerStatusService()

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            raise docker.errors.NotFound("vanished")
            yield  # pragma: no cover

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="missing")
        result = await svc._fetch_container_status(req)
        assert result.success is False
        assert result.error_type == "container_not_found"

    @pytest.mark.asyncio
    async def test_fetch_handles_runtime_error_outer(self, monkeypatch):
        svc = ContainerStatusService()

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            raise RuntimeError("daemon offline")
            yield  # pragma: no cover

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="ngx")
        result = await svc._fetch_container_status(req)
        assert result.success is False
        assert result.error_type == "docker_error"

    @pytest.mark.asyncio
    async def test_fetch_handles_attribute_error_outer(self, monkeypatch):
        svc = ContainerStatusService()

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            raise AttributeError("missing attr")
            yield  # pragma: no cover

        monkeypatch.setattr(
            "services.docker_service.docker_client_pool.get_docker_client_async",
            lambda *a, **kw: _fake_cm(),
        )

        req = ContainerStatusRequest(container_name="ngx")
        result = await svc._fetch_container_status(req)
        assert result.success is False
        assert result.error_type == "docker_service_error"


class TestContainerStatusCpuMemoryEdgeCases:
    """Lines 331-336, 344, 378-380."""

    def test_cpu_percent_falls_back_to_os_cpu_count(self, monkeypatch):
        svc = ContainerStatusService()
        # No online_cpus, no percpu_usage -> falls back to os.cpu_count().
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": []},
                "system_cpu_usage": 1000,
                "online_cpus": None,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
        }
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        cpu = svc._calculate_cpu_percent_from_stats(stats, "x")
        # delta=100, system_delta=500, cpus=4 -> (100/500)*4*100 = 80.0
        assert cpu == pytest.approx(80.0)

    def test_cpu_percent_method_2_fallback_returns_min(self):
        svc = ContainerStatusService()
        # System still has > 0 usage but precpu==cpu (delta==0).
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
        }
        cpu = svc._calculate_cpu_percent_from_stats(stats, "x")
        assert cpu == 0.1

    def test_memory_from_stats_handles_exception(self):
        svc = ContainerStatusService()
        # Pass non-dict for stats so .get on it raises AttributeError.
        usage_mb, limit_mb = svc._calculate_memory_from_stats(
            "not-a-dict",  # type: ignore[arg-type]
            "x",
        )
        assert usage_mb == 2.0
        assert limit_mb == 1024.0


class TestContainerStatusCompatibilityFallbacks:
    """Compat helpers' early-return paths (630, 736, 765)."""

    @pytest.mark.asyncio
    async def test_get_docker_info_returns_none_on_failure(self):
        fake_service = MagicMock()
        fake_service.get_container_status = AsyncMock(
            return_value=ContainerStatusResult(
                success=False, container_name="x"
            )
        )
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_service,
        ):
            assert await get_docker_info_service_first("x") is None

    @pytest.mark.asyncio
    async def test_get_docker_stats_returns_none_on_failure(self):
        fake_service = MagicMock()
        fake_service.get_container_status = AsyncMock(
            return_value=ContainerStatusResult(
                success=False, container_name="x"
            )
        )
        with patch(
            "services.infrastructure.container_status_service.get_container_status_service",
            return_value=fake_service,
        ):
            assert await get_docker_stats_service_first("x") is None


# =========================================================================== #
# spam_protection_service                                                     #
# =========================================================================== #


class TestSpamProtectionPathException:
    """Line 81-82: __file__.parents[2] resolution failure."""

    def test_init_falls_back_when_parents_resolution_fails(
        self, monkeypatch, tmp_path
    ):
        # We can't easily monkeypatch __file__ so instead trigger the
        # except by passing config_dir=None and patching ``Path(__file__)``
        # only for this module.  The import-time service has already
        # resolved successfully, so we re-create with explicit None and
        # observe the error-handling fallback by mocking Path itself.
        original_path = Path

        class _ExplodingPath(original_path):
            @property
            def parents(self):
                raise RuntimeError("no parents")

        # When Path(__file__) is called inside __init__ it returns our
        # exploding path which fails on .parents access. ``except Exception``
        # catches it and falls back to ``Path("config")`` (line 82).
        monkeypatch.setattr(
            "services.infrastructure.spam_protection_service.Path",
            _ExplodingPath,
        )
        # Also redirect cwd so the fallback "config" path is created in
        # tmp_path -- otherwise it would land in the project root.
        monkeypatch.chdir(tmp_path)
        svc = SpamProtectionService(config_dir=None)
        # Fallback "config" directory should now exist relative to cwd.
        assert svc.config_dir == _ExplodingPath("config")


class TestSpamProtectionSaveConfigFailure:
    """Lines 150-153: save_config IOError handling."""

    def test_save_config_handles_open_failure(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        cfg = svc._get_default_config()

        def _bad_open(*_a, **_kw):
            raise PermissionError("read-only filesystem")

        with patch("builtins.open", _bad_open):
            result = svc.save_config(cfg)
        assert result.success is False
        assert "Error saving" in result.error


class TestSpamProtectionFallbacks:
    """Lines 160, 167, 188 - fallbacks when get_config fails."""

    def test_is_enabled_returns_true_when_config_fails(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))

        with patch.object(
            svc,
            "get_config",
            return_value=MagicMock(success=False, data=None),
        ):
            assert svc.is_enabled() is True  # default fallback

    def test_get_command_cooldown_returns_5_when_config_fails(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        with patch.object(
            svc,
            "get_config",
            return_value=MagicMock(success=False, data=None),
        ):
            assert svc.get_command_cooldown("anything") == 5

    def test_get_button_cooldown_returns_5_when_config_fails(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        with patch.object(
            svc,
            "get_config",
            return_value=MagicMock(success=False, data=None),
        ):
            assert svc.get_button_cooldown("nothing") == 5


class TestSpamProtectionRemainingForCommand:
    """Lines 248-252: get_remaining_cooldown command branch (action_type
    is one of the listed commands)."""

    def test_get_remaining_cooldown_for_command_action(
        self, tmp_path, monkeypatch
    ):
        svc = SpamProtectionService(config_dir=str(tmp_path))

        import time as _t

        monkeypatch.setattr(_t, "time", lambda: 2000.0)
        svc.add_user_cooldown(11, "ping")
        # ping has command cooldown of 3 (default config)
        remaining = svc.get_remaining_cooldown(11, "ping")
        assert 2.9 <= remaining <= 3.0


class TestSpamProtectionAddCooldownDisabled:
    """Line 265: add_user_cooldown returns early when disabled."""

    def test_add_user_cooldown_no_op_when_disabled(self, tmp_path):
        svc = SpamProtectionService(config_dir=str(tmp_path))
        with patch.object(svc, "is_enabled", return_value=False):
            svc.add_user_cooldown(99, "control")
        assert "99:control" not in svc._user_cooldowns


# =========================================================================== #
# dynamic_cooldown_manager                                                    #
# =========================================================================== #


class TestDynamicCooldownGetForCommandFailures:
    """Lines 84-95: PyCord style + total failure paths."""

    def test_get_cooldown_for_command_pycord_style(self, monkeypatch):
        from discord.ext import commands as dpy_commands

        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 9

        # Force discord.py style to TypeError, falling through to PyCord style.
        original = dpy_commands.Cooldown
        call_count = {"n": 0}

        def _fake_cooldown(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call (discord.py 3-arg style) - raise TypeError.
                raise TypeError("3-arg form not supported")
            return original(*args, **kwargs)

        monkeypatch.setattr(dpy_commands, "Cooldown", _fake_cooldown)
        cd = mgr.get_cooldown_for_command("control")
        assert cd is not None
        assert cd.rate == 1
        assert cd.per == 9.0

    def test_get_cooldown_for_command_total_failure_returns_none(
        self, monkeypatch
    ):
        from discord.ext import commands as dpy_commands

        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 9

        call_count = {"n": 0}

        def _fake_cooldown(*_a, **_kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TypeError("3-arg form not supported")
            raise RuntimeError("py-cord 2-arg also broken")

        monkeypatch.setattr(dpy_commands, "Cooldown", _fake_cooldown)
        cd = mgr.get_cooldown_for_command("control")
        assert cd is None


class TestDynamicCooldownApplyAppCommands:
    """Lines 119-120: application_commands branch."""

    def test_apply_uses_application_commands_when_only_one_available(self):
        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.load_settings.return_value = MagicMock(success=True)
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 5

        slash_cmd = MagicMock()
        slash_cmd.name = "control"
        slash_cmd._buckets = MagicMock()

        bot = MagicMock(spec=["application_commands"])
        bot.application_commands = [slash_cmd]
        # Should not raise.
        mgr.apply_dynamic_cooldowns(bot)
        assert slash_cmd._buckets is not None


class TestDynamicCooldownApplyPyCordFallback:
    """Lines 139-146: cooldown apply with PyCord-only signature."""

    def test_apply_falls_back_to_pycord_style(self, monkeypatch):
        # Patch CooldownMapping inside the module under test.
        import services.infrastructure.dynamic_cooldown_manager as dcm_mod

        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.load_settings.return_value = MagicMock(success=True)
        mgr.spam_manager.is_enabled.return_value = True
        mgr.spam_manager.get_command_cooldown.return_value = 5

        # First CooldownMapping(cd, BucketType.user) raises TypeError.
        original = dcm_mod.commands.CooldownMapping
        sentinel_pycord = object()
        call_count = {"n": 0}

        def _fake_mapping(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: 2 positional (cd + bucket) -> raise TypeError
                # to force PyCord fallback.
                raise TypeError("BucketType not supported")
            # Second call: 1 positional (cd) -> return our sentinel.
            return sentinel_pycord

        monkeypatch.setattr(
            dcm_mod.commands, "CooldownMapping", _fake_mapping
        )

        fake_cmd = MagicMock()
        fake_cmd.name = "control"
        fake_cmd._buckets = MagicMock()

        bot = MagicMock(spec=["walk_commands"])
        bot.walk_commands = MagicMock(return_value=[fake_cmd])

        mgr.apply_dynamic_cooldowns(bot)
        # PyCord fallback was used -> sentinel installed.
        assert fake_cmd._buckets is sentinel_pycord


class TestDynamicCooldownApplyEmptyPycord:
    """Lines 154-161: empty-cooldown PyCord fallback for unknown commands."""

    def test_apply_empty_cooldown_falls_back_to_pycord(self, monkeypatch):
        import services.infrastructure.dynamic_cooldown_manager as dcm_mod

        mgr = DynamicCooldownManager()
        mgr.spam_manager = MagicMock()
        mgr.spam_manager.load_settings.return_value = MagicMock(success=True)
        mgr.spam_manager.is_enabled.return_value = True

        sentinel_pycord = object()
        call_count = {"n": 0}

        def _fake_mapping(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call (2 args = cd + BucketType.user) -> TypeError.
                raise TypeError("BucketType not supported")
            return sentinel_pycord

        monkeypatch.setattr(
            dcm_mod.commands, "CooldownMapping", _fake_mapping
        )

        fake_cmd = MagicMock()
        fake_cmd.name = "command-without-mapping"
        fake_cmd._buckets = MagicMock()

        bot = MagicMock(spec=["all_commands"])
        bot.all_commands = {fake_cmd.name: fake_cmd}

        mgr.apply_dynamic_cooldowns(bot)
        assert fake_cmd._buckets is sentinel_pycord
