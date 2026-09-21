# -*- coding: utf-8 -*-
"""The donation ledger records the channel it was given, not the guild.

THE FINDING (review D10, pass 2, section 17 F2): both donation processors do

    mech_service.add_donation(..., channel_id=request.discord_guild_id, ...)

The request carries BOTH `discord_guild_id` and `discord_channel_id` - the
factory in unified/service.py fills them side by side - and the channel one
is never used. The guild id therefore goes into the ledger under the name
`channel_id`, and from there into the DonationAdded event payload, which is
append-only and replayed on every rebuild.

Nothing reads that field today, which is why nothing broke. That is also why
it is worth correcting now rather than later: the events are kept forever,
so every day it stays wrong is another day of history that cannot be
repaired. The guild is not lost either - `emit_donation_event` records it
separately under its own name.
"""

import asyncio

import pytest

from services.donation.unified.models import DonationRequest
from services.donation.unified.processors import (
    execute_async_donation, execute_sync_donation)

GUILD = "111111111111111111"
CHANNEL = "222222222222222222"


class _Mech:
    """Stands in for the mech service and records what it was handed."""

    def __init__(self):
        self.calls = []

    def add_donation(self, **kwargs):
        self.calls.append(kwargs)
        return "state"

    async def add_donation_async(self, **kwargs):
        self.calls.append(kwargs)
        return "state"


def _request(**kwargs):
    fields = dict(amount=5.0, donor_name="max", source="discord",
                  discord_guild_id=GUILD, discord_channel_id=CHANNEL,
                  idempotency_key="key-1")
    fields.update(kwargs)
    return DonationRequest(**fields)


def test_the_sync_path_hands_over_the_channel():
    mech = _Mech()

    execute_sync_donation(mech, _request())

    assert mech.calls[-1]["channel_id"] == CHANNEL, (
        f"the ledger was given {mech.calls[-1]['channel_id']} - that is the guild"
    )


@pytest.mark.asyncio
async def test_the_async_path_hands_over_the_channel():
    mech = _Mech()

    await execute_async_donation(mech, _request())

    assert mech.calls[-1]["channel_id"] == CHANNEL


def test_without_a_channel_nothing_is_put_in_its_place():
    """A donation from outside a channel has none. The guild must not be
    written there as a stand-in."""
    mech = _Mech()

    execute_sync_donation(mech, _request(discord_channel_id=None))

    assert mech.calls[-1]["channel_id"] is None, (
        f"{mech.calls[-1]['channel_id']} was recorded as the channel"
    )


def test_everything_else_still_travels():
    """Counter-check: the rest of the call must be untouched."""
    mech = _Mech()

    execute_sync_donation(mech, _request())
    call = mech.calls[-1]

    assert call["amount"] == 5.0
    assert call["donor"] == "max"
    assert call["idempotency_key"] == "key-1"
