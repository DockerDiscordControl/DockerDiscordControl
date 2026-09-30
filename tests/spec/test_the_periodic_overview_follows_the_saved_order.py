# -*- coding: utf-8 -*-
"""The periodic overview edit uses the container order saved in the panel now.

THE FINDING (stage 4 review before v3.1.0, section 40 pass 4): the
periodic edit ordered the containers by self.ordered_server_names, loaded
once at the cog's start and never refreshed, while the donation/event
recreate read server_order.json fresh. After the operator reordered the
containers in the web panel, the periodic overview kept the old order
until a restart; each donation reposted it in the new order, and the next
periodic edit reverted it.

THE CONTRACT: both paths read the saved order when they draw; the start's
order is only the fallback for an empty file.

HOW THIS TEST CAN FAIL: the periodic edit draws the start's order again.

COUNTER-CHECK (2026-09-30): red before the change (['a', 'b']).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest

import cogs.message_updates as message_updates

SERVERS = [{"name": "a", "docker_name": "a"}, {"name": "b", "docker_name": "b"}]


@pytest.fixture
def cog(monkeypatch):
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(message_updates, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [dict(s) for s in SERVERS]))
    monkeypatch.setattr(message_updates, "load_config", lambda: {})
    cog = DockerControlCog.__new__(DockerControlCog)
    cog.ordered_server_names = ["a", "b"]           # the order at the cog's start
    cog._config_service = SimpleNamespace(get_config=lambda: {})
    channel = MagicMock(spec=discord.TextChannel)

    async def fetch_channel(channel_id):
        return channel
    cog.bot = SimpleNamespace(fetch_channel=fetch_channel)
    cog.channel_server_message_ids = {111: {"overview": 9001}}

    async def fresh():
        return None
    cog._ensure_status_cache_fresh = fresh
    drawn = []

    async def draw(ordered_servers, config):
        drawn.append([server["docker_name"] for server in ordered_servers])
        raise RuntimeError("drawn - the rest of the edit is not under test")
    cog._create_overview_embed_collapsed = draw
    return cog, drawn


@pytest.mark.asyncio
async def test_the_saved_order_is_drawn(cog, monkeypatch):
    instance, drawn = cog
    monkeypatch.setattr("services.docker_service.server_order.load_server_order", lambda: ["b", "a"])
    await instance._update_overview_message(111, 9001, "overview")
    assert drawn == [["b", "a"]]


@pytest.mark.asyncio
async def test_an_empty_saved_order_falls_back_to_the_start(cog, monkeypatch):
    instance, drawn = cog
    monkeypatch.setattr("services.docker_service.server_order.load_server_order", lambda: [])
    await instance._update_overview_message(111, 9001, "overview")
    assert drawn == [["a", "b"]]
