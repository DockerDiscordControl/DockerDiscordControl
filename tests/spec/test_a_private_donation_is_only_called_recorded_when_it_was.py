# -*- coding: utf-8 -*-
"""A private donation is only called recorded when it was recorded.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 4 F1, verified
2026-09-29). The donation modal's last branch - kept private - answered
"✅ Donation recorded privately! ... Your donation has been recorded and
helps power the Donation Engine" without looking at donation_booked. With
no amount nothing is ever booked, and a failed booking was swallowed
before it: the donor was told of a donation that was not there. The public
branches have asked donation_booked since Z3; the private one never did.

THE CONTRACT: "recorded" only when the booking happened; with no amount
the donor is told nothing was recorded; a failed booking says so.

HOW THIS TEST CAN FAIL: the private branch claims a booking again.

The answer is composed by donation_answer(), called by the modal - tested
here, and the call read from the source.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import ast
from pathlib import Path

DONATION_UI = Path(__file__).resolve().parents[2] / "cogs" / "donation_ui.py"


def _answer(**overrides):
    from cogs.donation_ui import donation_answer
    kwargs = dict(share=False, too_soon=False, amount="", booked=False, broadcast_allowed=False,
                  sent=0, failed=0, donor_name="Max")
    kwargs.update(overrides)
    return donation_answer(**kwargs)


def test_no_amount_is_not_called_recorded():
    text = _answer(amount="")
    assert "recorded privately" not in text and "has been recorded" not in text, text


def test_a_failed_booking_is_not_called_recorded():
    text = _answer(amount="5", booked=False)
    assert "recorded privately" not in text and "has been recorded" not in text, text


def test_a_real_private_booking_still_says_so():
    """Counter-check."""
    assert "recorded privately" in _answer(amount="5", booked=True)


def test_the_modal_answers_through_it():
    tree = ast.parse(DONATION_UI.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "donation_answer"]
    assert calls, "the modal composes its answer somewhere else"
