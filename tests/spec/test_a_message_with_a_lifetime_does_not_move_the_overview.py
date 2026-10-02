# -*- coding: utf-8 -*-
"""A message that has a lifetime does not move the overview, and keeps its time.

THE OBSERVATION (operator, 2026-10-02): the status overview was posted anew at
10:31, and they asked why the container had been rebuilt. It had not been.
At 10:27 a player joined Valheim and the join notice (meant to stay 30
minutes "so the status panels stay where they are") went under the
overview. Three minutes later the inactivity check took it for a stray bot
message burying the overview, cleared the channel - the notice with it -
and posted the overview again. The two features worked against each other,
and with the message lifetimes every auto-action notice would do the same.

THE OPERATOR'S CHOICE: the overview stays where it is. A message whose
lifetime is still running is not a stray; it stands below the overview
until its time is up. The join notices get their 30 minutes through the
same registry as the other lifetimes, so a restart keeps them too.

HOW THIS TEST CAN FAIL: a live notice counts as burying the overview again,
or a join notice falls back to a timer a restart forgets.

COUNTER-CHECK (2026-10-02): red before the change (buried: True; the join
notice had no record).
"""

import json
from types import SimpleNamespace

import pytest

from tests.spec.test_every_public_message_has_its_lifetime import _Channel, lifetimes  # noqa: F401


DDC = 7000


def _moves(message_id, author_id=DDC):
    """Whether the overview (9001) must move with this one message under it."""
    from cogs.channel_lifecycle import why_the_overview_must_move
    from services.discord.message_lifetimes import known_ids
    message = SimpleNamespace(id=message_id, author=SimpleNamespace(id=author_id, name="ddc"),
                              application_id=None)
    return why_the_overview_must_move([message], {DDC}, {9001}, known_ids()) is not None


@pytest.mark.asyncio
async def test_a_live_notice_does_not_bury_the_overview(lifetimes):  # noqa: F811
    module, clock = lifetimes
    channel = _Channel(111)
    notice = await module.post(channel, "auto_action", "⚡ RESTART Icarus")
    assert _moves(notice.id) is False


@pytest.mark.asyncio
async def test_an_unknown_message_still_does_but_an_expired_notice_not(lifetimes):  # noqa: F811
    """Until 19:51 on 2026-10-02 an expired notice moved the overview too; the
    sweep deletes it, so it waits (test_an_expired_notice_waiting_for_the_sweep_...)."""
    module, clock = lifetimes
    channel = _Channel(111)
    notice = await module.post(channel, "bulk_summary", "summary")
    clock[0] += 301
    assert _moves(notice.id) is False
    assert _moves(4242) is True
    assert _moves(9001) is False


@pytest.mark.asyncio
async def test_a_join_notice_is_written_down_for_30_minutes(lifetimes, tmp_path):  # noqa: F811
    module, clock = lifetimes
    from cogs import player_joins
    channel = _Channel(111)
    bot = SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == 111 else None)
    await player_joins._post(bot, [111], "👋 Anna joined Valheim (1/10)")
    records = json.loads((tmp_path / "message_lifetimes.json").read_text(encoding="utf-8"))
    assert records == {"111:1000": clock[0] + 30 * 60}
    assert "delete_after" not in channel.sent[0][1], "a timer a restart forgets"
