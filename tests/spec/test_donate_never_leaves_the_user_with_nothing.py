# -*- coding: utf-8 -*-
"""/donate always answers, and a failure it cannot answer is at least logged.

THE FINDING (independent review of the cog modules, 2026-09-23): /donate is
the only command whose handler answers nothing when it fails:

    except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
        logger.error(f"Error in donate command: {e}", exc_info=True)   # and that is all

and the global error handler skips donation commands ON PURPOSE, on the stated
grounds that "the donation commands answer their own errors, so this handler
must not answer a second time". /donate does not. So both doors are shut:

* an error INSIDE that tuple  -> logged, the user is told nothing;
* an error OUTSIDE it (an AttributeError, a DDCBaseException out of the mech
  service) -> leaves the command -> the global handler -> `return`, which sits
  BEFORE both of its logger.error calls. Nothing answered AND nothing logged.

The everyday way in needs no exotic failure: /donate has no channel permission
check, and /help advertises it as working everywhere. In a channel where the
bot may not embed links, `ctx.defer` succeeds and both followup sends raise
Forbidden. The user watches Discord's "thinking" state, tries again, hits the
5-second cooldown - which DOES answer - and concludes the bot is merely slow.

Two halves, because the premise of the skip has to become true rather than the
skip be removed: /donate answers its own failures now, and the global handler
logs a donation command's error before it steps aside.

HOW THIS TEST CAN FAIL: it makes every send fail and asks what the user was
told, then hands the global handler a donation error and reads the log. Silence
in either place is red.

COUNTER-CHECK (2026-09-23): red before - no answer at all, and no log line from
the handler. The last test keeps the reason the skip exists: the handler must
still not answer a donation command a second time.
"""

import asyncio
import logging
from unittest.mock import MagicMock

import discord
import pytest

from app.bot import events as events_module


class _Ctx:
    """A context whose command can be named, and that records its answers."""

    def __init__(self, command_name="donate"):
        self.command = command_name
        self.answers = []

    async def respond(self, message, ephemeral=False):
        self.answers.append(message)


@pytest.fixture
def on_command_error(monkeypatch):
    """The real handler, registered against a bot that only records."""
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
    return handlers["on_application_command_error"]


def test_a_donation_error_is_logged_even_though_it_is_not_answered(on_command_error, caplog):
    """THE FINDING: the skip sits before both logger.error calls."""
    ctx = _Ctx("donate")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(on_command_error(ctx, discord.ApplicationCommandError("boom")))

    logged = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert logged, (
        "a /donate error left no trace at all - not an answer, not a log line")
    assert any("donate" in message for message in logged), logged


def test_the_handler_still_does_not_answer_a_donation_command(on_command_error, caplog):
    """Counter-check: that is the whole reason the skip exists."""
    ctx = _Ctx("donate")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(on_command_error(ctx, discord.ApplicationCommandError("boom")))

    assert ctx.answers == [], (
        "the global handler answered a donation command that answers itself - "
        "the user gets the same error twice")


def test_an_ordinary_command_is_still_answered(on_command_error, caplog):
    """Counter-check: the handler's own job is untouched."""
    ctx = _Ctx("serverstatus")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(on_command_error(ctx, discord.ApplicationCommandError("boom")))

    assert ctx.answers, "an ordinary command was left without an answer"


def test_a_cooldown_is_still_answered_for_donate(on_command_error, caplog):
    """Counter-check: review C44 put the cooldown branch above the skip."""
    from discord.ext import commands as ext_commands

    ctx = _Ctx("donate")
    cooldown = ext_commands.CommandOnCooldown(
        ext_commands.Cooldown(1, 60.0), retry_after=42.0,
        type=ext_commands.BucketType.user)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(on_command_error(ctx, cooldown))

    assert ctx.answers, "a /donate on cooldown was left with no message again"
