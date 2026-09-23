# -*- coding: utf-8 -*-
"""There is one donation limit, and the donor gets to read it.

THE FINDING (independent review of the donation path, 2026-09-23): two places
hold a maximum, and they disagree by a factor of a hundred:

    services/web/donation_service.py       MAX_DONATION_AMOUNT   = 999999.0
    services/donation/unified/validation.py MAX_DONATION_DOLLARS =  10000.00

$50,000 therefore passes the panel's own check, reaches the ledger's gate and
is refused there with a sentence written to be read - "Amount exceeds the
maximum allowed value (10,000.00)". The comment beside that limit says in so
many words that it exists "for the donor to read".

They never do. _process_mech_donation wraps the refusal as a generic failure,
the caller answers status_code 500, and the panel shows "Failed to process
donation" with no number in it. The operator is left guessing what the limit
is, and the real reason is only in the server log.

Two ways to say the same thing always drift; this pair had drifted by 100x
before anyone looked. There is one number now, and the panel refuses with it,
as a 400 that can be shown.

HOW THIS TEST CAN FAIL: it submits an amount between the two limits. If the
panel accepts it, or refuses it without saying the limit, the test is red.

COUNTER-CHECK (2026-09-23): red before - the request passed validation, and
the refusal that followed carried 500 and no number. The last tests keep the
ordinary amounts working and the zero/negative refusals unchanged.
"""

import pytest

from services.donation.unified.validation import MAX_DONATION_DOLLARS
from services.web.donation_service import (DonationRequest, DonationResult,
                                           DonationService)


def _check(amount):
    request = DonationRequest(amount=amount, donor_name="Bob")
    return DonationService()._validate_and_sanitize_request(request)


def test_the_two_limits_are_one_limit():
    """THE FINDING: they were 999,999 and 10,000."""
    assert DonationService.MAX_DONATION_AMOUNT == MAX_DONATION_DOLLARS, (
        "the panel and the ledger disagree about the maximum donation again")


def test_an_amount_between_the_two_old_limits_is_refused_here():
    """It used to travel on and come back as a bare 500."""
    result = _check(50_000.0)

    assert result.success is False
    assert result.status_code == 400, (
        f"the refusal came back as {result.status_code}; 500 is not something "
        "the panel shows to the operator")


def test_the_refusal_says_what_the_limit_is():
    """The whole point of refusing early."""
    result = _check(50_000.0)
    text = f"{result.message} {result.error}"

    assert "10,000" in text or "10000" in text, (
        f"the operator is told it failed but not what the limit is: {text!r}")


def test_the_limit_itself_is_still_allowed():
    """Counter-check: the boundary belongs to the donor, not to the refusal."""
    assert _check(MAX_DONATION_DOLLARS).success is True


def test_an_ordinary_donation_still_goes_through():
    """Counter-check: the everyday case."""
    assert _check(25.0).success is True
    assert _check(0.01).success is True


@pytest.mark.parametrize("amount", [0, -5, "ten", None])
def test_nonsense_amounts_are_still_refused(amount):
    """Counter-check: the other refusals are untouched."""
    result = _check(amount)

    assert result.success is False
    assert result.status_code == 400
