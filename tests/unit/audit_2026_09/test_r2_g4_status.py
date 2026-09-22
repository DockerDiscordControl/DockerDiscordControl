# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""
Audit 2026-09, review round 2, package G4 - container status.

R4-4  a container Docker reports as not existing gets its own cached "not found" state
      (ContainerStatusResult.not_found) and is shown as ❓ instead of 🔴 / an endless 🔄.
R4-7  overview edits treat status cache entries older than 60 s as stale (one shared bulk
      refresh), independent of DDC_DOCKER_CACHE_DURATION.
R3-5  bulk status fetch runs up to 6 containers in parallel (was 3).
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import docker
import pytest

import cogs.status_handlers as sh_mod
from cogs.docker_control import STATUS_CACHE_MAX_RENDER_AGE_SECONDS, DockerControlCog
from cogs.status_handlers import StatusHandlersMixin, _bulk_fetch_concurrency
from services.docker_status.models import ContainerClassification, ContainerStatusResult
from services.infrastructure.container_status_service import ContainerStatusRequest, ContainerStatusService


def _now():
    return datetime.now(timezone.utc)


class FakeStatusCache:
    """Dict-backed stand-in for StatusCacheService (get returns None when missing)."""

    def __init__(self, entries=None):
        self.entries = dict(entries or {})

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, data, timestamp=None):
        self.entries[name] = {"data": data, "timestamp": timestamp}

    def remove(self, name):
        return self.entries.pop(name, None) is not None


def _entry(age_seconds=0.0, data=None):
    return {"data": data or SimpleNamespace(success=True), "timestamp": _now() - timedelta(seconds=age_seconds)}


def _servers(*names):
    scs = MagicMock()
    scs.get_all_servers.return_value = [{"docker_name": n, "name": n, "display_name": n.title()} for n in names]
    return scs


def _cog(cache):
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = cache
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    cog.pending_actions = {}
    return cog


def _bulk_fetch(names_returned=None):
    async def _fetch(names):
        await asyncio.sleep(0.01)
        returned = names if names_returned is None else [n for n in names if n in names_returned]
        return {n: SimpleNamespace(success=True, error_message=None) for n in returned}
    return AsyncMock(side_effect=_fetch)


# --------------------------------------------------------------------------- #
# R4-4: "not found" state                                                      #
# --------------------------------------------------------------------------- #

class _NotFoundClient:
    def __init__(self):
        self.not_found = True
        container = SimpleNamespace(status="exited", attrs={"State": {}, "NetworkSettings": {"Ports": {}}},
                                    image=SimpleNamespace(tags=["img:latest"], id="sha256:abc"))
        self.containers = SimpleNamespace(get=lambda name: self._get(name, container))

    def _get(self, name, container):
        if self.not_found:
            raise docker.errors.NotFound(f"No such container: {name}")
        return container


