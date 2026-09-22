# -*- coding: utf-8 -*-
"""A slash command that fails must say so. All of DDC's commands are slash.

THE FINDING (review E14, found while judging a DDC-exception scan hit in
``docker_control.py``): ``app/bot/events.py`` registers ``on_command_error``.
In py-cord that event belongs to **prefix** commands - the ``!command`` kind.
DDC has none: ``factory.py`` sets ``command_prefix="/"`` but not one
``@commands.command`` exists in the repo. Every DDC command is
``@commands.slash_command``.

Measured in the shipped py-cord (``/opt/runtime/site-packages/discord``):

  * ``commands/core.py:347``  raises ``CommandOnCooldown`` for an application
    command whose bucket is exhausted;
  * ``commands/core.py:483``  dispatches it as ``application_command_error``;
  * ``bot.py:1219``           the default handler prints to ``sys.stderr`` and
    answers the user NOT AT ALL.

So the handler in events.py never runs for anything DDC does, and an
interaction that fails is simply left hanging - the user sees the command
thinking, and then nothing.

**This is why it matters more than an unwired handler usually would.** That
handler carries review C44, whose comment reads: *"A cooldown is the one case
where the command has not answered at all, and returning here left the user
with no message and no log line: they pressed the button and pressed again."*
C44 read the symptom correctly and installed the cure on an event that never
fires. And the cooldowns are real: ``dynamic_cooldown_manager.py:150`` sets
``command._buckets`` on the slash commands at startup, which is exactly what
py-cord checks at core.py:337.

The fix registers the same handler for ``application_command_error`` as well.
``on_command_error`` stays: it costs nothing, and a prefix command may exist
one day.
"""

import discord
import pytest
from discord.ext import commands


class _Command:
    def __init__(self, name="donate"):
        self._name = name

    def __str__(self):
        return self._name


class _Ctx:
    """Enough of an ApplicationContext for an error handler."""

    def __init__(self, command_name="serverstatus"):
        self.command = _Command(command_name)
        self.cog = None
        self.replies = []

    async def respond(self, message, **kwargs):
        self.replies.append((message, kwargs))


def _bot_with_events():
    from app.bot import events

    class _Runtime:
        def __init__(self):
            import logging
            self.logger = logging.getLogger("ddc.test")

    bot = commands.Bot(command_prefix="/", intents=discord.Intents.default())
    events.register_event_handlers(bot, _Runtime())
    return bot


@pytest.mark.asyncio
async def test_the_handler_is_wired_to_the_event_slash_commands_actually_use():
    """py-cord dispatches 'application_command_error' - so something must listen.

    Async only because commands.Bot() needs a running loop on Python 3.14.
    """
    bot = _bot_with_events()

    # @bot.event does setattr on the INSTANCE; py-cord's own default is a
    # method on the class. So "is it in vars(bot)" is the whole question.
    assert "on_application_command_error" in vars(bot), (
        "DDC's commands are all slash commands, and py-cord sends their errors "
        "to 'application_command_error'. Only 'on_command_error' is registered, "
        "which fires for prefix commands - and DDC has none."
    )


@pytest.mark.asyncio
async def test_a_cooldown_on_a_slash_command_is_announced():
    """Review C44's actual symptom, on the path the cooldown actually travels."""
    bot = _bot_with_events()
    handler = vars(bot).get("on_application_command_error")
    assert handler is not None, "no handler at all - see the test above"

    ctx = _Ctx("serverstatus")
    cooldown = commands.CommandOnCooldown(
        commands.Cooldown(1, 30.0), retry_after=12.5, type=commands.BucketType.user)

    await handler(ctx, cooldown)

    assert ctx.replies, (
        "the user hit a cooldown and was told nothing - they press the button "
        "again, which is exactly what review C44 set out to stop"
    )
    assert "12" in ctx.replies[0][0], f"the wait was not named: {ctx.replies[0][0]!r}"


@pytest.mark.asyncio
async def test_an_unexpected_failure_is_announced_too():
    """Not just cooldowns: a DDC exception out of a command must not hang."""
    from services.exceptions import DockerConnectionError

    bot = _bot_with_events()
    handler = vars(bot)["on_application_command_error"]

    ctx = _Ctx("serverstatus")
    await handler(ctx, DockerConnectionError("docker socket is gone"))

    assert ctx.replies, (
        "the command failed and the interaction was left thinking forever"
    )
