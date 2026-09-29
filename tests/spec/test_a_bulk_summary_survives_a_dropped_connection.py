# -*- coding: utf-8 -*-
"""A bulk action's summary reaches the channel when the private answer's connection drops.

THE FINDING (stage 4 review before v3.1.0, section 01 pass 4 F9):
answer_or_post falls back to posting the summary in the channel only on
NotFound/HTTPException. A connection reset on Linux (aiohttp ClientOSError,
errno 104 - py-cord retries only the macOS/Windows numbers) or a
ServerDisconnectedError escaped it and the confirm callbacks, so the summary
of a bulk action that had already run was lost and the presser saw nothing.

THE CONTRACT: every failure to reach the presser falls through to the
channel post.

HOW THIS TEST CAN FAIL: a transport error escapes again.

COUNTER-CHECK (2026-09-29): both cases red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import discord
import pytest

from cogs.admin_overview import answer_or_post


@pytest.mark.parametrize("error", [aiohttp.ClientOSError(104, "Connection reset by peer"),
                                   aiohttp.ServerDisconnectedError()])
async def test_the_summary_goes_to_the_channel(error):
    channel = SimpleNamespace(send=AsyncMock())
    cog = SimpleNamespace(bot=SimpleNamespace(get_channel=lambda cid: channel))
    interaction = SimpleNamespace(followup=SimpleNamespace(send=AsyncMock(side_effect=error)))
    embed = discord.Embed(description="Successfully restarted: **3** containers")

    await answer_or_post(interaction, cog, 123, embed)

    channel.send.assert_awaited_once_with(embed=embed)
