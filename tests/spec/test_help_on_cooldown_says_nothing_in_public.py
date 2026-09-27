# -*- coding: utf-8 -*-
"""/help on cooldown tells the caller privately and posts nothing in the channel.

THE FINDING (2026-09-27, while updating the help): when the spam brake held
/help back, the command sent `followup.send(".", delete_after=0.1)` - without
ephemeral, after an ephemeral defer and after the brake had already answered.
So a "." flickered in the channel for everybody. The same dot had been taken
out of /donate and the admin overview's donate button on 2026-09-23
(test_donate_with_donations_off_says_so.py); /help kept it.

HOW THIS TEST CAN FAIL: it runs /help with the brake engaged and records every
message; nothing may be public, and the caller must be told.

COUNTER-CHECK (2026-09-27): red before - one public ".".
"""

import asyncio
from unittest.mock import MagicMock


class _Ctx:
    def __init__(self):
        self.sent = []
        self.author = MagicMock(id=7)
        self.followup = MagicMock()
        self.interaction = MagicMock()
        self.interaction.response.is_done.return_value = True

        async def defer(**kwargs):
            return None

        async def send(*args, **kwargs):
            self.sent.append({"text": args[0] if args else kwargs.get("content"),
                              "ephemeral": kwargs.get("ephemeral", False)})
            return MagicMock()

        async def respond(*args, **kwargs):
            await send(*args, **kwargs)

        self.defer = defer
        self.followup.send = send
        self.respond = respond


def test_help_on_cooldown_posts_nothing_public(monkeypatch):
    from cogs.slash_commands import SlashCommandsMixin

    spam = MagicMock()
    spam.is_enabled.return_value = True
    spam.is_on_cooldown.return_value = True
    spam.get_remaining_cooldown.return_value = 4
    monkeypatch.setattr("cogs.slash_commands.get_spam_protection_service", lambda: spam, raising=False)
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service", lambda: spam)

    ctx = _Ctx()
    cog = MagicMock()
    cog._check_spam_protection = lambda c, name: SlashCommandsMixin._check_spam_protection(cog, c, name)
    asyncio.run(SlashCommandsMixin.help_command.callback(cog, ctx))

    public = [m for m in ctx.sent if not m["ephemeral"]]
    assert public == [], f"posted in the channel: {public}"
    assert ctx.sent, "the caller was not told about the cooldown"
