# -*- coding: utf-8 -*-
"""A status older than the refresh cycle says how old it is.

THE FINDING: the status embed can mark data that is older than one and a half
refresh intervals - the reviewed rule of _age_hint_threshold_seconds, written
so that "a refresh was missed" is distinguishable from "we are inside the
normal cycle". Both display sites guard that mark with show_cache_age, and
EVERY caller in the tree passes False: /ss, the periodic edit, the control
buttons, the expand and collapse handlers. The mark was therefore unreachable
in production, and a status that is five minutes old was shown exactly like
one from this second.

The knob is gone; the threshold decides, as it was written to.

COUNTER-CHECK (2026-09-22): red before - the five-minute-old status carried
no age at all. A fresh status must stay unmarked (second test).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult

SERVER = {"docker_name": "web", "name": "web", "display_name": "web",
          "allowed_actions": ["status", "start", "stop", "restart"]}


def _embed(age_seconds):
    result = ContainerStatusResult.success_result(
        docker_name="web", display_name="web", is_running=True, cpu="1%", ram="1024 MB",
        uptime="1h", details_allowed=True)
    entry = {"data": result,
             "timestamp": datetime.now(timezone.utc) - timedelta(seconds=age_seconds)}
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=lambda name: entry)
    cog.pending_actions = {}
    cog.status_refresh_interval_seconds = 120
    cog.cache_ttl_seconds = 300
    cog.expanded_states = {}
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    with patch("cogs.status_handlers.get_server_config_service",
               lambda: SimpleNamespace(get_all_servers=lambda: [SERVER])), \
         patch("services.infrastructure.container_info_service.get_container_info_service",
               return_value=info_service):
        embed, _view, _running = asyncio.run(cog._generate_status_embed_and_view(
            1, "web", SERVER, {}))
    return embed.description


def test_a_status_five_minutes_old_says_so():
    description = _embed(300)

    assert "ago" in description, f"nothing says the data is old:\n{description}"


def test_a_fresh_status_says_nothing():
    """Counter-check: inside the normal cycle the hint must not appear."""
    assert "ago" not in _embed(30)


def test_the_flag_is_gone():
    """The knob that hid it everywhere is not there to be passed again."""
    import inspect

    from cogs.status_handlers import StatusHandlersMixin

    signature = inspect.signature(StatusHandlersMixin._generate_status_embed_and_view)
    assert "show_cache_age" not in signature.parameters

    # force_collapse went the same way on 2026-09-25: it chose between two
    # renderings of the box, and the collapsed one offered a button that no
    # view carries any more.
    assert "force_collapse" not in signature.parameters
