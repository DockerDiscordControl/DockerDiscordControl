# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""Audit 2026-09, package B: cogs/docker_control.py fixes.

- B1: overview updates render from the status cache and only refresh it when stale;
      concurrent callers share one bulk fetch.
- B6: overview builders return (embed, None) when the mech cache fails (was a bare None).
- B7: trigger_status_refresh finds the container although config['servers'] is a list.
- B10: persistent views are registered with real channel ids / tracked message ids.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import discord
import pytest

from cogs.docker_control import DockerControlCog


class FakeStatusCache:
    """Dict-backed stand-in for StatusCacheService (get returns None when missing)."""

    def __init__(self, names=()):
        self.entries = {n: {"data": SimpleNamespace(success=True), "timestamp": None} for n in names}

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, data, timestamp=None):
        self.entries[name] = {"data": data, "timestamp": timestamp}

    def remove(self, name):
        return self.entries.pop(name, None) is not None


def _servers(*names):
    scs = MagicMock()
    scs.get_all_servers.return_value = [{"docker_name": n} for n in names]
    scs.get_server_by_docker_name.side_effect = lambda n: next(
        ({"docker_name": s, "display_name": s.title()} for s in names if s == n), None)
    return scs


def _cog(cache):
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = cache
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    return cog


def _bulk_fetch(fail=()):
    async def _fetch(names):
        await asyncio.sleep(0.01)
        return {n: SimpleNamespace(success=n not in fail, error_message="gone") for n in names}
    return AsyncMock(side_effect=_fetch)


# ---------------------------------------------------------------------------
# B1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_cache_does_not_fetch():
    cog = _cog(FakeStatusCache(["a", "b"]))
    cog.bulk_fetch_container_status = _bulk_fetch()
    with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")):
        await cog._ensure_status_cache_fresh()
    cog.bulk_fetch_container_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_cache_fetches_once_for_concurrent_callers():
    cache = FakeStatusCache(["a"])
    cog = _cog(cache)
    cog.bulk_fetch_container_status = _bulk_fetch()
    with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")), \
         patch("cogs.docker_control.load_config", return_value={"language": "en"}):
        await asyncio.gather(*(cog._ensure_status_cache_fresh() for _i in range(3)))
    assert cog.bulk_fetch_container_status.await_count == 1
    assert cache.get("b") is not None


@pytest.mark.asyncio
async def test_failed_containers_do_not_force_refetch():
    cog = _cog(FakeStatusCache(["a"]))
    cog.bulk_fetch_container_status = _bulk_fetch(fail={"b"})
    with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a", "b")), \
         patch("cogs.docker_control.load_config", return_value={"language": "en"}):
        await cog._ensure_status_cache_fresh()   # b missing -> one fetch, b fails
        await cog._ensure_status_cache_fresh()   # b known-failed -> no second fetch
    assert cog.bulk_fetch_container_status.await_count == 1
    assert cog._status_fetch_failed == {"b"}


@pytest.mark.asyncio
async def test_update_overview_message_renders_from_fresh_cache():
    cog = _cog(FakeStatusCache(["a"]))
    cog.bulk_fetch_container_status = _bulk_fetch()
    message = MagicMock()
    message.edit = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    channel.get_partial_message.return_value = message
    cog.bot = MagicMock()
    cog.bot.fetch_channel = AsyncMock(return_value=channel)
    cog.ordered_server_names = ["a"]
    cog.last_message_update_time = {}
    cog.channel_server_message_ids = {5: {"admin_overview": 77}}
    cog._create_admin_overview_embed = AsyncMock(return_value=(discord.Embed(title="x"), None, True))

    with patch.object(DockerControlCog, "config", new_callable=PropertyMock, return_value={}), \
         patch("cogs.docker_control.get_server_config_service", return_value=_servers("a")):
        assert await cog._update_overview_message(5, 77, "admin_overview") is True

    cog.bulk_fetch_container_status.assert_not_awaited()
    message.edit.assert_awaited_once()


# ---------------------------------------------------------------------------
# B6
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("builder", ["_create_overview_embed_collapsed", "_create_overview_embed_expanded"])
@pytest.mark.asyncio
async def test_overview_builders_return_tuple_when_mech_cache_fails(builder):
    cog = _cog(FakeStatusCache())
    mech_cache = MagicMock()
    mech_cache.get_cached_status.return_value = SimpleNamespace(success=False, error_message="boom")
    with patch("cogs.docker_control.load_config", return_value={}), \
         patch("services.donation.donation_utils.is_donations_disabled", return_value=False), \
         patch("services.mech.mech_status_cache_service.get_mech_status_cache_service",
               return_value=mech_cache):
        result = await getattr(cog, builder)([], {})

    assert isinstance(result, tuple)
    embed, animation_file = result
    assert isinstance(embed, discord.Embed)
    assert animation_file is None


# ---------------------------------------------------------------------------
# B7
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_status_refresh_updates_overviews():
    cog = _cog(FakeStatusCache())
    fresh = SimpleNamespace(success=True)
    cog.get_status = AsyncMock(return_value=fresh)
    cog.channel_server_message_ids = {1: {"overview": 10, "admin_overview": 11}}
    cog._update_overview_message = AsyncMock(return_value=True)

    with patch("cogs.docker_control.load_config", return_value={"servers": [{"docker_name": "web"}]}), \
         patch("cogs.docker_control.get_server_config_service", return_value=_servers("web")), \
         patch("services.infrastructure.container_status_service.get_container_status_service"):
        await cog.trigger_status_refresh("web", delay_seconds=0)
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending)

    cog.get_status.assert_awaited_once_with({"docker_name": "web", "display_name": "Web"})
    assert cog.status_cache_service.get("web")["data"] is fresh
    awaited = [c.args for c in cog._update_overview_message.await_args_list]
    assert (1, 10, "overview") in awaited
    assert (1, 11, "admin_overview") in awaited


# ---------------------------------------------------------------------------
# B10
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistent_views_use_real_channel_and_message_ids():
    cog = object.__new__(DockerControlCog)
    cog.bot = MagicMock()
    cog.channel_server_message_ids = {111: {"overview": 1001, "admin_overview": 1002}}

    with patch("cogs.control_ui.is_donations_disabled", return_value=False):
        cog._register_persistent_mech_views()

    registered = []  # (custom_id, message_id, item)
    for call in cog.bot.add_view.call_args_list:
        view = call.args[0]
        for item in view.children:
            registered.append((item.custom_id, call.kwargs.get("message_id"), item))
    ids = {cid for cid, _mid, _item in registered}

    for cid in ("mech_expand_111", "mech_collapse_111", "mech_donate_111", "mech_history_111",
                "mech_private_donate_111", "mech_private_history_111"):
        assert cid in ids
    assert not any(cid.endswith("_0") for cid in ids if cid.startswith("mech_"))

    by_message = {}
    for cid, mid, _item in registered:
        by_message.setdefault(mid, set()).add(cid)
    assert {"admin_button_111", "info_button_111", "help_button_111"} <= by_message[1001]
    assert "admin_overview_stop_all_111" in by_message[1002]

    # Mech selection levels are registered locked; the callback re-checks the live level
    display_buttons = [item for cid, _mid, item in registered if cid.startswith("mech_display_")]
    assert len(display_buttons) == 11
    assert not any(b.unlocked for b in display_buttons)
