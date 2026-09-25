# -*- coding: utf-8 -*-
"""A posted overview is remembered, on disk too (channel setup, Phase 3 follow-up).

Found untested during the cog split: _send_control_panel_and_statuses,
_send_all_server_statuses and delete_bot_messages were mentioned by no test.
What matters about them is what the bot remembers afterwards - a message it
forgets is posted a second time after the next restart (FIX C):

* a control channel gets the Admin Overview; its message id is tracked as
  'admin_overview' and written to disk, the channel's other entries stay;
* a status channel gets the server overview; it is the ONLY tracked message
  there afterwards (older entries are dropped), written to disk; with
  force_collapse the mech panel is collapsed first, in memory and in the
  saved state;
* the servers are shown in their configured order;
* a message Discord refuses to take is not tracked;
* deleting DDC's messages keeps the Live Log messages and does nothing in a
  channel that is not a text channel.

COUNTER-CHECK (2026-09-22): written against the existing code; dropping the
persist call in _send_all_server_statuses turns the status test red, and
tracking before the send turns the "refused" test red.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import cogs.channel_lifecycle as lifecycle
from cogs.docker_control import DockerControlCog

CHANNEL = 42
SERVERS = [{"docker_name": "b", "order": 2}, {"docker_name": "a", "order": 1}, {"docker_name": "c"}]


class _TextChannel(discord.TextChannel):
    def __init__(self, channel_id, send=None):
        self.id = channel_id
        self.name = f"chan-{channel_id}"
        self.send = send or AsyncMock(return_value=SimpleNamespace(id=9001))

    def __repr__(self):
        return f"<channel {self.id}>"


@pytest.fixture
def cog(monkeypatch):
    monkeypatch.setattr(lifecycle, "load_config", lambda: {"language": "en"})
    monkeypatch.setattr(lifecycle, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [dict(s) for s in SERVERS]))
    monkeypatch.setattr("cogs.admin_overview.AdminOverviewView", lambda *a: "admin-view")
    monkeypatch.setattr("cogs.control_ui.MechView", lambda *a: "mech-view")
    cog = object.__new__(DockerControlCog)
    cog.channel_server_message_ids = {CHANNEL: {"overview": 1, "old": 2}}
    cog.last_message_update_time = {}
    cog.mech_state_manager = MagicMock()
    cog._persist_tracked_message_ids = MagicMock()
    cog._background_cache_population = AsyncMock()
    cog._create_admin_overview_embed = AsyncMock(return_value=("embed", None, True))
    cog._create_overview_embed_collapsed = AsyncMock(return_value=("embed", None))
    cog._send_message_with_files = AsyncMock(return_value=SimpleNamespace(id=7007))
    return cog


def test_the_admin_overview_is_tracked_and_saved(cog):
    channel = _TextChannel(CHANNEL)
    asyncio.run(cog._send_control_panel_and_statuses(channel))
    channel.send.assert_awaited_once_with(embed="embed", view="admin-view")
    assert cog.channel_server_message_ids[CHANNEL] == {"overview": 1, "old": 2, "admin_overview": 9001}
    cog._persist_tracked_message_ids.assert_called_once()
    shown = cog._create_admin_overview_embed.await_args.args[0]
    assert [s["docker_name"] for s in shown] == ["a", "b", "c"]


def test_the_status_overview_is_the_only_tracked_message(cog):
    asyncio.run(cog._send_all_server_statuses(_TextChannel(CHANNEL)))
    assert cog.channel_server_message_ids[CHANNEL] == {"overview": 7007}
    cog._persist_tracked_message_ids.assert_called_once()
    assert list(cog.last_message_update_time[CHANNEL]) == ["overview"]


def test_a_refused_message_is_not_tracked(cog):
    refused = AsyncMock(side_effect=discord.errors.HTTPException(MagicMock(status=403), "no"))
    asyncio.run(cog._send_control_panel_and_statuses(_TextChannel(CHANNEL, send=refused)))
    assert "admin_overview" not in cog.channel_server_message_ids[CHANNEL]
    cog._persist_tracked_message_ids.assert_not_called()


def test_deleting_keeps_the_live_logs_and_needs_a_text_channel(cog):
    result = SimpleNamespace(success=True, messages_deleted=3, method_used="bulk",
                             messages_preserved=1, execution_time_ms=1.0)
    cog.cleanup_service = SimpleNamespace(delete_bot_messages_preserve_live_logs=AsyncMock(return_value=result))
    asyncio.run(cog.delete_bot_messages(_TextChannel(CHANNEL), limit=50))
    call = cog.cleanup_service.delete_bot_messages_preserve_live_logs.await_args
    assert call.kwargs["channel"].id == CHANNEL and call.kwargs["message_limit"] == 50
    asyncio.run(cog.delete_bot_messages(SimpleNamespace(id=5)))
    assert cog.cleanup_service.delete_bot_messages_preserve_live_logs.await_count == 1
