# -*- coding: utf-8 -*-
"""A DDC exception during a donation comes back as a result, not as a crash.

THE FINDING (review D20, pass 2, section 18 F7): `process_donation` and
`process_donation_async` wrap the booking call in three handlers -
`MechServiceError`, `(ValueError, TypeError, AttributeError, KeyError)` and
`(RuntimeError, OSError)` - each of which turns the failure into a
`DonationResult(success=False, ...)` with a reason and a metric.

`DDCBaseException` inherits straight from `Exception`, so every DDC exception
that is not a `MechServiceError` walks past all three: a `ConfigLoadError`
while the level-up prices the next goal, a `ConfigCacheError`, a
`DonationServiceError`. The caller - the Discord modal, the web route - then
gets the exception instead of the structured failure this method exists to
produce, and the donor is shown Discord's own "application did not respond".

This is the shape reviews C6 and C33 removed elsewhere: DDCBaseException does
not inherit from anything the narrow tuples name.
"""

import pytest

from services.donation.unified import service as module
from services.donation.unified.models import DonationRequest
from services.donation.unified.service import UnifiedDonationService
from services.exceptions import (
    ConfigLoadError, DonationServiceError, MechServiceError)


def _request():
    return DonationRequest(amount=5.0, donor_name="max", source="web",
                           idempotency_key="key-1")


@pytest.fixture
def donation_service(monkeypatch):
    """A donation service whose booking call fails on demand."""
    instance = UnifiedDonationService()

    class _Mech:
        # get_state, not get_mech_state: the first version of this stub had the
        # wrong name, so an AttributeError fired BEFORE the booking call and was
        # caught by the data handler - five green tests that never reached the
        # code under test.
        def get_state(self):
            return None

    instance.mech_service = _Mech()

    def _fail_with(failure):
        def _booking(mech_service, request):
            raise failure
        monkeypatch.setattr(module, "execute_sync_donation", _booking)
        return instance
    return _fail_with


@pytest.mark.parametrize("failure", [ConfigLoadError("config is unreadable"),
                                     DonationServiceError("the ledger said no")])
def test_a_ddc_error_comes_back_as_a_failed_result(donation_service, failure):
    result = donation_service(failure).process_donation(_request())

    assert result.success is False, (
        f"{type(failure).__name__} left process_donation instead of being reported"
    )
    assert result.error_message


@pytest.mark.parametrize("failure", [MechServiceError("as before"),
                                     ValueError("as before"),
                                     RuntimeError("as before")])
def test_the_errors_it_already_caught_are_unchanged(donation_service, failure):
    """Counter-check: the three existing handlers must keep their behaviour."""
    result = donation_service(failure).process_donation(_request())

    assert result.success is False
    assert result.error_message
