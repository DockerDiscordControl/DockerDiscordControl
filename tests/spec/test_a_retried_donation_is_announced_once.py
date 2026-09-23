# -*- coding: utf-8 -*-
"""A donation the ledger already holds is not announced a second time.

THE FINDING (independent review of the donation path, 2026-09-23): the panel's
donation form keeps its `__ddcDonationToken` until a booking is CONFIRMED and
reuses it on a retry. That is right for the ledger: add_donation sees the same
idempotency key and books nothing (SPEC.md Z4).

What it does not cover is everything after the booking. add_donation answers a
dedupe hit with an ordinary success - the mech's UI state, exactly as for a
fresh donation - and process_donation then writes a SECOND
donation_notification file and a SECOND MANUAL_DONATION line.

    donor submits $50      -> booked, announcement written
    the answer is lost, or slower than the 30 s AbortController
    the page says "Request timeout... try again" and re-enables the button
    donor clicks again     -> ledger dedupes, NOTHING is booked
                           -> a second announcement is written anyway

In Discord every channel then reads "Bob donated $50.00 to DDC - thank you"
twice for one payment, and the audit log has two entries for one $50 row in the
history. Nothing in the panel hints at it.

HOW THIS TEST CAN FAIL: it books a donation, then sends the same request again
with the same key, and counts the announcements. Two means red.

COUNTER-CHECK (2026-09-23): red before - two announcement files for one
booking. The other tests keep the point of announcing at all: a first donation
is announced, and a second donation with a DIFFERENT key is announced too.
"""

import pytest

from services.web.donation_service import DonationRequest, DonationService


class _Recorder(DonationService):
    """The real service, with the two outward steps recorded instead of done."""

    def __init__(self, already_booked):
        super().__init__()
        self.announced = []
        self.logged = []
        self._already = already_booked

    def _process_mech_donation(self, request):
        # What add_donation answers for BOTH cases: an ordinary success.
        return {"success": True, "mech_state": None}

    def _handle_discord_notification(self, request):
        self.announced.append(request.donor_name)
        return True

    def _log_donation_action(self, request, discord_success):
        self.logged.append((request.donor_name, discord_success))

    def _validate_and_sanitize_request(self, request):
        from services.web.donation_service import DonationResult

        return DonationResult(success=True)

    def _build_donation_response(self, request, mech_result, discord_success):
        from services.web.donation_service import DonationResult

        return DonationResult(success=True, message="ok")


def _request(key):
    return DonationRequest(donor_name="Bob", amount=50.0, publish_to_discord=True,
                           idempotency_key=key)


@pytest.fixture
def ledger(monkeypatch):
    """A ledger that answers whether a key is already in it."""
    seen = set()
    import services.web.donation_service as module

    monkeypatch.setattr(module, "donation_is_already_recorded",
                        lambda key: key in seen, raising=False)
    return seen


def test_the_second_submission_is_not_announced_again(ledger):
    """THE FINDING: one payment, two thank-yous in every channel."""
    service = _Recorder(already_booked=False)

    service.process_donation(_request("token-1"))
    ledger.add("token-1")              # the first submission booked it
    service.process_donation(_request("token-1"))

    assert service.announced == ["Bob"], (
        f"the same donation was announced {len(service.announced)} times")


def test_the_second_submission_is_not_logged_again(ledger):
    """The audit log had two entries for one row in the history."""
    service = _Recorder(already_booked=False)

    service.process_donation(_request("token-1"))
    ledger.add("token-1")
    service.process_donation(_request("token-1"))

    assert len(service.logged) == 1, f"the action log got {len(service.logged)} entries"


def test_a_first_donation_is_still_announced(ledger):
    """Counter-check: announcing is the point of the whole path."""
    service = _Recorder(already_booked=False)

    service.process_donation(_request("token-1"))

    assert service.announced == ["Bob"]


def test_a_different_donation_is_announced_too(ledger):
    """Counter-check: two real donations are two announcements."""
    service = _Recorder(already_booked=False)

    service.process_donation(_request("token-1"))
    ledger.add("token-1")
    service.process_donation(_request("token-2"))

    assert service.announced == ["Bob", "Bob"]
