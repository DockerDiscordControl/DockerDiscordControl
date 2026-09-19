# -*- coding: utf-8 -*-
"""/serverstatus must deliver the cooldown refusal PRIVATELY.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. The behaviour change has been decided:
"check before defer".

THE FINDING. ``serverstatus`` defers PUBLICLY (``ctx.defer()`` without
ephemeral) and only checks the spam protection afterwards. The refusal goes out
via followup and thereby replaces the public "is thinking..." message - the
whole channel sees "Command on cooldown". So the spam protection of all things
produced channel noise.

THE FIX: the brake runs BEFORE the defer and refuses via
``ctx.respond(..., ephemeral=True)``. The price, stated openly: there is now a
config-file read before the defer; on a heavily overloaded bot the risk of
"Unknown interaction" (10062) rises minimally. The operator weighed it that
way.

A CORRECTION OF MY QUESTION: I had named /donate as public too. Measured,
/donate defers with ``ctx.defer(ephemeral=True)``; the followup refusal
inherits that and was never public. /donate therefore stays unchanged - the
boundary test below records the reason.

HOW IT IS CHECKED HERE: the command function is called via ``.callback`` with a
stand-in cog whose ``_check_spam_protection`` is the REAL method - against a
real service. The order of brake and defer is recorded in ONE shared log.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.infrastructure.spam_protection_service import SpamProtectionService
from tests.spec import is_not_awaitable_error

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 9955


class _Service:
    """Real service; is_on_cooldown records itself in the shared log."""

    def __init__(self, real, sequence):
        self._real = real
        self._sequence = sequence

    def is_on_cooldown(self, user_id, action_type, kind="button"):
        self._sequence.append("brake")
        return self._real.is_on_cooldown(user_id, action_type, kind=kind)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _setup(tmp_path, blocked):
    sequence = []
    real = SpamProtectionService(config_dir=str(tmp_path))
    if blocked:
        real.add_user_cooldown(USER, "serverstatus", kind="command")
    ctx = MagicMock()
    ctx.author.id = USER
    ctx.defer = AsyncMock(side_effect=lambda *a, **k: sequence.append("defer"))
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    cog = MagicMock()

    async def _check(c, name):
        return await DockerControlCog._check_spam_protection(cog, c, name)

    cog._check_spam_protection = _check
    return _Service(real, sequence), sequence, ctx, cog


async def _call(command, cog, ctx, service):
    with patch(SPAM_PATH, return_value=service):
        try:
            await command.callback(cog, ctx)
        except TypeError as e:
            # Only from deep AFTER brake and defer (cog methods on a
            # MagicMock). The tests assert POSITIVELY via the log.
            if not is_not_awaitable_error(e):
                raise


@pytest.mark.asyncio
async def test_the_refusal_is_private(tmp_path):
    """THE FINDING: the refusal appears for the whole channel."""
    service, sequence, ctx, cog = _setup(tmp_path, blocked=True)

    await _call(DockerControlCog.serverstatus, cog, ctx, service)

    ctx.followup.send.assert_not_awaited()
    ctx.defer.assert_not_awaited()
    ctx.respond.assert_awaited_once()
    assert "on cooldown" in ctx.respond.await_args.args[0]
    assert ctx.respond.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_the_brake_runs_before_the_defer(tmp_path):
    """THE FINDING, order - in the normal case too, otherwise the private
    refusal would only be a coincidence of the blocked case."""
    service, sequence, ctx, cog = _setup(tmp_path, blocked=False)

    await _call(DockerControlCog.serverstatus, cog, ctx, service)

    assert sequence[:2] == ["brake", "defer"], (
        f"Sequence {sequence!r}: the brake must run BEFORE the defer."
    )


@pytest.mark.asyncio
async def test_donate_defers_privately(tmp_path):
    """Boundary and the reason why /donate stays unchanged: it defers
    ephemerally, and the followup refusal inherits that. If it ever deferred
    publicly, the finding would be back there."""
    service, sequence, ctx, cog = _setup(tmp_path, blocked=False)

    with patch("services.donation.donation_utils.is_donations_disabled", return_value=False):
        await _call(DockerControlCog.donate_command, cog, ctx, service)

    assert ctx.defer.await_args_list[0].kwargs.get("ephemeral") is True
