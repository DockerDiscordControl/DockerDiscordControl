# -*- coding: utf-8 -*-
"""A notice whose lifetime just ran out does not move the overview while it waits for the sweep.

THE OBSERVATION (operator, 2026-10-02, 19:51): a join notice posted at
19:20:33 lived until 19:50:33. The sweep runs in the status loop every 30
seconds and had not reached it yet when the inactivity check ran at 19:51:03;
that check took the expired, not yet deleted notice for "a DDC message
without a running lifetime", cleared the channel and posted the overview
anew. Only the notice should have gone.

THE CONTRACT: a message the lifetime registry knows is a passing DDC notice,
expired or not - the sweep deletes it. Only DDC messages the registry does
not know (and messages of anyone else) move the overview.

HOW THIS TEST CAN FAIL: an expired notice moves the overview again.

COUNTER-CHECK (2026-10-02): red before the change (it moved).
"""

from types import SimpleNamespace

import pytest

from tests.spec.test_every_public_message_has_its_lifetime import _Channel, lifetimes  # noqa: F401
from tests.spec.test_the_overview_moves_down_only_for_others import (  # noqa: F401
    DDC, _message, channel_below)


@pytest.mark.asyncio
async def test_the_loop_waits_for_the_sweep(lifetimes, channel_below):  # noqa: F811
    module, clock = lifetimes
    notice = await module.post(_Channel(111), "player_join", "👋 A player joined Valheim (1/10)")
    clock[0] += 30 * 60 + 30                   # expired half a minute ago, not swept yet
    cog, regenerated = channel_below([_message(notice.id, DDC)])
    await cog.inactivity_check_loop.coro(cog)
    assert regenerated == [], "the overview was posted anew for a notice about to be swept"


@pytest.mark.asyncio
async def test_an_unknown_ddc_message_still_moves_it(lifetimes, channel_below):  # noqa: F811
    module, clock = lifetimes
    cog, regenerated = channel_below([_message(4242, DDC)])
    await cog.inactivity_check_loop.coro(cog)
    assert regenerated == ["status"]
