# -*- coding: utf-8 -*-
"""Details switched off look switched off, not like a measurement that failed.

THE FINDING: a container whose "detailed status" is switched off gets the
word "Hidden" instead of CPU and RAM. The Admin Overview parses those
strings as numbers, the parse fails, and the row reads "🟢 name · —% • —GB" -
which the operator reads as "DDC could not measure it", not as "I turned this
off for this container". The number was never missing; it was withheld on
purpose.

COUNTER-CHECK (2026-09-22): red before - the row showed —% • —GB. A container
whose details ARE allowed must still show its numbers (second test).
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult


def _row(details_allowed):
    result = ContainerStatusResult.success_result(
        docker_name="web", display_name="web", is_running=True,
        cpu="Hidden" if not details_allowed else "12%",
        ram="Hidden" if not details_allowed else "2048 MB",
        uptime="1h", details_allowed=details_allowed)
    entries = {"web": {"data": result, "timestamp": datetime.now(timezone.utc)}}
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
        embed, _file, _running = asyncio.run(cog._create_admin_overview_embed(
            [{"docker_name": "web", "name": "web", "display_name": "web",
              "allowed_actions": ["restart"]}], {}))
    return next(line for line in embed.description.splitlines() if "web" in line)


def test_a_container_with_details_off_does_not_show_dashes():
    line = _row(details_allowed=False)

    assert "—%" not in line and "—GB" not in line, line


def test_a_container_with_details_on_shows_its_numbers():
    """Counter-check: the measurements must still be shown."""
    line = _row(details_allowed=True)

    assert "12.0%" in line and "2.0GB" in line, line
