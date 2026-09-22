# -*- coding: utf-8 -*-
"""/control replaces its admin overview instead of leaving a second one.

THE FINDING: /ss deletes the overview it tracks before posting a new one -
that is what stops duplicates. /control does not: it posts a second admin
overview and writes the new id over the old one, so the previous message
stays in the channel, untracked, and nothing edits or removes it again. Two
admin panels, one of them frozen at the moment it was posted, with buttons
that still work.

COUNTER-CHECK (2026-09-22): red before - the old message was never deleted.
A first /control in a channel must still work (second test).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.docker_control import DockerControlCog

CHANNEL, OLD, NEW = 9, 900, 901


def _ctx():
    ctx = MagicMock()
    ctx.channel_id = CHANNEL
    ctx.channel.id = CHANNEL
    ctx.channel.name = "control"
    ctx.defer = AsyncMock()
    ctx.followup.send = AsyncMock(return_value=SimpleNamespace(id=NEW))
    ctx.author = "operator"
    return ctx


def _cog(tracked, deleted, fails=False):
    cog = object.__new__(DockerControlCog)
    cog._config_service = SimpleNamespace(get_config=lambda force_reload=False: {})
    cog._initial_config = {}

    cog.channel_server_message_ids = {CHANNEL: dict(tracked)} if tracked else {}
    cog._channel_locks = {}
    cog._persist_tracked_message_ids = MagicMock()
    cog._check_spam_protection = AsyncMock(return_value=True)
    cog._create_admin_overview_embed = AsyncMock(return_value=("embed", None, True))

    def _partial(message_id):
        async def _delete():
            if fails:
                raise discord.errors.HTTPException(MagicMock(status=500), "later")
            deleted.append(message_id)

        return SimpleNamespace(delete=_delete)

    cog.bot = SimpleNamespace(get_channel=lambda cid: SimpleNamespace(
        get_partial_message=_partial, id=cid))
    return cog


def _run(cog, ctx):
    with patch("cogs.slash_commands._channel_has_permission", return_value=True), \
         patch("cogs.slash_commands.load_config", return_value={"language": "en"}), \
         patch("cogs.slash_commands.get_server_config_service",
               lambda: SimpleNamespace(get_all_servers=lambda: [{"docker_name": "web"}])), \
         patch("cogs.admin_overview.AdminOverviewView", lambda *a: "view"):
        asyncio.run(cog.control.callback(cog, ctx))  # the command object wraps the coroutine


def test_the_previous_admin_overview_is_deleted():
    deleted = []
    cog = _cog({"admin_overview": OLD}, deleted)
    ctx = _ctx()

    _run(cog, ctx)

    assert deleted == [OLD], (f"the old admin overview stayed in the channel: {deleted}; "
                              f"what was sent: {ctx.followup.send.await_args_list}")
    assert cog.channel_server_message_ids[CHANNEL]["admin_overview"] == NEW


def test_the_first_control_in_a_channel_still_works():
    """Counter-check: nothing to delete is not an error."""
    deleted = []
    cog = _cog({}, deleted)
    ctx = _ctx()

    _run(cog, ctx)

    assert deleted == []
    assert cog.channel_server_message_ids[CHANNEL]["admin_overview"] == NEW


def test_a_delete_that_fails_is_remembered_for_later():
    deleted = []
    cog = _cog({"admin_overview": OLD}, deleted, fails=True)

    _run(cog, _ctx())

    assert OLD in getattr(cog, "_undeleted_messages", {}).get(CHANNEL, set())
    assert cog.channel_server_message_ids[CHANNEL]["admin_overview"] == NEW
