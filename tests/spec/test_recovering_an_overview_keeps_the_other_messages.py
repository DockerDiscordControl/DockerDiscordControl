# -*- coding: utf-8 -*-
"""Recovering a deleted overview does not take the Live Logs with it.

THE FINDING: when the tracked overview is gone - a moderator deleted it - DDC
recreates it, and before posting it ran a CLEAN SWEEP: every bot message in
the channel, with none of the preservation the ordinary cleanup has. Two
things followed.

* The operator's Live Log message and the auto-action notices were deleted
  along with the leftovers. Every other cleanup in the cog uses the variant
  that preserves them.
* In a channel that tracks both overviews (one with /ss, one with /control),
  recovering one swept the OTHER away while its id stayed tracked. A minute
  later that one's edit hit NotFound, recovered, and swept the first back
  out: one channel-wide delete and one post per minute, for ever.

The recovery now uses the preserving cleanup and keeps the channel's other
tracked messages.

COUNTER-CHECK (2026-09-22): red before - the recovery called the clean sweep,
and the other tracked id was not kept.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.docker_control import DockerControlCog

CHANNEL, OVERVIEW, ADMIN = 7, 111, 222


class _Cleanup:
    def __init__(self):
        self.swept = []
        self.preserving = []

    async def clean_sweep_bot_messages(self, **kwargs):
        self.swept.append(kwargs)
        return SimpleNamespace(success=True, messages_deleted=0, messages_found=0,
                               execution_time_ms=1.0, error=None)

    async def delete_bot_messages_preserve_live_logs(self, **kwargs):
        self.preserving.append(kwargs)
        return SimpleNamespace(success=True, messages_deleted=0, method_used="purge",
                               messages_preserved=2, execution_time_ms=1.0, error=None)


@pytest.fixture
def cog(monkeypatch):
    cog = object.__new__(DockerControlCog)
    cog._channel_locks = {}
    cog.channel_server_message_ids = {CHANNEL: {"overview": OVERVIEW, "admin_overview": ADMIN}}
    cog.last_message_update_time = {}
    cog.mech_expanded_states = {}
    cog.pending_actions = {}
    cog._persist_tracked_message_ids = MagicMock()
    cog.cleanup_service = _Cleanup()
    cog._create_overview_embed_collapsed = AsyncMock(return_value=("embed", None))
    monkeypatch.setattr("cogs.control_ui.MechView", lambda *a: "view")
    return cog


def _channel():
    channel = MagicMock()
    channel.id = CHANNEL
    channel.name = "status"
    channel.send = AsyncMock(return_value=SimpleNamespace(id=333))
    return channel


def _recover(cog):
    return asyncio.run(cog._recover_deleted_overview(_channel(), CHANNEL, OVERVIEW, "overview",
                                                     [{"docker_name": "web"}], {}))


def test_the_recovery_preserves_live_logs(cog):
    assert _recover(cog) is True
    assert cog.cleanup_service.swept == [], "the recovery still uses the unfiltered clean sweep"
    assert cog.cleanup_service.preserving, "no cleanup ran at all"


def test_the_other_tracked_overview_is_kept(cog):
    _recover(cog)

    kept = cog.cleanup_service.preserving[0].get("keep_message_ids") or set()
    assert ADMIN in kept, f"the admin overview was swept away: {kept}"
    assert OVERVIEW not in kept, "the message being replaced does not need keeping"


def test_the_new_message_is_tracked(cog):
    """Counter-check: the recovery still does its job."""
    _recover(cog)

    assert cog.channel_server_message_ids[CHANNEL]["overview"] == 333
    assert cog.channel_server_message_ids[CHANNEL]["admin_overview"] == ADMIN
