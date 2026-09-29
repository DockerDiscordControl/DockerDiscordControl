# -*- coding: utf-8 -*-
"""The donation window's final answer stays its full time, counted from the answer.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 4 F5): the
"⏳ Processing..." reply was sent with delete_after=15 s, and every final
answer is an edit of that same message. py-cord schedules that deletion when
the message is SENT and edits do not cancel it - so the answer, including
"Your donation was recorded - do NOT submit it again", stayed only for what
was left of those 15 s, and an answer after 15 s hit a deleted message and
the donor got nothing.

THE CONTRACT: "Processing" is sent without a deletion; the deletion is
scheduled once, after the last answer.

HOW THIS TEST CAN FAIL: the first send carries delete_after again, or the
deletion is scheduled before the answer.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from cogs.ddc_ui import NOTICE_STAYS_FOR
from cogs.donation_ui import DonationBroadcastModal


async def test_the_deletion_is_counted_from_the_last_answer():
    order = []
    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.name_input = SimpleNamespace(value="Donor")
    modal.amount_input = SimpleNamespace(value="abc")        # answered: invalid amount
    modal.share_input = SimpleNamespace(value="")
    interaction = MagicMock()
    interaction.user.name = "Donor"

    async def _first(*args, **kwargs):
        order.append(("processing", kwargs.get("delete_after")))

    async def _answer(*args, **kwargs):
        order.append(("answer", None))

    async def _delete(*, delay=None):
        order.append(("delete", delay))
    interaction.response.send_message = _first
    interaction.followup.send = _answer
    interaction.edit_original_response = AsyncMock(side_effect=_answer)
    interaction.delete_original_response = _delete

    await DonationBroadcastModal.callback(modal, interaction)

    assert order[0] == ("processing", None), f"'Processing' was sent to delete itself: {order}"
    assert order[-1] == ("delete", NOTICE_STAYS_FOR), f"no deletion after the answer: {order}"
    assert ("answer", None) in order[:-1]
