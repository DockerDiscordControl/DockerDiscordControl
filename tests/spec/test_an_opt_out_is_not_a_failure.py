# -*- coding: utf-8 -*-
"""A channel that wants no donation notices is not a failed delivery.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 06 F4, re-checked 2026-09-20):
in the broadcast flow, a channel with ``donation_broadcasts=False`` - an
opt-out the operator sets in the web panel - falls into the same ``else`` as
a channel that could not be found or could not be written to, and raises
``failed_count``. The admin is then told "⚠️ Failed to send to 2 channels"
although nothing failed: those two channels asked not to be told. Someone
reading that goes looking for a fault that is not there.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DonationBroadcastModal

WANTS = "111111111111111111"
OPTED_OUT = "222222222222222222"
GONE = "333333333333333333"


def _modal():
    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.donation_manager_available = True
    modal.bot = MagicMock()
    modal.name_input = SimpleNamespace(value="Donor")
    modal.amount_input = SimpleNamespace(value="5.00")
    modal.share_input = SimpleNamespace(value="X")  # share publicly
    return modal


def _interaction(known_channels):
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    processing = MagicMock()
    processing.delete = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=processing)
    interaction.edit_original_response = AsyncMock()
    interaction.user = SimpleNamespace(name="Admin", id=4711)
    interaction.guild = SimpleNamespace(id=1, name="guild")
    interaction.channel = SimpleNamespace(id=2)
    interaction.id = 999

    def get_channel(channel_id):
        channel = known_channels.get(str(channel_id))
        return channel

    interaction.client.get_channel = get_channel
    return interaction


def _channel():
    channel = MagicMock()
    channel.send = AsyncMock()
    return channel


async def _broadcast(channels_config, known_channels):
    # The fields the confirmation reads - including the Power alias pinned by B26.
    state = SimpleNamespace(level=2, Power=5.0, power_level=5.0, power_current=5.0,
                            power_max=10.0, evo_percent=50, total_donated=5.0,
                            total_donations=5.0, name="Scout", threshold=25.0)
    result = SimpleNamespace(success=True, new_state=state, error_message=None,
                             old_level=2, new_level=2, level_changed=False)
    interaction = _interaction(known_channels)
    with patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(return_value=result)), \
         patch("cogs.docker_control.load_config",
               return_value={"channel_permissions": channels_config}):
        await _modal().callback(interaction)
    answers = [call.kwargs.get("content") or (call.args[0] if call.args else "")
               for call in interaction.edit_original_response.await_args_list]
    return " ".join(str(answer) for answer in answers)


@pytest.mark.asyncio
async def test_a_channel_that_wants_the_notice_gets_it():
    """Premise: the normal case reports what it sent."""
    answer = await _broadcast({WANTS: {"donation_broadcasts": True}},
                              {WANTS: _channel()})

    assert "1" in answer and "Failed" not in answer, answer


@pytest.mark.asyncio
async def test_an_opt_out_is_not_reported_as_a_failure():
    answer = await _broadcast(
        {WANTS: {"donation_broadcasts": True}, OPTED_OUT: {"donation_broadcasts": False}},
        {WANTS: _channel(), OPTED_OUT: _channel()})

    assert "Failed" not in answer, (
        f"a channel that opted out was counted as a failed delivery: {answer}"
    )


@pytest.mark.asyncio
async def test_a_channel_that_is_gone_is_still_a_failure():
    """Counter-check: a real failure must still be named."""
    answer = await _broadcast(
        {WANTS: {"donation_broadcasts": True}, GONE: {"donation_broadcasts": True}},
        {WANTS: _channel()})

    assert "Failed" in answer, f"a channel the bot cannot see is a failure: {answer}"
