# -*- coding: utf-8 -*-
"""The Admin Overview's header counts only what its lines say.

Two numbers in "Container: 5 • Online: 4 • Offline: 1" were built from
something other than the lines below them:

* a container Docker says does not EXIST (deleted or renamed outside DDC)
  renders as "❓ name · not found" and was counted as Offline. The operator
  reads one stopped container they could start; there is none. This is the
  same rule as SPEC.md Z3, one state further: what is not there is not
  "off";
* the total was len(ordered_servers), taken before the loop, and the loop
  skips any entry without a display name or docker name. The header then
  promised more containers than it showed.

COUNTER-CHECK (2026-09-22): red before - the not-found container counted as
Offline: 1, and a broken entry left "Container: 2" above one line.
"""

import asyncio
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult


def _server(name):
    return {"docker_name": name, "name": name, "display_name": name, "allowed_actions": ["restart"]}


def _entry(result):
    return {"data": result, "timestamp": datetime.now(timezone.utc)}


def _running(name):
    return _entry(ContainerStatusResult.success_result(
        docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1024 MB",
        uptime="1h", details_allowed=True))


def _header(servers, entries):
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=entries.get)
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    cog.pending_actions = {}
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    with patch("cogs.overview_embeds.load_config", return_value={}), \
         patch("services.infrastructure.container_info_service.get_container_info_service",
               return_value=info_service):
        embed, _file, _running_flag = asyncio.run(cog._create_admin_overview_embed(servers, {}))
    line = next(l for l in embed.description.splitlines() if l.startswith("Container:"))
    numbers = [int(n) for n in re.findall(r"(\d+)", line)]
    return dict(zip(("total", "online", "offline"), numbers)), embed.description


def test_a_container_that_does_not_exist_is_not_counted_as_offline():
    entries = {"web": _running("web"),
               "gone": _entry(ContainerStatusResult.not_found_result("gone", "gone"))}

    counts, description = _header([_server("web"), _server("gone")], entries)

    assert "not found" in description, "premise: the line says not found"
    assert counts["offline"] == 0, f"a container that does not exist was counted as offline: {counts}"
    assert counts["online"] == 1


def test_a_stopped_container_is_still_offline():
    """Counter-check: the count must still work for a container that IS off."""
    entries = {"web": _running("web"),
               "db": _entry(ContainerStatusResult.offline_result("db", "db"))}

    counts, _description = _header([_server("web"), _server("db")], entries)

    assert counts == {"total": 2, "online": 1, "offline": 1}


def test_the_total_counts_the_lines_that_are_shown():
    broken = {"name": "", "docker_name": ""}          # an entry the loop skips
    counts, description = _header([_server("web"), broken], {"web": _running("web")})

    lines = [l for l in description.split("\n\n", 1)[1].split("\n") if l not in ("ㅤ", "")]
    assert counts["total"] == len(lines), f"{counts} above {len(lines)} lines"
