# -*- coding: utf-8 -*-
"""The overview's mech picture changes when the mech does.

THE FINDING (operator, 2026-09-29). The mech ran out of power between two
donations. Its details (Mech button) said OFFLINE, the overview in the
channel kept showing it walking. The animation is attached when the overview
is posted; the periodic edit sent the embed only ("can't add files to edit"),
so the attached picture stayed whatever it was at posting time - a level-up
or a speed change never reached it either. Only a donation event, through
the event-driven path, could recreate the message.

THE CONTRACT: the periodic edit replaces the attachment when the picture's
key - evolution level, speed level, offline - differs from the one it last
put on that message, and once after a restart, when that is not known.
An unchanged picture is not uploaded again: the edit stays an embed edit on
the partial message, with no extra fetch.

HOW THIS TEST CAN FAIL: a mech that goes offline keeps its old picture, or
every minute's edit uploads the animation again.

COUNTER-CHECK (2026-09-29): with the edit sending the embed only (the old
line) all four go red - no file ever reaches Discord;
with the key comparison removed so every edit uploads, the unchanged test
goes red.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


@pytest.fixture
def cog(monkeypatch):
    import cogs.message_updates as message_updates
    import cogs.mech_ui as mech_ui
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(message_updates, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: []))
    monkeypatch.setattr(mech_ui, "MechView", lambda *_args: "view")

    cog = DockerControlCog.__new__(DockerControlCog)
    cog._config_service = SimpleNamespace(get_config=lambda: {})
    cog.ordered_server_names = []
    cog.last_message_update_time = {}
    cog.channel_server_message_ids = {111: {"overview": 9001}}
    cog._ensure_status_cache_fresh = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.partial = MagicMock()
    channel.partial.edit = AsyncMock()
    channel.full = MagicMock()
    channel.full.edit = AsyncMock()
    channel.get_partial_message = MagicMock(return_value=channel.partial)
    channel.fetch_message = AsyncMock(return_value=channel.full)
    cog.bot = SimpleNamespace(fetch_channel=AsyncMock(return_value=channel))
    cog.channel = channel

    cog.mech = {"key": (5, 3, False)}

    async def _collapsed(_servers, _config):
        cog._collapsed_animation_key = cog.mech["key"]
        return "embed", discord.File(__file__, filename="mech_animation.webp")

    cog._create_overview_embed_collapsed = _collapsed
    return cog


def _uploads(channel):
    return [c.kwargs["file"] for c in channel.full.edit.await_args_list if "file" in c.kwargs]


@pytest.mark.asyncio
async def test_the_first_edit_after_a_restart_puts_the_current_picture_on(cog):
    assert await cog._update_overview_message(111, 9001, "overview") is True

    assert len(_uploads(cog.channel)) == 1
    assert cog.channel.full.edit.await_args.kwargs["attachments"] == []
    cog.channel.partial.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unchanged_picture_is_not_uploaded_again(cog):
    await cog._update_overview_message(111, 9001, "overview")
    await cog._update_overview_message(111, 9001, "overview")
    await cog._update_overview_message(111, 9001, "overview")

    assert len(_uploads(cog.channel)) == 1
    assert cog.channel.fetch_message.await_count == 1
    assert cog.channel.partial.edit.await_count == 2
    assert all("file" not in c.kwargs for c in cog.channel.partial.edit.await_args_list)


@pytest.mark.asyncio
async def test_a_mech_that_runs_dry_gets_the_offline_picture(cog):
    await cog._update_overview_message(111, 9001, "overview")
    cog.mech["key"] = (5, 3, True)      # power reached 0
    await cog._update_overview_message(111, 9001, "overview")

    assert len(_uploads(cog.channel)) == 2
    assert cog.channel.full.edit.await_args.kwargs["attachments"] == []


@pytest.mark.asyncio
async def test_a_level_up_changes_the_picture_too(cog):
    await cog._update_overview_message(111, 9001, "overview")
    cog.mech["key"] = (6, 3, False)
    await cog._update_overview_message(111, 9001, "overview")

    assert len(_uploads(cog.channel)) == 2


# ---------------------------------------------------------------------------
# Final check before v3.1.0 (2026-09-29), two holes in the swap above.
#
# 1. The key held the raw speed level, which moves with every cent of decay,
#    while the cache picks the picture in 5% steps: the same frames went up
#    again every few ten minutes per channel. The key uses the cache's steps.
# 2. A swap that failed (no Read Message History for fetch_message, no Attach
#    Files, an upload refused) returned False before the plain edit: the
#    overview and its "last update" froze on every beat. It falls back now.
#
# COUNTER-CHECK (2026-09-29): with the raw speed in animation_key the step
# test goes red; with the fallback removed the failed-swap test goes red.
# ---------------------------------------------------------------------------

def test_the_key_moves_in_the_steps_the_picture_does():
    from cogs.overview_embeds import animation_key
    from services.mech.animation_cache_service import get_animation_cache_service

    cache = get_animation_cache_service()

    assert animation_key(6, 41, 4.2, cache) == animation_key(6, 42, 4.1, cache)
    assert animation_key(6, 41, 4.2, cache) != animation_key(6, 49, 4.2, cache)
    assert animation_key(6, 41, 0, cache)[2] is True


@pytest.mark.asyncio
async def test_a_failed_swap_still_updates_the_status(cog):
    cog.channel.fetch_message = AsyncMock(side_effect=discord.Forbidden(
        MagicMock(status=403, reason="Forbidden"), "Missing Access"))

    assert await cog._update_overview_message(111, 9001, "overview") is True

    cog.channel.partial.edit.assert_awaited_once()
    assert 111 in cog.last_message_update_time
