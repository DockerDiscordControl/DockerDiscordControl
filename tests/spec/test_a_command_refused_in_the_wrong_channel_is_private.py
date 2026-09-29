# -*- coding: utf-8 -*-
"""/ss and /control refused in the wrong channel answer privately.

THE FINDING (stage 4 review before v3.1.0, section 05 pass 4 F1, verified
2026-09-29). Both commands deferred PUBLICLY first and checked the channel
afterwards. The first followup after a public defer replaces the public
"thinking..." message - ephemeral=True is ignored there - so "Permission
Denied" was shown to the whole channel and never deleted. The spam brake
was moved before the defer for exactly this reason on 2026-09-19; the
channel check was not.

THE CONTRACT: the channel check comes before the defer and its refusal
goes out with respond(ephemeral=True); nothing public is started.

HOW THIS TEST CAN FAIL: a refusal after a public defer again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def cog(monkeypatch):
    import cogs.slash_commands as module
    from cogs.docker_control import DockerControlCog

    instance = DockerControlCog.__new__(DockerControlCog)
    instance._config_service = MagicMock(get_config=lambda: {})
    monkeypatch.setattr(DockerControlCog, "_check_spam_protection", AsyncMock(return_value=True))
    return instance, module


def _ctx():
    ctx = MagicMock()
    ctx.channel.id = 5
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    return ctx


def test_ss_in_a_control_channel_refuses_privately(cog, monkeypatch):
    instance, module = cog
    monkeypatch.setattr(module, "_channel_has_permission", lambda cid, key, cfg: key == "control")
    ctx = _ctx()

    asyncio.run(instance.serverstatus.callback(instance, ctx))

    ctx.defer.assert_not_awaited()
    assert ctx.respond.await_args.kwargs.get("ephemeral") is True


def test_control_in_a_status_channel_refuses_privately(cog, monkeypatch):
    instance, module = cog
    monkeypatch.setattr(module, "_channel_has_permission", lambda cid, key, cfg: key == "serverstatus")
    ctx = _ctx()

    asyncio.run(instance.control.callback(instance, ctx))

    ctx.defer.assert_not_awaited()
    assert ctx.respond.await_args.kwargs.get("ephemeral") is True
