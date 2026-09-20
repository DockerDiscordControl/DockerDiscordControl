# -*- coding: utf-8 -*-
"""
THE FINDING (review C44, section 33 F2): the two donation commands are the only
ones whose cooldown is never explained to the user.

`on_command_error` starts with

    if hasattr(ctx, "command") and str(ctx.command) in ["donate", "donatebroadcast"]:
        return

before it has looked at the error at all. For every other command a cooldown
produces "This command is on cooldown. Please try again in ...". For these two
it produces nothing: no message, no log line. The user presses the button, sees
no reaction, and presses again.

The exclusion itself has a reason - the donate flow answers the interaction
itself, so a second response would fail - but that reason only covers the
branches that RESPOND with an error. The cooldown branch is the one place where
the command has not answered at all.

The counter-checks keep the exclusion doing its job for everything else, and
keep the other commands unchanged.
"""

import discord
import pytest
from discord.ext import commands

from app.bot import events as events_module


class _Ctx:
    def __init__(self, command_name):
        self.command = command_name
        self.responses = []

    async def respond(self, message, ephemeral=False):
        self.responses.append(message)


@pytest.fixture
def on_command_error(monkeypatch):
    """Register the handlers against a bot that just records them."""
    handlers = {}

    class _Bot:
        @staticmethod
        def event(func):
            handlers[func.__name__] = func
            return func

    class _Runtime:
        import logging as _logging
        logger = _logging.getLogger("ddc.spec.events")

    monkeypatch.setattr(events_module, "StartupManager",
                        lambda bot, runtime: object())
    events_module.register_event_handlers(_Bot(), _Runtime())
    return handlers["on_command_error"]


def _cooldown():
    return commands.CommandOnCooldown(
        commands.Cooldown(1, 60.0), retry_after=42.0,
        type=commands.BucketType.user)


@pytest.mark.parametrize("command_name", ["donate", "donatebroadcast"])
async def test_a_donation_cooldown_is_explained(on_command_error, command_name):
    """THE FINDING: silence is the one answer a cooldown must not give."""
    ctx = _Ctx(command_name)

    await on_command_error(ctx, _cooldown())

    assert ctx.responses, "the user was told nothing at all"
    assert "cooldown" in ctx.responses[0].lower()


async def test_another_command_still_gets_its_cooldown_message(on_command_error):
    """COUNTER-CHECK: nothing changes for every other command."""
    ctx = _Ctx("control")

    await on_command_error(ctx, _cooldown())

    assert ctx.responses and "cooldown" in ctx.responses[0].lower()


@pytest.mark.parametrize("command_name", ["donate", "donatebroadcast"])
async def test_other_donation_errors_are_still_left_to_the_command(
        on_command_error, command_name):
    """COUNTER-CHECK: the exclusion keeps its purpose - the donate flow answers
    its own errors, so this handler must not answer a second time."""
    ctx = _Ctx(command_name)

    await on_command_error(ctx, discord.ApplicationCommandError("something else"))

    assert ctx.responses == []


async def test_another_command_still_gets_its_error_message(on_command_error):
    """COUNTER-CHECK: the exclusion must stay an exclusion for the donation
    commands only - every other command still gets its error explained."""
    ctx = _Ctx("control")

    await on_command_error(ctx, discord.ApplicationCommandError("boom"))

    assert ctx.responses, "a normal command's error was swallowed"
