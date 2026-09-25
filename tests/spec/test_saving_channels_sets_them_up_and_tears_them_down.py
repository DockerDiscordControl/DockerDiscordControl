# -*- coding: utf-8 -*-
"""Saving the channel list applies it without a restart (channel hot-reload).

Found untested during the cog split (Phase 3): _apply_channel_config_changes,
_teardown_channel and _setup_channel were mentioned by no test. What they
promise, pinned here:

* a channel no longer in channel_permissions is torn down: DDC's messages in
  it are deleted and its tracking (message ids, also on disk, lock, activity,
  mech state) is dropped - the other channels keep theirs;
* a newly added control channel gets the Admin Overview, a newly added status
  channel the server overview (collapsed), both after the
  old DDC messages were cleaned up;
* a newly added channel with "post initial" off is only tracked - nothing is
  deleted or posted in it;
* a channel with neither control nor status permission gets nothing;
* keys that are not channel ids are ignored, and an unchanged list does
  nothing at all.

COUNTER-CHECK (2026-09-22): written against the existing code, so first
checked that each test can fail: swapping the modes in _setup_channel turns
the two mode tests red; not popping the tracking in _teardown_channel turns
the teardown test red.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.docker_control import DockerControlCog

KEPT, GONE, NEW = 101, 202, 303


class _TextChannel(discord.TextChannel):
    def __init__(self, channel_id):  # no Discord state needed
        self.id = channel_id
        self.name = f"chan-{channel_id}"

    def __repr__(self):  # discord's needs Discord state
        return f"<channel {self.id}>"


def _cog(permissions):
    cog = object.__new__(DockerControlCog)
    cog.bot = SimpleNamespace(wait_until_ready=AsyncMock(),
                              get_channel=lambda cid: _TextChannel(cid),
                              fetch_channel=AsyncMock(side_effect=lambda cid: _TextChannel(cid)))
    cog.channel_server_message_ids = {KEPT: {"overview": 1}, GONE: {"overview": 2}}
    cog._channel_locks = {}
    cog.last_message_update_time = {KEPT: 1, GONE: 1}
    cog.last_channel_activity = {KEPT: 1, GONE: 1}
    cog.last_glvl_per_channel = {KEPT: 3, GONE: 3}
    cog._persist_tracked_message_ids = MagicMock()
    cog.delete_bot_messages = AsyncMock()
    cog._delete_tracked_overview_messages = AsyncMock()
    cog._background_cache_population = AsyncMock()

    # The real senders track the message they posted, and since 2026-09-22 a setup
    # that tracked nothing is reported and left untracked
    # (tests/spec/test_a_channel_whose_first_message_failed_is_not_forgotten.py).
    def _tracking_sender(key):
        async def _send(channel, **kwargs):
            cog.channel_server_message_ids.setdefault(channel.id, {})[key] = 999
        return AsyncMock(side_effect=_send)

    cog._send_control_panel_and_statuses = _tracking_sender("admin_overview")
    cog._send_all_server_statuses = _tracking_sender("overview")
    cog._config = {"channel_permissions": permissions}
    return cog


@pytest.fixture(autouse=True)
def config(monkeypatch):
    holder = {}

    def _service():
        return SimpleNamespace(get_config=lambda force_reload=False: holder["cog"]._config)

    monkeypatch.setattr("services.config.config_service.get_config_service", _service)
    monkeypatch.setattr("cogs.channel_lifecycle.asyncio.sleep", AsyncMock())
    return holder


def _perm(control=False, status=False, post_initial=True):
    return {"commands": {"control": control, "serverstatus": status}, "post_initial": post_initial}


def _run(config, permissions):
    cog = _cog(permissions)
    config["cog"] = cog
    asyncio.run(cog._apply_channel_config_changes())
    return cog


def _deleted_in(mock):
    return [call.args[0].id for call in mock.await_args_list]


def test_a_removed_channel_is_torn_down_and_the_others_keep_theirs(config):
    cog = _run(config, {str(KEPT): _perm(status=True)})
    assert _deleted_in(cog.delete_bot_messages) == [GONE]
    assert list(cog.channel_server_message_ids) == [KEPT]
    cog._persist_tracked_message_ids.assert_called()
    for tracked in (cog.last_message_update_time, cog.last_channel_activity,
                    cog.last_glvl_per_channel):
        assert list(tracked) == [KEPT]


def test_an_added_control_channel_gets_the_admin_overview(config):
    cog = _run(config, {str(KEPT): _perm(status=True), str(GONE): _perm(status=True),
                        str(NEW): _perm(control=True, status=True)})
    assert _deleted_in(cog._delete_tracked_overview_messages) == [NEW]
    assert _deleted_in(cog.delete_bot_messages) == [NEW]
    assert _deleted_in(cog._send_control_panel_and_statuses) == [NEW]
    cog._send_all_server_statuses.assert_not_awaited()
    assert NEW in cog.last_channel_activity


def test_an_added_status_channel_gets_the_collapsed_overview(config):
    cog = _run(config, {str(KEPT): _perm(status=True), str(GONE): _perm(status=True),
                        str(NEW): _perm(status=True)})
    cog._send_control_panel_and_statuses.assert_not_awaited()
    call = cog._send_all_server_statuses.await_args
    assert call.args[0].id == NEW
    assert call.kwargs == {}


def test_post_initial_off_only_tracks_the_channel(config):
    cog = _run(config, {str(KEPT): _perm(status=True), str(GONE): _perm(status=True),
                        str(NEW): _perm(control=True, post_initial=False)})
    cog.delete_bot_messages.assert_not_awaited()
    cog._send_control_panel_and_statuses.assert_not_awaited()
    assert NEW in cog.last_channel_activity


def test_a_channel_without_permissions_gets_nothing(config):
    cog = _run(config, {str(KEPT): _perm(status=True), str(GONE): _perm(status=True),
                        str(NEW): _perm()})
    cog.delete_bot_messages.assert_not_awaited()
    cog._send_control_panel_and_statuses.assert_not_awaited()
    cog._send_all_server_statuses.assert_not_awaited()


def test_an_unchanged_list_and_foreign_keys_do_nothing(config):
    cog = _run(config, {str(KEPT): _perm(status=True), str(GONE): _perm(status=True),
                        "default": _perm(control=True)})
    cog.delete_bot_messages.assert_not_awaited()
    cog.bot.fetch_channel.assert_not_awaited()
    assert set(cog.channel_server_message_ids) == {KEPT, GONE}
