# -*- coding: utf-8 -*-
"""
THE FINDING (review C26, section 29 F1): the money is taken and the donor is
told it failed.

`_process_mech_donation` calls `process_web_ui_donation`, which books the
donation through the idempotency-protected path. It then checks
`donation_result.success` - and only afterwards reads
`donation_result.new_state`. If that read raises (an AttributeError, say,
because the state object could not be rebuilt), the method's own
`except (ImportError, AttributeError)` turns it into
`{'success': False, 'error': 'Mech service unavailable: ...'}`, and
`process_donation` answers the web panel with

    DonationResult(success=False, message="Donation processing failed",
                   status_code=500)

The donation is booked. The donor reads "processing failed" and, quite
reasonably, donates again.

Everything up to and including the success check can fail without the money
moving. Everything after it cannot. The two are now separated, and a failure to
READ THE STATE BACK is reported as what it is: the donation went through, the
new state could not be shown.

The second half of the fix is the same rule as review C1: when the state cannot
be read, the response must not fill the donor's screen with 0 power, level 1
and "SCRAP MECH" as though those were measurements.

The counter-checks keep both ends: a donation that genuinely fails is still a
failure, and a normal donation still reports its real numbers.
"""

import sys
import types

import pytest

from services.web.donation_service import DonationRequest, DonationService


class _State:
    Power = 42.5
    total_donated = 300.0
    level = 4
    level_name = "ARMORED MECH"


class _BookedButUnreadable:
    """What the unified service returns when the booking worked but the state
    object cannot be handed back."""
    success = True
    error_message = None

    @property
    def new_state(self):
        raise AttributeError("progress state could not be rebuilt")


class _Booked:
    success = True
    error_message = None
    new_state = _State()


class _Refused:
    success = False
    error_message = "idempotency key already used with a different amount"
    new_state = None


@pytest.fixture
def service():
    return DonationService()


@pytest.fixture(autouse=True)
def no_discord(monkeypatch):
    monkeypatch.setattr(DonationService, "_handle_discord_notification",
                        lambda self, request: False)
    monkeypatch.setattr(DonationService, "_log_donation_action",
                        lambda self, request, discord_success: None)


def _unified(monkeypatch, result):
    module = types.ModuleType("services.donation.unified_donation_service")
    module.process_web_ui_donation = lambda **kwargs: result
    monkeypatch.setitem(sys.modules,
                        "services.donation.unified_donation_service", module)


def _request():
    return DonationRequest(amount=25.0, donor_name="Alice",
                           idempotency_key="key-1", publish_to_discord=False)


def test_a_booked_donation_is_not_reported_as_failed(service, monkeypatch):
    """THE FINDING: the booking succeeded, so the answer is not 'failed'."""
    _unified(monkeypatch, _BookedButUnreadable())

    result = service.process_donation(_request())

    assert result.success is True, result.error
    assert "failed" not in (result.message or "").lower()


def test_the_state_that_could_not_be_read_is_not_invented(service, monkeypatch):
    """The same rule as review C1: not measured is not zero."""
    _unified(monkeypatch, _BookedButUnreadable())

    info = service.process_donation(_request()).donation_info

    assert info['new_Power'] is None
    assert info['total_donations'] is None
    assert info['mech_level'] is None
    assert info['mech_level_name'] is None


def test_a_donation_that_was_refused_is_still_a_failure(service, monkeypatch):
    """COUNTER-CHECK: not every answer becomes a success."""
    _unified(monkeypatch, _Refused())

    result = service.process_donation(_request())

    assert result.success is False
    assert result.status_code == 500


def test_a_normal_donation_still_reports_its_numbers(service, monkeypatch):
    """COUNTER-CHECK: the ordinary path is untouched."""
    _unified(monkeypatch, _Booked())

    info = service.process_donation(_request()).donation_info

    assert info['new_Power'] == 42.5
    assert info['total_donations'] == 300.0
    assert info['mech_level'] == 4
    assert info['mech_level_name'] == "ARMORED MECH"
