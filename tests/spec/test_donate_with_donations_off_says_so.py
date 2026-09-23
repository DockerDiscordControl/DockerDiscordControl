# -*- coding: utf-8 -*-
"""/donate with donations switched off tells the caller, privately.

THE FINDING (independent review of the cog modules, 2026-09-23): with a
premium key entered, /donate answers like this:

    await ctx.defer(ephemeral=True)
    ...
    if is_donations_disabled():
        await ctx.followup.send(".", delete_after=0.1)
        return

`ctx.followup.send` WITHOUT ephemeral=True after an ephemeral defer produces a
PUBLIC message - a "." that flickers in the channel for 100 ms - while the
caller's own ephemeral response is never filled. They are left on Discord's
"thinking" state.

The same situation has a correct answer three hundred lines down: the donate
BUTTON shows a "🔐 Premium Features Active" embed, ephemeral, explaining that
donations are off. One state, two answers.

The way in is ordinary: _remove_donation_commands only runs in setup(), so
entering the key while DDC is running leaves /donate registered until the next
restart. Anyone who runs it in that window gets the "." and the spinner.

HOW THIS TEST CAN FAIL: it runs /donate with donations off and reads what was
sent. A public message, or a caller told nothing, is red.

COUNTER-CHECK (2026-09-23): red before - one public ".", nothing ephemeral.
The last test keeps the ordinary case: with donations ON the command still
builds its panel.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


class _Ctx:
    """Records what was sent, and whether it was private."""

    def __init__(self):
        self.sent = []
        self.author = MagicMock()
        self.channel = MagicMock()
        self.guild = MagicMock()
        self.followup = MagicMock()

        async def defer(**kwargs):
            return None

        async def send(*args, **kwargs):
            self.sent.append({
                "content": args[0] if args else kwargs.get("content"),
                "embed": kwargs.get("embed"),
                "ephemeral": kwargs.get("ephemeral", False),
            })
            return MagicMock()

        self.defer = defer
        self.followup.send = send


@pytest.fixture
def donations_off(monkeypatch):
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: True)


def _run_donate(ctx):
    from cogs.slash_commands import SlashCommandsMixin

    cog = MagicMock()
    cog._check_spam_protection = AsyncMock(return_value=True)
    cog.bot = MagicMock()
    asyncio.run(SlashCommandsMixin.donate_command.callback(cog, ctx))


def test_nothing_public_is_sent(donations_off):
    """THE FINDING: a "." flickered in the channel for everyone to see."""
    ctx = _Ctx()

    _run_donate(ctx)

    public = [message for message in ctx.sent if not message["ephemeral"]]
    assert public == [], (
        f"a public message was sent into the channel: {public}")


def test_the_caller_is_told_why(donations_off):
    """And not left on the spinner with a dot."""
    ctx = _Ctx()

    _run_donate(ctx)

    assert ctx.sent, "the caller was left on Discord's 'thinking' state"
    answer = ctx.sent[-1]
    text = f"{answer['content']} {getattr(answer['embed'], 'description', '')}"
    assert answer["ephemeral"] is True
    assert text.strip() not in {".", "None"}, f"the answer was {text!r}"
    assert "premium" in text.lower() or "disabled" in text.lower(), text


def test_with_donations_on_the_panel_is_still_built(monkeypatch):
    """Counter-check: the everyday case must not start refusing."""
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: False)
    ctx = _Ctx()

    _run_donate(ctx)

    assert ctx.sent, "the donation panel was not sent at all"
    assert any(message["embed"] is not None for message in ctx.sent)
