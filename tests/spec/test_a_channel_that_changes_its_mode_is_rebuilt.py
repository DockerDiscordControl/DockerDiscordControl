# -*- coding: utf-8 -*-
"""A channel switched from status to control is rebuilt, not left as it was.

THE FINDING: the channel hot-reload compares the configured channel ids with
the tracked ones and acts on the difference - added and removed. A channel
that stays but changes what it is FOR is in neither set: switching it from
"serverstatus" to "control" in the panel logs "no channels added or removed"
and leaves the server overview sitting there. The operator sees no admin
panel until DDC restarts or the inactivity regeneration happens to fire.

What DDC tracks says which mode a channel was built in: 'overview' for a
status channel, 'admin_overview' for a control channel. A channel whose
configuration no longer matches what it was built as is torn down and set up
again.

COUNTER-CHECK (2026-09-22): red before - the switched channel was not touched
at all. A channel whose mode did not change must stay untouched (second
test).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.docker_control import DockerControlCog

CHANNEL = 101


def _cog(tracked, permissions, monkeypatch):
    cog = object.__new__(DockerControlCog)
    cog.bot = SimpleNamespace(wait_until_ready=AsyncMock())
    cog.channel_server_message_ids = {CHANNEL: dict(tracked)}
    cog._channel_locks = {}
    cog.last_message_update_time = {}
    cog.last_channel_activity = {}
    cog.last_glvl_per_channel = {}
    cog._persist_tracked_message_ids = MagicMock()
    cog._teardown_channel = AsyncMock()
    cog._setup_channel = AsyncMock()
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: SimpleNamespace(get_config=lambda force_reload=False: {
                            "channel_permissions": permissions}))
    monkeypatch.setattr("cogs.channel_lifecycle.asyncio.sleep", AsyncMock())
    return cog


def _perm(control=False, status=False):
    return {"commands": {"control": control, "serverstatus": status}, "post_initial": True}


def test_a_status_channel_turned_into_a_control_channel_is_rebuilt(monkeypatch):
    cog = _cog({"overview": 5}, {str(CHANNEL): _perm(control=True)}, monkeypatch)

    asyncio.run(cog._apply_channel_config_changes())

    cog._teardown_channel.assert_awaited_once_with(CHANNEL)
    assert cog._setup_channel.await_args.args[0] == CHANNEL


def test_a_control_channel_turned_into_a_status_channel_is_rebuilt(monkeypatch):
    cog = _cog({"admin_overview": 6}, {str(CHANNEL): _perm(status=True)}, monkeypatch)

    asyncio.run(cog._apply_channel_config_changes())

    cog._setup_channel.assert_awaited_once()


def test_an_unchanged_channel_is_left_alone(monkeypatch):
    """Counter-check: a save that changes nothing must not repost anything."""
    cog = _cog({"overview": 5}, {str(CHANNEL): _perm(status=True)}, monkeypatch)

    asyncio.run(cog._apply_channel_config_changes())

    cog._teardown_channel.assert_not_awaited()
    cog._setup_channel.assert_not_awaited()


def test_a_channel_with_both_permissions_is_left_alone(monkeypatch):
    """Counter-check: control wins when both are set, and that is how it was
    built - nothing to do."""
    cog = _cog({"admin_overview": 6}, {str(CHANNEL): _perm(control=True, status=True)}, monkeypatch)

    asyncio.run(cog._apply_channel_config_changes())

    cog._setup_channel.assert_not_awaited()
