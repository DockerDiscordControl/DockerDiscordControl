# -*- coding: utf-8 -*-
"""One channel failing at startup does not stop the others, and is logged.

THE FINDING (stage 4 review before v3.1.0, section 04 pass 4 F1, verified
2026-09-29 in a corrected form). send_initial_status caught only
DiscordException, RuntimeError, OSError (and ValueError outside). Any other
exception from one channel's work ended the whole loop and left DDC's log
without an ERROR. A confirmed trigger: aiohttp.ServerDisconnectedError from
channel.send - py-cord re-raises only OSError, and that one is not. The
failing channel was already swept (blank, untracked); every later channel
got no activity time, so its inactivity recreation was off.

THE CONTRACT: whatever one channel raises (short of a cancellation) is
logged as an ERROR naming it, and the next channel is still set up.

HOW THIS TEST CAN FAIL: an unexpected exception type escapes the loop again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord


def test_a_disconnect_in_one_channel_leaves_the_next_one_set_up(monkeypatch):
    import cogs.channel_lifecycle as lifecycle

    log = MagicMock()
    monkeypatch.setattr(lifecycle, "logger", log)
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: SimpleNamespace(get_config=lambda force_reload=False: {
                            "channel_permissions": {
                                "111": {"post_initial": True, "commands": {"serverstatus": True}},
                                "222": {"post_initial": True, "commands": {"serverstatus": True}}}}))

    async def _fast(*_a):
        return None

    monkeypatch.setattr(lifecycle.asyncio, "sleep", _fast)

    def _channel(cid):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = cid
        channel.name = f"c{cid}"
        return channel

    class Cog(lifecycle.ChannelLifecycleMixin):
        pass

    cog = Cog.__new__(Cog)
    cog.bot = SimpleNamespace(wait_until_ready=AsyncMock(),
                              fetch_channel=AsyncMock(side_effect=lambda cid: _channel(cid)))
    cog.channel_server_message_ids = {}
    cog.last_channel_activity = {}
    cog.initial_messages_sent = False
    cog._background_cache_population = AsyncMock()
    cog._delete_tracked_overview_messages = AsyncMock()
    cog.delete_bot_messages = AsyncMock()
    locks = {}
    cog._get_channel_lock = lambda cid: locks.setdefault(cid, asyncio.Lock())

    async def _send(ch):
        if ch.id == 111:
            raise aiohttp.ServerDisconnectedError()
        cog.channel_server_message_ids.setdefault(ch.id, {})["overview"] = 999

    cog._send_all_server_statuses = _send

    asyncio.run(cog.send_initial_status())      # must not raise

    assert cog.channel_server_message_ids.get(222) == {"overview": 999}, "the next channel was never set up"
    assert "111" in " ".join(str(c) for c in log.error.call_args_list), "the failure was never logged"
