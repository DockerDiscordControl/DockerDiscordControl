# -*- coding: utf-8 -*-
"""Slash commands must brake through the spam service.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``DockerControlCog._check_spam_protection``
(``docker_control.py:1721``) is the path of all slash commands
(serverstatus, control, help, ping, donate, info). It fetches only the
DURATION from the service and does the bookkeeping itself - in a dictionary
that it attaches FROM OUTSIDE to the service object
(``spam_manager._command_cooldowns``).

THREE CONSEQUENCES:

1. The COMMAND per-minute limit from the panel (max_commands_per_minute) has
   no effect - it counts in ``add_user_cooldown``, and this path never arrives
   there. That was the last of the thirteen spots with their own bookkeeping.
2. The attached dictionary is NEVER cleaned up; per user and command it grows
   for the lifetime of the process.
3. A foreign attribute on the service is state the service itself does not
   know about - nobody reading the service sees it.

WHAT STAYS THE SAME, measured: the duration (``get_command_cooldown``), the
message (already translated), the delivery path (``followup`` for deferred
commands, otherwise ``respond``).

PREREQUISITE, and the reason for the order: only since commit 8f47f7c can a
command identify itself with ``kind="command"`` (then named ``art="befehl"``).
Before that, the change would have thrown commands and buttons of the same
name (/info and the info button) into one bucket.

A DECISION, stated openly: a command with cooldown 0 stays without a
per-command pause, but counts towards the per-minute window. "0" means "no
pause for this command", not "exempt from the per-minute limit".

NOT PART OF THIS FINDING: for deferred commands the cooldown message goes out
via followup WITHOUT ephemeral - it is visible to the whole channel. A
separate behaviour question, unchanged here.

HOW IT IS CHECKED HERE: the method does not use ``self``; it is therefore
called unbound instead of building the cog with its more than 4,000 lines. The
service is a REAL SpamProtectionService, only passed through for recording.
"""

import inspect
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 3141
NOW = 70_000.0
CHECK = DockerControlCog._check_spam_protection


class _Recorder:
    """Passes through to the REAL service and records calls including kind."""

    def __init__(self, real):
        self.__dict__["_real"] = real
        self.__dict__["asked"] = []
        self.__dict__["recorded"] = []

    def is_on_cooldown(self, user_id, action_type, kind="button"):
        self.asked.append((user_id, action_type, kind))
        return self._real.is_on_cooldown(user_id, action_type, kind=kind)

    def add_user_cooldown(self, user_id, action_type, kind="button"):
        self.recorded.append((user_id, action_type, kind))
        return self._real.add_user_cooldown(user_id, action_type, kind=kind)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        # If someone attaches something to the service, it lands on the REAL
        # service - where the test sees it.
        setattr(self._real, name, value)


def _service(tmp_path):
    return _Recorder(SpamProtectionService(config_dir=str(tmp_path)))


def _ctx():
    ctx = MagicMock()
    ctx.author.id = USER
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    return ctx


async def _check(service, name):
    ctx = _ctx()
    with patch(SPAM_PATH, return_value=service):
        allowed = await CHECK(MagicMock(), ctx, name)
    return allowed, ctx


def test_the_check_exists_and_is_async():
    """Safeguard against a blunt tool."""
    assert inspect.iscoroutinefunction(CHECK)
    assert list(inspect.signature(CHECK).parameters) == ["self", "ctx", "command_name"]


@pytest.mark.asyncio
async def test_the_service_is_asked_and_recorded_as_a_command(tmp_path):
    """THE FINDING: the stateful methods are never called."""
    service = _service(tmp_path)

    allowed, _ = await _check(service, "ping")

    assert allowed is True
    assert service.asked == [(USER, "ping", "command")], (
        f"is_on_cooldown was not called as a command with 'ping', but "
        f"{service.asked!r}. The command path brakes past the service."
    )
    assert service.recorded == [(USER, "ping", "command")]


@pytest.mark.asyncio
# serverstatus uses "respond" since 2026-09-19: the brake runs there BEFORE the
# defer (test_serverstatus_refuses_privately.py). donate defers ephemerally
# and stays with followup.
@pytest.mark.parametrize("name,route", [("ping", "respond"), ("serverstatus", "respond"),
                                      ("donate", "followup")])
async def test_a_recorded_command_is_refused(tmp_path, monkeypatch, name, route):
    """THE FINDING, effect - on the delivery path this command takes today.

    With a frozen clock, so that the remaining time in the message is exactly
    the duration of the command slider and can be checked (otherwise a
    message "try again in 0 seconds" would survive every test).
    """
    monkeypatch.setattr(time, "time", lambda: NOW)
    service = _service(tmp_path)
    duration = service._real.get_command_cooldown(name)
    assert duration > 0, f"/{name} has no cooldown - the test would prove nothing."
    service._real.add_user_cooldown(USER, name, kind="command")

    allowed, ctx = await _check(service, name)

    assert allowed is False, (
        f"/{name} is recorded in the service as a command and is still "
        "let through."
    )
    sender = ctx.followup.send if route == "followup" else ctx.respond
    sender.assert_awaited_once()
    message = sender.await_args.args[0]
    assert "on cooldown" in message
    assert f"in {duration} seconds" in message, (
        f"The message does not state the remaining time {duration} s: {message!r}"
    )
    if route == "respond":
        # Only the user who asked sees the refusal. For the followup path that
        # does NOT hold today - an open behaviour question, deliberately not pinned down here.
        assert sender.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_nothing_is_attached_to_the_service_from_outside(tmp_path):
    """THE FINDING, second part: no foreign, never cleaned-up storage."""
    service = _service(tmp_path)

    await _check(service, "ping")

    assert not hasattr(service._real, "_command_cooldowns"), (
        "The command path still attaches _command_cooldowns to the service - "
        "a dictionary that is never cleaned up and that the service does not know about."
    )


@pytest.mark.asyncio
async def test_the_command_per_minute_limit_applies(tmp_path):
    """THE FINDING, third part: max_commands_per_minute from the panel takes effect."""
    service = _service(tmp_path)
    limit = service._real._get_default_config().max_commands_per_minute
    for i in range(limit):
        service._real.add_user_cooldown(USER, f"probe_{i}", kind="command")

    allowed, _ = await _check(service, "ping")

    assert allowed is False, (
        f"After {limit} commands in the same minute - the quota from "
        "max_commands_per_minute - /ping still goes through."
    )


@pytest.mark.asyncio
async def test_disabled_brakes_nothing_and_records_nothing(tmp_path):
    """Boundary: the operator can switch the protection off."""
    service = _service(tmp_path)

    with patch.object(service._real, "is_enabled", return_value=False):
        allowed, _ = await _check(service, "ping")

    assert allowed is True
    assert service.recorded == []
