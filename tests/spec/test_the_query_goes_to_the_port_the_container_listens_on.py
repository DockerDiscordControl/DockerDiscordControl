# -*- coding: utf-8 -*-
"""An autodiscovered game query goes to the port the container listens on.

THE FINDING (stage 4 review before v3.1.0, section 19b pass 4 F1, verified
2026-09-29). With no host configured, resolve_query_candidates queries the
container's own Docker IP - and paired it with the PUBLISHED host ports.
For any mapping where the two differ (`-p 27016:27015/udp`) nothing listens
there: every status cycle burned its timeout per candidate, and the
container never showed a player count, with nothing saying why. Every test
used identical host and container ports.

THE CONTRACT: when the target is the container's own IP, the candidates are
the container-side ports; with a configured host (a host address) they
stay the published ones.

HOW THIS TEST CAN FAIL: the container IP is paired with host ports again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from unittest.mock import MagicMock, patch


def _docker(ports):
    container = MagicMock()
    container.attrs = {"NetworkSettings": {"IPAddress": "172.17.0.5", "Ports": ports}}
    client = MagicMock()
    client.containers.get.return_value = container

    class _CM:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *a):
            return False

    return patch("services.docker_service.docker_client_pool.get_docker_client_async",
                 return_value=_CM())


def test_the_container_ip_is_asked_on_its_own_port():
    from services.infrastructure.game_query_service import GameQueryService

    with _docker({"27015/udp": [{"HostPort": "27016"}]}):
        host, ports = asyncio.run(GameQueryService().resolve_query_candidates("srv"))

    assert (host, ports) == ("172.17.0.5", [27015]), (host, ports)


def test_a_configured_host_keeps_the_published_port():
    """Counter-check: a host address is asked on the port published there."""
    from services.infrastructure.game_query_service import GameQueryService

    with _docker({"27015/udp": [{"HostPort": "27016"}]}):
        host, ports = asyncio.run(GameQueryService().resolve_query_candidates("srv", "192.168.1.249"))

    assert (host, ports) == ("192.168.1.249", [27016]), (host, ports)
