# -*- coding: utf-8 -*-
# @covers Z8
"""Z8 - a failed donation does not leave "Processing..." standing in the channel.

THE FINDING (stage 4 review, stage B, section 06 F2, re-checked 2026-09-20):
the broadcast modal posts a PUBLIC "💰 Processing $X donation..." message
(the comment there says it is kept visible "so we can delete it later") and
then books the donation. If the booking answers success=False, the code
logs, tells the admin privately that it failed, and RETURNS - the public
message is deleted only on the success path or in the outer except, neither
of which that early return reaches. Everyone in the channel keeps reading
"Processing a $X donation" for a donation that never happened.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DonationBroadcastModal


def _interaction():
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    processing_message = MagicMock()
    processing_message.delete = AsyncMock()
    inter.followup.send = AsyncMock(return_value=processing_message)
    inter.edit_original_response = AsyncMock()
    inter.user.name = "Donor"
    inter.user.id = 4711
    inter.guild.id = 1
    inter.channel.id = 2
    inter.id = 999
    inter.client.get_channel = lambda _id: None
    return inter, processing_message


def _modal():
    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.donation_manager_available = True
    modal.bot = MagicMock()
    modal.name_input = SimpleNamespace(value="Donor")
    modal.amount_input = SimpleNamespace(value="5.00")
    modal.share_input = SimpleNamespace(value="X")
    return modal


@pytest.mark.asyncio
async def test_a_failed_booking_removes_the_public_message():
    inter, processing_message = _interaction()
    failed = SimpleNamespace(success=False, error_message="ledger not writable",
                             new_state=None)

    with patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(return_value=failed)):
        await _modal().callback(inter)

    processing_message.delete.assert_awaited(), (
        "the donation failed and the public 'Processing...' message stays in the channel"
    )