class TestNotFoundDetection:

    async def test_service_flags_not_found_until_next_success(self, monkeypatch):
        client = _NotFoundClient()

        @asynccontextmanager
        async def _fake_cm(*_a, **_kw):
            yield client

        monkeypatch.setattr("services.docker_service.docker_client_pool.get_docker_client_async",
                            lambda *a, **kw: _fake_cm())
        svc = ContainerStatusService()
        request = ContainerStatusRequest(container_name="Icarus", include_stats=False)

        assert (await svc.get_container_status(request)).success is False
        assert svc.is_container_not_found("Icarus") is True
        assert svc.is_container_not_found("other") is False

        client.not_found = False  # container recreated
        assert (await svc.get_container_status(request)).success is True
        assert svc.is_container_not_found("Icarus") is False

    def test_not_found_result_is_a_determined_offline_state(self):
        result = ContainerStatusResult.not_found_result("icarus", "Icarus")

        assert result.success is True and result.is_running is False
        assert result.not_found is True and result.error_type == "not_found"
        assert ContainerStatusResult.offline_result("icarus", "Icarus").not_found is False

    async def test_bulk_fetch_returns_not_found_result(self):
        mixin = StatusHandlersMixin()
        mixin._enrich_status_with_player_counts = AsyncMock()
        mixin._schedule_support_probes = MagicMock()
        fetch = SimpleNamespace(fetch_with_retries=AsyncMock(side_effect=lambda n: (n, None, None)))
        perf = SimpleNamespace(classify_containers=lambda names: ContainerClassification(fast_containers=list(names)))
        connectivity = SimpleNamespace(check_connectivity=AsyncMock(return_value=SimpleNamespace(is_connected=True)))
        css = SimpleNamespace(is_container_not_found=lambda n: n == "gone")

        with patch("services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
                   return_value=connectivity), \
             patch.object(sh_mod, "get_performance_service", return_value=perf), \
             patch.object(sh_mod, "get_fetch_service", return_value=fetch), \
             patch.object(sh_mod, "get_server_config_service", return_value=_servers("gone", "down")), \
             patch.object(sh_mod, "get_container_status_service", return_value=css):
            results = await mixin.bulk_fetch_container_status(["gone", "down"])

        assert results["gone"].not_found is True and results["gone"].success is True
        # No NotFound from Docker (e.g. daemon trouble) -> still the old offline result
        assert results["down"].not_found is False and results["down"].is_offline

    async def test_get_status_returns_not_found_result(self):
        mixin = StatusHandlersMixin()
        with patch.object(sh_mod, "get_docker_info_dict_service_first", AsyncMock(return_value=None)), \
             patch.object(sh_mod, "get_container_status_service",
                          return_value=SimpleNamespace(is_container_not_found=lambda n: True)):
            result = await mixin.get_status({"docker_name": "gone", "display_name": "Gone"})

        assert result.not_found is True and result.display_name == "Gone"

    async def test_not_found_result_is_cached_not_counted_as_failed(self):
        cache = FakeStatusCache()
        cog = _cog(cache)
        cog.bulk_fetch_container_status = AsyncMock(return_value={
            "gone": ContainerStatusResult.not_found_result("gone", "Gone")})
        with patch("cogs.docker_control.get_server_config_service", return_value=_servers("gone")), \
             patch("cogs.docker_control.load_config", return_value={"language": "en"}), patch("cogs.overview_embeds.load_config", return_value={"language": "en"}):
            await cog._background_cache_population()

        assert cache.get("gone")["data"].not_found is True
        assert cog._status_fetch_failed == set()


def _render_patches():
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    mech_cache = MagicMock()
    mech_cache.get_cached_status.return_value = SimpleNamespace(success=False, error_message="n/a")
    return [
        patch("cogs.docker_control.load_config", return_value={}), patch("cogs.overview_embeds.load_config", return_value={}),
        patch("services.infrastructure.container_info_service.get_container_info_service",
              return_value=info_service),
        patch("services.donation.donation_utils.is_donations_disabled", return_value=False),
        patch("services.mech.mech_status_cache_service.get_mech_status_cache_service", return_value=mech_cache),
    ]


class TestNotFoundRendering:

    SERVERS = [{"docker_name": "gone", "display_name": "Gone"}, {"docker_name": "down", "display_name": "Down"}]

    def _cache(self):
        return FakeStatusCache({
            "gone": _entry(data=ContainerStatusResult.not_found_result("gone", "Gone")),
            "down": _entry(data=ContainerStatusResult.offline_result("down", "Down")),
        })

    async def _build(self, builder):
        cog = _cog(self._cache())
        patches = _render_patches()
        for p in patches:
            p.start()
        try:
            return await getattr(cog, builder)(self.SERVERS, {})
        finally:
            for p in patches:
                p.stop()

    async def test_admin_overview_shows_not_found(self):
        embed, _file, has_running = await self._build("_create_admin_overview_embed")

        assert "❓ Gone · not found" in embed.description
        assert "🔴 Down · offline" in embed.description
        assert "🔄" not in embed.description
        assert "Online: 0" in embed.description and has_running is False

    @pytest.mark.parametrize("builder", ["_create_overview_embed_expanded", "_create_overview_embed_collapsed"])
    async def test_server_overview_shows_not_found(self, builder):
        embed, _file = await self._build(builder)

        assert "│ ❓ Gone · not found" in embed.description
        assert "│ 🔴 Down" in embed.description
        assert "🔄" not in embed.description

    async def test_status_embed_shows_not_found(self):
        mixin = StatusHandlersMixin()
        mixin.status_cache_service = self._cache()
        mixin.pending_actions = {}
        mixin.expanded_states = {}
        mixin.cache_ttl_seconds = 75
        with patch.object(sh_mod, "get_server_config_service", return_value=_servers("gone")), \
             patch.object(sh_mod, "_channel_has_permission", return_value=False), \
             patch.object(sh_mod, "ControlView", MagicMock()), \
             patch("cogs.status_info_integration.should_show_info_in_status_channel", return_value=False):
            embed, _view, running = await mixin._generate_status_embed_and_view(
                1, "Gone", {"docker_name": "gone"}, {"language": "en"})

        assert "❓ Not found" in embed.description
        assert running is False


