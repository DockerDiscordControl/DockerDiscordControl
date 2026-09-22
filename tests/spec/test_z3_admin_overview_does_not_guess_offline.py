# -*- coding: utf-8 -*-
# @covers Z3
"""Z3 - the admin overview does not count "not known yet" as "offline".

THE FINDING (stage 4 review, stage B, section 05 F1, re-checked 2026-09-20):
right after a restart - or whenever a container's cache entry has expired -
``_create_admin_overview_embed`` shows the container line with the loading
icon 🔄, and at the same time counts that container as OFFLINE in the header
("Container: 5 • Online: 0 • Offline: 5"). The admin opens /control and
reads "everything is down" for containers nobody has asked about yet.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult

SERVERS = [{"docker_name": "vrising", "name": "V-Rising", "display_name": "V-Rising",
            "allowed_actions": ["start", "stop", "restart"]}]


class _Cache:
    def __init__(self, entries):
        self._entries = entries

    def get(self, name):
        return self._entries.get(name)


def _cog(entries):
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = _Cache(entries)
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    cog.pending_actions = {}
    return cog


def _patches():
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    mech_cache = MagicMock()
    mech_cache.get_cached_status.return_value = SimpleNamespace(success=False, error_message="n/a")
    return [
        patch("cogs.docker_control.load_config", return_value={}), patch("cogs.overview_embeds.load_config", return_value={}),
        patch("services.infrastructure.container_info_service.get_container_info_service",
              return_value=info_service),
        patch("services.donation.donation_utils.is_donations_disabled", return_value=False),
        patch("services.mech.mech_status_cache_service.get_mech_status_cache_service",
              return_value=mech_cache),
    ]


def _overview(entries):
    cog = _cog(entries)
    started = _patches()
    for p in started:
        p.start()
    try:
        embed, _file, _running = asyncio.run(cog._create_admin_overview_embed(SERVERS, {}))
    finally:
        for p in started:
            p.stop()
    return embed.description


def test_a_container_without_data_is_not_counted_as_offline():
    description = _overview({})          # nothing cached yet - as right after a restart

    assert "🔄" in description, "premise: the container line shows the loading icon"
    assert "Offline: 0" in description, (
        f"a container nobody has fetched yet is counted as offline: {description!r}"
    )


def test_a_stopped_container_is_still_counted_as_offline():
    """Counter-check: otherwise 'never offline' would pass the test above."""
    entries = {"vrising": {"data": ContainerStatusResult.offline_result("vrising", "V-Rising"),
                           "timestamp": datetime.now(timezone.utc)}}

    description = _overview(entries)

    assert "Offline: 1" in description, description
