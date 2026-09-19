# -*- coding: utf-8 -*-
# @covers Z3
"""Z3 - money in the ledger is never reported as a failed donation.

``UnifiedDonationService.process_donation`` books the donation first
(execute_sync_donation) and emits ``donation_completed`` afterwards - both
inside ONE try/except. Anything the emission raises was answered with
``success=False, error_code="DATA_ERROR"`` for money that was already booked;
a donor told "failed" pays again.

THE FINDING (stage 4 review pass 1, section 18 F1, re-checked 2026-09-19):
the listener half of this is fixed (bb11ede - EventManager isolates each
listener), but building and emitting the event itself is still inside the
same try, so a failure there still turns a booked donation into a reported
failure. The remaining half is fixed here, for the sync and the async path.
"""

from types import SimpleNamespace

import pytest

from services.donation.unified import events as events_module
from services.donation.unified import models
from services.donation.unified import service as service_module


class _Mech:
    """Books into ``self.booked`` - the ledger stand-in."""

    def __init__(self):
        self.booked = []
        self.state = SimpleNamespace(level=1, Power=100.0, power_level=100.0)

    def get_state(self):
        return self.state

    def add_donation(self, amount, donor, channel_id=None, idempotency_key=None):  # noqa: ARG002
        self.booked.append((donor, amount))
        return self.state

    async def add_donation_async(self, **kwargs):
        return self.add_donation(kwargs["amount"], kwargs["donor"],
                                 kwargs.get("channel_id"),
                                 idempotency_key=kwargs.get("idempotency_key"))


@pytest.fixture
def broken_emit(monkeypatch):
    mech = _Mech()
    monkeypatch.setattr(service_module, "get_mech_service", lambda: mech, raising=False)
    monkeypatch.setattr(service_module, "get_event_manager", lambda: object(), raising=False)
    monkeypatch.setattr(service_module, "clear_mech_cache", lambda: None, raising=False)

    def explode(*_a, **_k):
        raise TypeError("the event payload could not be built")

    monkeypatch.setattr(events_module, "emit_donation_event", explode)
    return mech


def _request():
    return models.DonationRequest(donor_name="Alex", amount=5, source="web")


def test_the_sync_path_reports_the_booking(broken_emit):
    result = service_module.UnifiedDonationService().process_donation(_request())

    assert broken_emit.booked == [("Alex", 5)], "premise: the donation was booked"
    assert result.success, (
        f"booked, but reported {getattr(result, 'error_code', None)!r} - a donor told "
        f"'failed' may pay again"
    )
    assert not result.event_emitted, "no event went out, so it must not claim one did"


@pytest.mark.asyncio
async def test_the_async_path_reports_the_booking(broken_emit):
    result = await service_module.UnifiedDonationService().process_donation_async(_request())

    assert broken_emit.booked == [("Alex", 5)], "premise: the donation was booked"
    assert result.success, f"booked, but reported {getattr(result, 'error_code', None)!r}"
    assert not result.event_emitted