# --------------------------------------------------------------------------- #
# R4-7: entries older than 60 s are stale for overview edits                   #
# --------------------------------------------------------------------------- #

class TestStatusCacheMaxRenderAge:

    async def test_young_entries_render_from_cache(self):
        cog = _cog(FakeStatusCache({"a": _entry(5), "b": _entry(STATUS_CACHE_MAX_RENDER_AGE_SECONDS - 5)}))
        cog.bulk_fetch_container_status = _bulk_fetch()
        with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")):
            await cog._ensure_status_cache_fresh()
        cog.bulk_fetch_container_status.assert_not_awaited()

    async def test_old_entry_triggers_one_shared_refresh(self):
        cache = FakeStatusCache({"a": _entry(5), "b": _entry(STATUS_CACHE_MAX_RENDER_AGE_SECONDS + 30)})
        cog = _cog(cache)
        cog.bulk_fetch_container_status = _bulk_fetch()
        with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")), \
             patch("cogs.docker_control.load_config", return_value={"language": "en"}), patch("cogs.overview_embeds.load_config", return_value={"language": "en"}):
            await asyncio.gather(*(cog._ensure_status_cache_fresh() for _i in range(3)))
            await cog._ensure_status_cache_fresh()   # just refreshed -> fresh again, no fetch

        assert cog.bulk_fetch_container_status.await_count == 1
        assert cache.get("b")["timestamp"] > _now() - timedelta(seconds=5)

    async def test_old_entry_of_failed_container_does_not_force_refetch(self):
        cog = _cog(FakeStatusCache({"a": _entry(5), "b": _entry(STATUS_CACHE_MAX_RENDER_AGE_SECONDS + 30)}))
        cog._status_fetch_failed = {"b"}
        cog.bulk_fetch_container_status = _bulk_fetch()
        with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")):
            await cog._ensure_status_cache_fresh()
        cog.bulk_fetch_container_status.assert_not_awaited()

    async def test_container_missing_from_results_counts_as_failed(self):
        cog = _cog(FakeStatusCache({"a": _entry(5), "b": _entry(STATUS_CACHE_MAX_RENDER_AGE_SECONDS + 30)}))
        cog.bulk_fetch_container_status = _bulk_fetch(names_returned={"a"})
        with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")), \
             patch("cogs.docker_control.load_config", return_value={"language": "en"}), patch("cogs.overview_embeds.load_config", return_value={"language": "en"}):
            await cog._ensure_status_cache_fresh()
            await cog._ensure_status_cache_fresh()

        assert cog.bulk_fetch_container_status.await_count == 1
        assert cog._status_fetch_failed == {"b"}


# --------------------------------------------------------------------------- #
# R3-5: bulk fetch concurrency                                                 #
# --------------------------------------------------------------------------- #

class TestBulkFetchConcurrency:

    @pytest.mark.parametrize("cpus, expected", [(16, 6), (4, 6), (2, 4), (1, 3), (None, 3)])
    def test_concurrency_keeps_executor_headroom(self, monkeypatch, cpus, expected):
        monkeypatch.setattr(sh_mod.os, "process_cpu_count", lambda: cpus, raising=False)
        assert _bulk_fetch_concurrency() == expected

    async def test_bulk_fetch_runs_six_in_parallel(self, monkeypatch):
        monkeypatch.setattr(sh_mod.os, "process_cpu_count", lambda: 8, raising=False)
        active = peak = 0

        async def _fetch(name):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return name, {"State": {"Running": False}}, None

        names = [f"c{i}" for i in range(10)]
        mixin = StatusHandlersMixin()
        mixin._enrich_status_with_player_counts = AsyncMock()
        mixin._schedule_support_probes = MagicMock()
        perf = SimpleNamespace(classify_containers=lambda n: ContainerClassification(fast_containers=list(n)))
        connectivity = SimpleNamespace(check_connectivity=AsyncMock(return_value=SimpleNamespace(is_connected=True)))

        with patch("services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
                   return_value=connectivity), \
             patch.object(sh_mod, "get_performance_service", return_value=perf), \
             patch.object(sh_mod, "get_fetch_service",
                          return_value=SimpleNamespace(fetch_with_retries=_fetch)), \
             patch.object(sh_mod, "get_server_config_service", return_value=_servers(*names)):
            results = await mixin.bulk_fetch_container_status(names)

        assert len(results) == 10
        assert peak == 6
