# -*- coding: utf-8 -*-
"""Health and RestartCount reach the status cache (container watchdog, Phase 4a, part 2).

The watchdog decides from the status cache (services/automation/container_watch.py),
but the cache never held what it needs. Docker's inspect answer carries
State.Health.Status and RestartCount; DDC's chain dropped both at every link:

1. ContainerStatusService._query_container_sync read the inspect attrs and
   kept only running / uptime / image / ports;
2. get_docker_info_dict_service_first rebuilt a small dict with State.Running
   alone;
3. the status handlers turned that into the cached ContainerStatusResult.

Each link has its own test: a field one link forwards and the next drops
would pass a test of the first link alone.

COUNTER-CHECK (2026-09-22): red on all four before. Then the info dict was
made to leave RestartCount out again: the info-dict test went red (the handler
tests feed a fixed dict, so they cover only the last link - which is why each
link has its own test).
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_handlers as sh_mod
from cogs.status_handlers import StatusHandlersMixin
from services.docker_status.models import ContainerClassification
from services.infrastructure.container_status_service import (ContainerStatusRequest,
                                                              ContainerStatusService,
                                                              get_docker_info_dict_service_first)

ATTRS = {
    "State": {"Status": "running", "Running": True, "StartedAt": "2026-09-22T10:00:00Z",
              "Health": {"Status": "unhealthy"}},
    "RestartCount": 4,
    "Config": {"Image": "nginx:latest"},
    "NetworkSettings": {"Ports": {}},
}


class _Client:
    def __init__(self):
        container = SimpleNamespace(status="running", attrs=ATTRS)
        self.containers = SimpleNamespace(get=lambda name: container)


@pytest.fixture
def docker_answers(monkeypatch):
    @asynccontextmanager
    async def _fake_cm(*_a, **_kw):
        yield _Client()

    monkeypatch.setattr("services.docker_service.docker_client_pool.get_docker_client_async",
                        lambda *a, **kw: _fake_cm())


@pytest.mark.asyncio
async def test_the_service_keeps_health_and_restart_count(docker_answers):
    result = await ContainerStatusService().get_container_status(
        ContainerStatusRequest(container_name="web", include_stats=False))
    assert result.success
    assert (result.health, result.restart_count) == ("unhealthy", 4)


@pytest.mark.asyncio
async def test_the_info_dict_carries_them(docker_answers):
    import services.infrastructure.container_status_service as css

    monkeypatch_service = ContainerStatusService()
    with patch.object(css, "get_container_status_service", return_value=monkeypatch_service):
        info = await get_docker_info_dict_service_first("web")
    assert info["State"]["Health"]["Status"] == "unhealthy"
    assert info["RestartCount"] == 4


INFO = {"State": {"Running": True, "StartedAt": None, "Health": {"Status": "unhealthy"}},
        "RestartCount": 4, "Config": {"Image": "nginx"}, "NetworkSettings": {"Ports": {}},
        "_computed": {"cpu_percent": 1.0, "memory_usage_mb": 10.0, "uptime_seconds": 60}}


def _servers():
    scs = MagicMock()
    scs.get_all_servers.return_value = [{"docker_name": "web", "name": "web", "display_name": "Web"}]
    return scs


@pytest.mark.asyncio
async def test_the_bulk_fetch_puts_them_in_the_cache_entry():
    mixin = StatusHandlersMixin()
    mixin._enrich_status_with_player_counts = AsyncMock()
    mixin._schedule_support_probes = MagicMock()
    fetch = SimpleNamespace(fetch_with_retries=AsyncMock(side_effect=lambda n: (n, INFO, None)))
    perf = SimpleNamespace(classify_containers=lambda names: ContainerClassification(fast_containers=list(names)))
    connectivity = SimpleNamespace(check_connectivity=AsyncMock(return_value=SimpleNamespace(is_connected=True)))
    with patch("services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
               return_value=connectivity), \
         patch.object(sh_mod, "get_performance_service", return_value=perf), \
         patch.object(sh_mod, "get_fetch_service", return_value=fetch), \
         patch.object(sh_mod, "get_server_config_service", return_value=_servers()):
        results = await mixin.bulk_fetch_container_status(["web"])
    assert (results["web"].health, results["web"].restart_count) == ("unhealthy", 4)


@pytest.mark.asyncio
async def test_the_single_fetch_puts_them_in_the_result_too():
    mixin = StatusHandlersMixin()
    mixin._enrich_status_with_player_counts = AsyncMock()
    with patch.object(sh_mod, "get_docker_info_dict_service_first", AsyncMock(return_value=INFO)), \
         patch.object(sh_mod, "get_docker_stats_service_first", AsyncMock(return_value=None), create=True):
        result = await mixin.get_status({"docker_name": "web", "display_name": "Web"})
    assert (result.health, result.restart_count) == ("unhealthy", 4)
