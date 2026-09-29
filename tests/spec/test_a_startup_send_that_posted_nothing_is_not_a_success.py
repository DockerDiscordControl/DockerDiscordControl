# -*- coding: utf-8 -*-
"""A startup send that posted nothing is not logged as a success.

THE FINDING (stage 4 review before v3.1.0, section 04 pass 3 F1, verified
2026-09-29 in a corrected form). send_initial_status clears a channel and
posts the overview again. The two posting helpers catch a Discord error and
just return - and send_initial_status then logged "Successfully
regenerated channel", counted the start as successful and left an empty,
unbuilt tracking entry behind. The channel stood blank, the log said all
was well. _setup_channel has asked channel_was_built() for exactly this
for exactly this case; this path never did.

THE CONTRACT: after the send the channel is asked whether anything was
built; if not, it is an ERROR, not a success, and no empty entry is left.
The activity time stays set so the inactivity loop still retries.

HOW THIS TEST CAN FAIL: the send is logged as successful without looking.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

CHANNEL = 123


def _world(monkeypatch, posts):
    import cogs.channel_lifecycle as lifecycle

    log = MagicMock()
    monkeypatch.setattr(lifecycle, "logger", log)
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: SimpleNamespace(get_config=lambda force_reload=False: {
                            "channel_permissions": {str(CHANNEL): {
                                "post_initial": True, "commands": {"serverstatus": True}}}}))

    async def _fast(*_a):
        return None

    monkeypatch.setattr(lifecycle.asyncio, "sleep", _fast)

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CHANNEL
    channel.name = "status"

    class Cog(lifecycle.ChannelLifecycleMixin):
        pass

    cog = Cog.__new__(Cog)
    cog.bot = SimpleNamespace(wait_until_ready=AsyncMock(), fetch_channel=AsyncMock(return_value=channel))
    cog.channel_server_message_ids = {}
    cog.last_channel_activity = {}
    cog.initial_messages_sent = False
    cog._background_cache_population = AsyncMock()
    cog._delete_tracked_overview_messages = AsyncMock()
    cog.delete_bot_messages = AsyncMock()
    locks = {}
    cog._get_channel_lock = lambda cid: locks.setdefault(cid, asyncio.Lock())

    async def _send(ch):
        if posts:
            cog.channel_server_message_ids.setdefault(ch.id, {})["overview"] = 999
        # else: the helper caught its Discord error and returned

    cog._send_all_server_statuses = _send
    return cog, log


def _said(log, level):
    return " ".join(str(c) for c in getattr(log, level).call_args_list)


def test_nothing_posted_is_an_error_not_a_success(monkeypatch):
    cog, log = _world(monkeypatch, posts=False)

    asyncio.run(cog.send_initial_status())

    assert "Successfully regenerated" not in _said(log, "info")
    assert str(CHANNEL) in _said(log, "error") or "status" in _said(log, "error")
    assert "Success: False" in _said(log, "info")
    assert cog.channel_server_message_ids.get(CHANNEL) in (None,), cog.channel_server_message_ids
    assert CHANNEL in cog.last_channel_activity, "the inactivity loop would never retry"


def test_a_real_post_is_still_a_success(monkeypatch):
    """Counter-check."""
    cog, log = _world(monkeypatch, posts=True)

    asyncio.run(cog.send_initial_status())

    assert "Successfully regenerated" in _said(log, "info")
    assert "Success: True" in _said(log, "info")
