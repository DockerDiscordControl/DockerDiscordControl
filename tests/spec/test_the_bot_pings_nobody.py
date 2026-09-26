# -*- coding: utf-8 -*-
"""The bot pings nobody - whatever text it re-posts.

THE FINDING (audit 2026-09-26). Nothing in DDC set allowed_mentions, and
Discord's default pings everyone, every role and every user a message names.
The channel translation copies video/social URLs out of other people's
messages into the body of its own post, taking everything up to the next
space: "https://x.com/@everyone" or a role mention glued to a youtu.be link
pinged with the BOT's permissions - including in a channel where the author
may not ping at all. Any other path that echoes user text (task names, info
texts, donor names) had the same exposure.

DDC mentions nobody on purpose (checked: no role, user or everyone mention is
built anywhere in cogs/, services/ or app/bot/), so the bot's default is none.

COUNTER-CHECK (2026-09-26): red before - the bot's allowed_mentions was None,
which Discord reads as "ping what is named".
"""

import logging
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_the_bot_allows_no_mentions():
    from app.bot.factory import create_bot

    bot = create_bot(SimpleNamespace(logger=logging.getLogger("test")))
    mentions = bot.allowed_mentions

    assert mentions is not None, "Discord's default pings everything a message names"
    assert mentions.everyone is False
    assert mentions.roles is False or mentions.roles == []
    assert mentions.users is False or mentions.users == []
