# -*- coding: utf-8 -*-
"""A donation modal whose amount notice cannot be sent still answers the donor.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 3 F2): the modal's
error handler reads processing_msg, which was first bound further down than
the try begins. When the notice about an invalid amount could not be sent
(an HTTPException on the followup), the handler raised UnboundLocalError: the
fallback answer was never attempted and the log showed a stack trace for the
wrong error.

THE CONTRACT: the handler runs to its answer, whatever failed first.

HOW THIS TEST CAN FAIL: UnboundLocalError escapes again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.donation_ui import DonationBroadcastModal


async def test_the_donor_still_gets_the_error_answer():
    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.name_input = SimpleNamespace(value="Donor")
    modal.amount_input = SimpleNamespace(value="abc")
    modal.share_input = SimpleNamespace(value="")
    interaction = MagicMock()
    interaction.user.name = "Donor"
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock(side_effect=discord.HTTPException(
        MagicMock(status=500, reason="Server Error"), "x"))
    interaction.edit_original_response = AsyncMock()

    await DonationBroadcastModal.callback(modal, interaction)

    said = " ".join(str(c.kwargs.get("content")) for c in interaction.edit_original_response.await_args_list)
    assert "Error sending donation broadcast" in said, said
