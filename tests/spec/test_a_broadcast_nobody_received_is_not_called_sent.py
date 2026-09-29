# -*- coding: utf-8 -*-
"""A donation broadcast that reached no channel is not announced as sent.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 3 F3): when every
configured channel had opted out of donation announcements (or there were
none), the donor read "✅ Donation broadcast sent!" over "Sent to 0
channels" - a success header over an announcement nobody received.

THE CONTRACT: with nothing sent, the answer says the donation was recorded
and that no channel posted it; a channel that could not be reached is still
named as a failure.

HOW THIS TEST CAN FAIL: "broadcast sent" over zero channels again.

COUNTER-CHECK (2026-09-29): the first case red before the change; a
broadcast that reached a channel is unchanged.
"""

from cogs.donation_ui import donation_answer


def _answer(sent, failed):
    return donation_answer(share=True, too_soon=False, amount="5", booked=True,
                           broadcast_allowed=True, sent=sent, failed=failed, donor_name="X")


def test_zero_channels_is_not_a_sent_broadcast():
    text = _answer(sent=0, failed=0)
    assert "broadcast sent" not in text.lower(), text
    assert "recorded" in text.lower() and "no channel" in text.lower(), text


def test_an_unreachable_channel_is_still_named():
    assert "Failed to send to 1 channels" in _answer(sent=0, failed=1)


def test_a_broadcast_that_reached_a_channel_is_unchanged():
    assert "Donation broadcast sent" in _answer(sent=2, failed=0)
