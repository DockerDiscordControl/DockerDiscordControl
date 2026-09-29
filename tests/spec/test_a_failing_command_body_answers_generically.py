# -*- coding: utf-8 -*-
"""An error inside a slash command body gets the generic answer and a traceback.

THE FINDING (stage 4 review before v3.1.0, section 33 pass 4 F2): py-cord
wraps any exception raised inside a slash command's callback in
discord.ApplicationCommandInvokeError - an ApplicationCommandError. So it
landed in the handler's "readable message" branch: the user got "Error
during execution: Application Command raised an exception: <Type>: <raw
text>" - the raw text the generic branch exists to hide (a path, a URL with a
query string) - and the log line had no traceback. The generic branch was
practically unreachable for errors from a command body.

THE CONTRACT: an ApplicationCommandInvokeError is answered like any
unexpected error - the generic message, the traceback of the ORIGINAL error
in the log. Other ApplicationCommandErrors keep their readable message.

HOW THIS TEST CAN FAIL: the raw text reaches the user again, or the
traceback is lost; or a readable error loses its message.

COUNTER-CHECK (2026-09-29): the first case red before the change, the
second green before and after.
"""

import logging

import discord
import pytest

from tests.spec.test_a_slash_command_error_reaches_the_user import _bot_with_events, _Ctx


@pytest.mark.asyncio
async def test_a_wrapped_body_error_is_answered_generically(caplog):
    bot = _bot_with_events()
    ctx = _Ctx("status")
    error = discord.ApplicationCommandInvokeError(RuntimeError("/secret/path?token=1"))

    with caplog.at_level(logging.ERROR):
        await bot.on_application_command_error(ctx, error)

    said = " ".join(message for message, _ in ctx.replies)
    assert "/secret/path" not in said, f"the raw error text reached the user: {said}"
    assert ctx.replies, "nobody was answered"
    assert any(r.exc_info and r.exc_info[1] is error.original for r in caplog.records), (
        "the log line carries no traceback of the original error")


@pytest.mark.asyncio
async def test_a_readable_command_error_keeps_its_message():
    bot = _bot_with_events()
    ctx = _Ctx("status")
    await bot.on_application_command_error(ctx, discord.CheckFailure("You may not do that here."))
    assert "You may not do that here." in " ".join(message for message, _ in ctx.replies)
