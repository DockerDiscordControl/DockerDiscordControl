# -*- coding: utf-8 -*-
"""The startup send keeps the tracked /donate panel id, like every other path.

THE FINDING (stage 4 review before v3.1.0, section 04, both passes,
verified 2026-09-29). The id of the panel /donate posts is tracked under
'donation' so that the restart clean-up deletes it instead of leaving a
button that does nothing (a5c4d3658 / test_the_donation_panel_is_not_a_phantom).
send_initial_status still cleared "leftover" keys with its own list -
overview and admin_overview only - and dropped 'donation' with them. When
the startup donation step and the sweep both failed to delete the panel
(Discord 5xx twice), no later start could retry: the dead button stayed.

THE CONTRACT: the startup send clears only kinds DDC does not track;
'donation' is kept (TRACKED_MESSAGE_KINDS, the one list).

HOW THIS TEST CAN FAIL: a second hand-written list of kinds again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord


def test_the_donation_id_survives_the_startup_send(monkeypatch):
    import cogs.channel_lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "logger", MagicMock())
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: SimpleNamespace(get_config=lambda force_reload=False: {
                            "channel_permissions": {"123": {
                                "post_initial": True, "commands": {"serverstatus": True}}}}))

    async def _fast(*_a):
        return None

    monkeypatch.setattr(lifecycle.asyncio, "sleep", _fast)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.name = "status"

    class Cog(lifecycle.ChannelLifecycleMixin):
        pass

    cog = Cog.__new__(Cog)
    cog.bot = SimpleNamespace(wait_until_ready=AsyncMock(), fetch_channel=AsyncMock(return_value=channel))
    cog.channel_server_message_ids = {123: {"donation": 777, "valheim": 1}}
    cog.last_channel_activity = {}
    cog.initial_messages_sent = False
    cog._background_cache_population = AsyncMock()
    cog._delete_tracked_overview_messages = AsyncMock()
    cog.delete_bot_messages = AsyncMock()
    cog._get_channel_lock = lambda cid: asyncio.Lock()

    async def _send(ch):
        cog.channel_server_message_ids[ch.id]["overview"] = 999

    cog._send_all_server_statuses = _send

    asyncio.run(cog.send_initial_status())

    tracked = cog.channel_server_message_ids[123]
    assert tracked.get("donation") == 777, tracked
    assert "valheim" not in tracked, "a real leftover of the old architecture stays"
