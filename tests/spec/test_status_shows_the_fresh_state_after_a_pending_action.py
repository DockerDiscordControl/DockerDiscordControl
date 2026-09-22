# -*- coding: utf-8 -*-
"""After a pending action resolves, the status shows the state just measured.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 08 F1, re-checked 2026-09-20):
``_generate_status_embed_and_view`` reads the cache entry FIRST and handles
the pending action afterwards. When a pending start/stop/restart passes its
timeout, that block fetches the container's current status and writes it
into the cache - but the render below still uses the entry read before, so
the message shows the state from before the action (or "loading" when there
was no entry at all).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_handlers as sh
from cogs.status_handlers import StatusHandlersMixin
from services.docker_status.models import ContainerStatusResult

DOCKER = "vrising"
NOW = datetime.now(timezone.utc)


class _Cache:
    """Cache that answers with whatever was last written."""

    def __init__(self, entry):
        self.entry = entry

    def get(self, _name):
        return self.entry

    def set(self, _name, data, timestamp):
        self.entry = {"data": data, "timestamp": timestamp}

    def remove(self, _name):
        self.entry = None


def _embed_text():
    mixin = StatusHandlersMixin()
    mixin.status_cache_service = _Cache({
        "data": ContainerStatusResult.offline_result(DOCKER, "V-Rising"),   # before the start
        "timestamp": NOW - timedelta(minutes=10)})
    # A start that has been pending far longer than the timeout and has succeeded
    mixin.pending_actions = {DOCKER: {"action": "start", "timestamp": NOW - timedelta(minutes=5),
                                      "user": "tester", "display_name": "V-Rising"}}
    mixin.expanded_states = {}
    mixin.cache_ttl_seconds = 75
    running = ContainerStatusResult.success_result(
        docker_name=DOCKER, display_name="V-Rising", is_running=True,
        cpu="1.0%", ram="100MB", uptime="1h", details_allowed=True)
    mixin.get_status = AsyncMock(return_value=running)
    servers = MagicMock()
    servers.get_all_servers.return_value = [{"docker_name": DOCKER, "name": "V-Rising"}]
    with patch.object(sh, "get_server_config_service", return_value=servers), \
            patch.object(sh, "_channel_has_permission", return_value=False), \
            patch.object(sh, "ControlView", MagicMock()), \
            patch("cogs.status_info_integration.should_show_info_in_status_channel",
                  return_value=False):
        embed, _view, running_flag = asyncio.run(mixin._generate_status_embed_and_view(
            1, "V-Rising", {"docker_name": DOCKER}, {"language": "en"}))
    return f"{embed.title or ''} {embed.description or ''}", running_flag


def test_the_message_shows_the_state_just_measured():
    text, running_flag = _embed_text()

    assert running_flag is True, (
        f"the action finished and the container runs, but the status still says "
        f"otherwise: {text!r}"
    )
