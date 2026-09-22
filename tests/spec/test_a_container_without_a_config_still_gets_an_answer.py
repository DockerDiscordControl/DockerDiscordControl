# -*- coding: utf-8 -*-
"""Every container the bulk fetch was asked about comes back in its answer.

THE FINDING: bulk_fetch_container_status promises "Dict mapping
container_name -> ContainerStatusResult" and its own docstring says complete
data. One branch breaks that: when the container has no server configuration
any more, it logs a warning and `continue`s, so the name is simply missing
from the answer.

It is reachable without anything being broken: the caller builds its list of
names and the fetch re-reads the server configuration, so a container renamed
or deactivated in the web panel between those two reads has no config here.
The caller then caches neither a status nor an error for it, and the panel
leaves it on the loading icon until something else fixes it - looking exactly
like a container nobody has asked about yet.

The name comes back as a failure now, which the caller already knows how to
record.

COUNTER-CHECK (2026-09-22): red before - the answer held one entry for two
requested containers.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cogs.docker_control import DockerControlCog

CONFIG = {"name": "Web", "docker_name": "web", "display_name": "Web", "allow_detailed_status": True}


@pytest.mark.asyncio
async def test_a_container_whose_config_vanished_is_reported_as_failed():
    cog = object.__new__(DockerControlCog)
    cog.pending_actions = {}
    cog.status_cache_service = SimpleNamespace(get=lambda name: None)

    async def _retries(name):
        return name, {"State": {"Running": True}, "Config": {"Image": "nginx"}}, None

    classification = SimpleNamespace(fast_containers=["web", "gone"], slow_containers=[],
                                     unknown_containers=[])
    with patch("services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
               lambda: SimpleNamespace(check_connectivity=AsyncMock(
                   return_value=SimpleNamespace(is_connected=True, error_message=None)))), \
         patch("cogs.status_handlers.get_performance_service",
               lambda: SimpleNamespace(classify_containers=lambda names: classification,
                                       update_performance=lambda *a, **kw: None)), \
         patch("cogs.status_handlers.get_fetch_service",
               lambda: SimpleNamespace(fetch_with_retries=_retries)), \
         patch("cogs.status_handlers.get_server_config_service",
               lambda: SimpleNamespace(get_all_servers=lambda: [CONFIG])), \
         patch("cogs.status_handlers.get_container_status_service",
               lambda: SimpleNamespace(is_container_not_found=lambda name: False)):
        results = await cog.bulk_fetch_container_status(["web", "gone"])

    assert set(results) == {"web", "gone"}, f"a requested container is missing: {sorted(results)}"
    assert results["gone"].success is False
    assert results["web"].success is True
