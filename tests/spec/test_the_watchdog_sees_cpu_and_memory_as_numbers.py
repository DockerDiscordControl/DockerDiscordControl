# -*- coding: utf-8 -*-
"""CPU and memory reach the status cache as numbers (resource thresholds, Phase 4b, part 2).

The cache held CPU and RAM only as display text ("12.3%", "512MB"), and the
info dict's _computed block carried the memory usage without its limit, so no
percentage could be formed. The resource watcher needs cpu_percent and
memory_percent (usage / limit). One test per link, as for health and restarts.

COUNTER-CHECK (2026-09-22): red before; dropping memory_limit_mb from the
info dict again turns the info-dict test red.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_handlers as sh_mod
from cogs.status_handlers import StatusHandlersMixin
from services.docker_status.models import ContainerClassification
from services.infrastructure.container_status_service import ContainerStatusResult, get_docker_info_dict_service_first


@pytest.mark.asyncio
async def test_the_info_dict_carries_the_memory_limit():
    import services.infrastructure.container_status_service as css

    result = ContainerStatusResult(success=True, container_name="web", is_running=True,
                                   cpu_percent=42.0, memory_usage_mb=256.0, memory_limit_mb=1024.0)
    service = SimpleNamespace(get_container_status=AsyncMock(return_value=result))
    with patch.object(css, "get_container_status_service", return_value=service):
        info = await get_docker_info_dict_service_first("web")
    assert info["_computed"]["memory_limit_mb"] == 1024.0


INFO = {"State": {"Running": True, "StartedAt": None}, "RestartCount": 0,
        "Config": {"Image": "nginx"}, "NetworkSettings": {"Ports": {}},
        "_computed": {"cpu_percent": 42.0, "memory_usage_mb": 256.0, "memory_limit_mb": 1024.0,
                      "uptime_seconds": 60}}


@pytest.mark.asyncio
async def test_the_cache_entry_has_cpu_and_memory_percent():
    mixin = StatusHandlersMixin()
    mixin._enrich_status_with_player_counts = AsyncMock()
    mixin._schedule_support_probes = MagicMock()
    fetch = SimpleNamespace(fetch_with_retries=AsyncMock(side_effect=lambda n: (n, INFO, None)))
    perf = SimpleNamespace(classify_containers=lambda names: ContainerClassification(fast_containers=list(names)))
    connectivity = SimpleNamespace(check_connectivity=AsyncMock(return_value=SimpleNamespace(is_connected=True)))
    servers = MagicMock()
    servers.get_all_servers.return_value = [{"docker_name": "web", "name": "web", "display_name": "Web"}]
    with patch("services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
               return_value=connectivity), \
         patch.object(sh_mod, "get_performance_service", return_value=perf), \
         patch.object(sh_mod, "get_fetch_service", return_value=fetch), \
         patch.object(sh_mod, "get_server_config_service", return_value=servers):
        results = await mixin.bulk_fetch_container_status(["web"])
    assert results["web"].cpu_percent == 42.0
    assert results["web"].memory_percent == 25.0


def test_no_limit_means_no_percentage():
    from cogs.status_handlers import _watch_fields

    fields = _watch_fields({"_computed": {"cpu_percent": None, "memory_usage_mb": 10.0, "memory_limit_mb": None}})
    assert fields["cpu_percent"] is None and fields["memory_percent"] is None
