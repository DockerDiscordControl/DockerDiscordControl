# -*- coding: utf-8 -*-
"""A single-container status refresh shows the uptime, as the bulk refresh does.

THE FINDING (stage 4 review before v3.1.0, section 08 pass 4 F7):
get_status read the uptime from State.StartedAt, which the SERVICE FIRST
info dict always leaves None ("will calculate uptime differently"). So every
single-container refresh - after each Discord start/stop/restart, the
auto-action refresh, the pending recheck - reported "Uptime: N/A" for a
running container and cached it, until the next bulk loop wrote the real
value. The bulk path reads _computed.uptime_seconds.

THE CONTRACT: both paths read the same computed uptime.

HOW THIS TEST CAN FAIL: the single refresh says N/A again for a running
container whose uptime Docker reported.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import cogs.status_handlers as sh


async def test_the_uptime_of_a_running_container_is_shown(monkeypatch):
    info = {"State": {"Running": True, "StartedAt": None},
            "_computed": {"cpu_percent": 1.0, "memory_usage_mb": 10.0, "memory_limit_mb": None,
                          "memory_limited": False, "uptime_seconds": 3723}}
    monkeypatch.setattr(sh, "get_docker_info_dict_service_first", AsyncMock(return_value=info))
    monkeypatch.setattr(sh, "get_docker_stats_service_first", AsyncMock(return_value={}))
    cog = SimpleNamespace()

    result = await sh.StatusHandlersMixin.get_status(cog, {"docker_name": "c", "display_name": "c"})

    assert result.uptime == sh.format_uptime(0, 3723), f"uptime shown as {result.uptime!r}"
