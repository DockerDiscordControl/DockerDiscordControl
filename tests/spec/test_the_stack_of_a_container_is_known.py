# -*- coding: utf-8 -*-
"""The Compose stack of a container reaches the status cache (Phase 4c, part 1).

Roadmap Phase 4c: containers started by Docker Compose carry the label
com.docker.compose.project in their inspect answer; grouping and "restart the
stack" start from knowing it. The chain that dropped health and restarts
dropped labels too - the service kept only running/uptime/image/ports, the
info dict rebuilt Config with the image alone. One test per link.

COUNTER-CHECK (2026-09-22): red before; dropping the label from the info dict
again turns the info-dict test red.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.infrastructure.container_status_service import (ContainerStatusRequest, ContainerStatusResult,
                                                              ContainerStatusService,
                                                              get_docker_info_dict_service_first)

LABEL = "com.docker.compose.project"
ATTRS = {"State": {"Status": "running", "Running": True, "StartedAt": "2026-09-22T10:00:00Z"},
         "RestartCount": 0, "Config": {"Image": "postgres:16", "Labels": {LABEL: "verwaltli"}},
         "NetworkSettings": {"Ports": {}}}


@pytest.mark.asyncio
async def test_the_service_reads_the_stack(monkeypatch):
    container = SimpleNamespace(status="running", attrs=ATTRS)

    @asynccontextmanager
    async def _cm(*_a, **_kw):
        yield SimpleNamespace(containers=SimpleNamespace(get=lambda name: container))

    monkeypatch.setattr("services.docker_service.docker_client_pool.get_docker_client_async",
                        lambda *a, **kw: _cm())
    result = await ContainerStatusService().get_container_status(
        ContainerStatusRequest(container_name="db", include_stats=False))
    assert result.compose_project == "verwaltli"


@pytest.mark.asyncio
async def test_the_info_dict_carries_the_label():
    import services.infrastructure.container_status_service as css

    result = ContainerStatusResult(success=True, container_name="db", is_running=True, compose_project="verwaltli")
    with patch.object(css, "get_container_status_service",
                      return_value=SimpleNamespace(get_container_status=AsyncMock(return_value=result))):
        info = await get_docker_info_dict_service_first("db")
    assert info["Config"]["Labels"][LABEL] == "verwaltli"


def test_the_cache_entry_names_the_stack():
    from cogs.status_handlers import _watch_fields

    assert _watch_fields({"Config": {"Labels": {LABEL: "verwaltli"}}})["compose_project"] == "verwaltli"
    assert _watch_fields({"Config": {}})["compose_project"] is None
