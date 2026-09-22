# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""
Audit 2026-09, package C1 - Docker status fetching and performance.

Regression tests for:
    C1-1  blocking Docker SDK calls run in a worker thread; one Docker query per fetch
    C1-3  timeouts count as failures; percentile/floor based timeout; bounded emergency fetch
    C1-4  CPU% comes from stats(stream=False) (daemon fills precpu_stats)
    C1-7  a Docker NotFound never rewrites the container config

No Docker daemon needed: get_docker_client_async is replaced by a fake client.
"""

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import docker
import pytest

import services.docker_status.fetch_service as fetch_mod
import services.infrastructure.container_status_service as css_mod
from services.docker_status.fetch_service import DockerStatusFetchService
from services.docker_status.performance_service import PerformanceProfileService
from services.infrastructure.container_status_service import (
    ContainerBulkStatusRequest,
    ContainerStatusRequest,
    ContainerStatusService,
)

STATS = {
    "cpu_stats": {"cpu_usage": {"total_usage": 300}, "system_cpu_usage": 2000, "online_cpus": 2},
    "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
    "memory_stats": {"usage": 64 * 1024 * 1024, "limit": 1024 * 1024 * 1024},
}


class FakeContainer:
    """Container stand-in that records how the SDK is used."""

    def __init__(self, status="running"):
        self.status = status
        self.attrs = {
            "State": {"StartedAt": "2024-01-01T00:00:00Z"},
            "NetworkSettings": {"Ports": {}},
            "Config": {"Image": "img:latest"},
        }
        self.image_calls = 0
        self.stats_calls = []

    @property
    def image(self):
        self.image_calls += 1  # every access is an API call in docker-py
        return SimpleNamespace(tags=["img:latest"], id="sha256:abc")

    def stats(self, stream=True, decode=None):
        self.stats_calls.append({"stream": stream, "decode": decode})
        return STATS


class FakeClient:
    """Docker client stand-in; containers.get() can block like a real HTTP call."""

    def __init__(self, get_delay=0.0, not_found=False):
        self.container = FakeContainer()
        self.get_delay = get_delay
        self.not_found = not_found
        self.get_calls = 0
        self.get_threads = []
        self.containers = SimpleNamespace(get=self._get)

    def _get(self, name):
        self.get_calls += 1
        self.get_threads.append(threading.get_ident())
        if self.get_delay:
            time.sleep(self.get_delay)
        if self.not_found:
            raise docker.errors.NotFound(f"No such container: {name}")
        return self.container


@pytest.fixture
def fake_docker(monkeypatch):
    """Route get_docker_client_async to holder.client (swap it per test)."""
    holder = SimpleNamespace(client=FakeClient())

    @asynccontextmanager
    async def _fake_cm(*_a, **_kw):
        yield holder.client

    monkeypatch.setattr(
        "services.docker_service.docker_client_pool.get_docker_client_async",
        lambda *a, **kw: _fake_cm(),
    )
    return holder


@pytest.fixture
def perf(monkeypatch):
    """Fresh performance profile service used by the fetch service."""
    service = PerformanceProfileService()
    monkeypatch.setattr(fetch_mod, "get_performance_service", lambda: service)
    return service


async def _hang(*_a, **_kw):
    await asyncio.Event().wait()


# --------------------------------------------------------------------------- #
# C1-1: SDK calls off the event loop, one Docker query per fetch               #
# --------------------------------------------------------------------------- #

class TestSdkCallsOffTheEventLoop:

    async def test_sdk_calls_run_in_worker_thread(self, fake_docker):
        fake_docker.client = FakeClient(get_delay=0.3)
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        ticker = asyncio.create_task(_ticker())
        try:
            result = await ContainerStatusService()._fetch_container_status(
                ContainerStatusRequest(container_name="Enshrouded_Proton"))
        finally:
            ticker.cancel()

        assert result.success is True
        assert fake_docker.client.get_threads[0] != threading.get_ident()
        # The event loop kept running while the SDK call blocked for 300ms
        assert ticks >= 5

    async def test_bulk_fetch_runs_containers_in_parallel(self, fake_docker):
        fake_docker.client = FakeClient(get_delay=0.3)
        start = time.monotonic()
        bulk = await ContainerStatusService().get_bulk_container_status(
            ContainerBulkStatusRequest(container_names=["a", "b", "c"], max_concurrent=3))
        elapsed = time.monotonic() - start

        assert bulk.successful_containers == 3
        assert elapsed < 0.75  # serial execution takes >= 0.9s

    async def test_wait_for_timeout_fires_while_sdk_call_blocks(self, fake_docker):
        fake_docker.client = FakeClient(get_delay=0.6)
        start = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                ContainerStatusService()._fetch_container_status(
                    ContainerStatusRequest(container_name="slow")),
                timeout=0.1)
        assert time.monotonic() - start < 0.4

    async def test_container_image_is_never_requested(self, fake_docker):
        """Package C1 cut the extra image request from two to one. Review E53
        cut it to none: the name is in attrs, and the request was what failed
        with 404 once the image had been removed from the host."""
        result = await ContainerStatusService()._fetch_container_status(
            ContainerStatusRequest(container_name="x"))
        assert result.image == "img:latest"
        assert fake_docker.client.container.image_calls == 0

    async def test_fetch_with_retries_queries_docker_once(self, fake_docker, perf, monkeypatch):
        # Fresh status service singleton so no cached state leaks in or out
        monkeypatch.setattr(css_mod, "_container_status_service", ContainerStatusService())
        fetch = DockerStatusFetchService()
        fetch.set_query_cooldown(0)

        name, info, stats = await fetch.fetch_with_retries("Icarus")

        assert name == "Icarus"
        assert info["_computed"]["cpu_percent"] > 0
        assert stats["is_running"] is True
        # info and stats come from a single Docker query (stats are served from the cache)
        assert fake_docker.client.get_calls == 1
        assert len(fake_docker.client.container.stats_calls) == 1

    async def test_info_failure_skips_stats_query(self, perf, monkeypatch):
        stats_mock = AsyncMock()
        monkeypatch.setattr(fetch_mod, "get_docker_info_dict_service_first", AsyncMock(return_value=None))
        monkeypatch.setattr(fetch_mod, "get_docker_stats_service_first", stats_mock)
        fetch = DockerStatusFetchService()
        fetch.set_query_cooldown(0)

        name, info, stats = await fetch.fetch_with_retries("gone")

        assert (name, info, stats) == ("gone", None, None)
        stats_mock.assert_not_awaited()


# --------------------------------------------------------------------------- #
# C1-4: CPU% from a non-stream stats snapshot                                  #
# --------------------------------------------------------------------------- #

class TestCpuFromNonStreamStats:

    async def test_stats_requested_without_stream(self, fake_docker):
        result = await ContainerStatusService()._fetch_container_status(
            ContainerStatusRequest(container_name="x"))

        assert fake_docker.client.container.stats_calls == [{"stream": False, "decode": None}]
        # (300 - 100) / (2000 - 1000) * 2 CPUs * 100
        assert result.cpu_percent == pytest.approx(40.0)
        assert result.memory_usage_mb == pytest.approx(64.0)

    async def test_stopped_container_skips_stats(self, fake_docker):
        fake_docker.client.container.status = "exited"
        result = await ContainerStatusService()._fetch_container_status(
            ContainerStatusRequest(container_name="x"))
        assert result.success is True and result.is_running is False
        assert fake_docker.client.container.stats_calls == []


# --------------------------------------------------------------------------- #
# C1-7: NotFound is reported, config is never rewritten                        #
# --------------------------------------------------------------------------- #

class TestNotFoundKeepsConfig:

    async def test_not_found_does_not_deactivate_container(self, fake_docker, tmp_path, monkeypatch):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        (tmp_path / "containers").mkdir()
        cfg = tmp_path / "containers" / "Icarus.json"
        cfg.write_text(json.dumps({"name": "Icarus", "active": True}), encoding="utf-8")
        fake_docker.client = FakeClient(not_found=True)

        result = await ContainerStatusService()._fetch_container_status(
            ContainerStatusRequest(container_name="Icarus"))

        assert result.success is False
        assert result.error_type == "container_not_found"
        assert json.loads(cfg.read_text(encoding="utf-8"))["active"] is True

    async def test_recreated_container_is_reported_again(self, fake_docker):
        svc = ContainerStatusService()
        fake_docker.client = FakeClient(not_found=True)
        first = await svc._fetch_container_status(ContainerStatusRequest(container_name="Icarus"))
        fake_docker.client = FakeClient()
        second = await svc._fetch_container_status(ContainerStatusRequest(container_name="Icarus"))

        assert first.success is False
        assert second.success is True and second.is_running is True
        assert "Icarus" not in svc._not_found_logged


# --------------------------------------------------------------------------- #
# C1-3: timeout accounting and bounded emergency fetch                         #
# --------------------------------------------------------------------------- #

class TestTimeoutAccounting:

    async def test_timeouts_recorded_as_failures(self, perf, monkeypatch):
        monkeypatch.setattr(fetch_mod, "get_docker_info_dict_service_first", _hang)
        monkeypatch.setattr(perf, "get_adaptive_timeout", lambda _name: 50.0)  # 50ms
        monkeypatch.setattr(fetch_mod.asyncio, "sleep", AsyncMock())
        fetch = DockerStatusFetchService()
        fetch.set_query_cooldown(0)
        emergency = AsyncMock(return_value=("c", None, None))
        monkeypatch.setattr(fetch, "_emergency_full_fetch", emergency)

        await fetch.fetch_with_retries("c")

        profile = perf.get_profile("c")
        assert profile.total_attempts == 3
        assert profile.successful_attempts == 0
        assert profile.success_rate == 0.0
        emergency.assert_awaited_once()

    def test_fast_polls_do_not_shrink_timeout_below_floor(self):
        perf = PerformanceProfileService()
        for _ in range(20):
            perf.update_performance("fast", 200.0, True)
        assert perf.get_config().min_timeout == 10000
        assert perf.get_adaptive_timeout("fast") >= 10000

    def test_timeout_uses_high_percentile(self):
        perf = PerformanceProfileService()
        for t in [1000.0] * 18 + [9000.0, 9500.0]:
            perf.update_performance("spiky", t, True)
        # p95 (nearest rank of 20 samples) = 9000ms, x2 multiplier.
        # The average-based formula gave only max(3.6s, 14.25s, floor).
        assert perf.get_adaptive_timeout("spiky") == pytest.approx(18000.0)

    async def test_emergency_fetch_is_bounded(self, perf, monkeypatch):
        monkeypatch.setattr(fetch_mod, "get_docker_info_dict_service_first", _hang)
        perf.get_config().max_timeout = 200  # ms
        prev = asyncio.TimeoutError()
        start = time.monotonic()

        name, info, stats = await DockerStatusFetchService()._emergency_full_fetch("c", prev)

        assert time.monotonic() - start < 2.0
        assert name == "c" and info is prev and stats is None
        profile = perf.get_profile("c")
        assert profile.total_attempts == 1 and profile.successful_attempts == 0

    async def test_emergency_fetch_without_data_is_not_a_success(self, perf, monkeypatch):
        stats_mock = AsyncMock()
        monkeypatch.setattr(fetch_mod, "get_docker_info_dict_service_first", AsyncMock(return_value=None))
        monkeypatch.setattr(fetch_mod, "get_docker_stats_service_first", stats_mock)

        name, info, stats = await DockerStatusFetchService()._emergency_full_fetch("gone", RuntimeError("x"))

        assert info is None and stats is None
        stats_mock.assert_not_awaited()
        profile = perf.get_profile("gone")
        assert profile.total_attempts == 1 and profile.successful_attempts == 0

    async def test_emergency_fetch_with_data_is_a_success(self, perf, monkeypatch):
        info_payload = {"State": {"Running": True}}
        monkeypatch.setattr(fetch_mod, "get_docker_info_dict_service_first", AsyncMock(return_value=info_payload))
        monkeypatch.setattr(fetch_mod, "get_docker_stats_service_first", AsyncMock(return_value={"cpu_percent": 1.0}))

        name, info, stats = await DockerStatusFetchService()._emergency_full_fetch("slow", RuntimeError("x"))

        assert info == info_payload and stats == {"cpu_percent": 1.0}
        assert perf.get_profile("slow").successful_attempts == 1
