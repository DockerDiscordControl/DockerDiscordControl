# -*- coding: utf-8 -*-
# @covers Z8
# @covers Z3
"""Z8/Z3 - one failing event listener must not break the others, or the donation.

``EventManager.emit_event`` (services/infrastructure/event_manager.py) called
each listener inside ``except RuntimeError``. Any other exception type left
the loop: the remaining listeners were skipped, and the exception flew back
into whoever emitted the event.

THE FINDING (2026-09-19, Z8 sweep): ``donation_completed`` is emitted by the
unified donation service AFTER the donation is booked
(services/donation/unified/service.py: execute_sync_donation, then
emit_donation_event). Two caches listen to it. If one of them raised e.g. a
KeyError or TypeError, the donation service caught it in its
``except (ValueError, TypeError, AttributeError, KeyError)`` and returned
``success=False, error_code="DATA_ERROR"`` - for money that WAS in the ledger.
Z3 in reverse: a failure reported that did not happen. A donor who then tries
again is booked twice.
"""

import logging
from types import SimpleNamespace

from services.donation.unified import models
from services.donation.unified import service as service_module
from services.infrastructure.event_manager import EventManager


def test_a_failing_listener_does_not_skip_the_others(caplog):
    manager = EventManager()
    heard = []

    def broken(_event):
        raise KeyError("amount")

    manager.register_listener("donation_completed", broken)
    manager.register_listener("donation_completed", lambda event: heard.append(event))

    with caplog.at_level(logging.DEBUG):
        manager.emit_event("donation_completed", "test", {"amount": 5})   # must not raise

    assert len(heard) == 1, "the second listener was skipped because the first one failed"
    assert any(r.levelno >= logging.ERROR for r in caplog.records), \
        "the failing listener left no error in the log"


class _Mech:
    """Books into ``self.booked`` - the ledger stand-in."""

    def __init__(self):
        self.booked = []
        self.state = SimpleNamespace(level=1, Power=100.0, power_level=100.0)

    def get_state(self):
        return self.state

    def add_donation(self, amount, donor, channel_id=None, idempotency_key=None):  # noqa: ARG002
        self.booked.append((donor, amount))
        self.state = SimpleNamespace(level=1, Power=self.state.Power + amount,
                                     power_level=self.state.Power + amount)
        return self.state


def test_a_booked_donation_is_reported_as_booked_even_if_a_listener_fails(monkeypatch):
    mech = _Mech()
    manager = EventManager()

    def broken_cache(_event):
        raise TypeError("cache listener broke")

    manager.register_listener("donation_completed", broken_cache)
    monkeypatch.setattr(service_module, "get_mech_service", lambda: mech, raising=False)
    monkeypatch.setattr(service_module, "get_event_manager", lambda: manager, raising=False)
    monkeypatch.setattr(service_module, "clear_mech_cache", lambda: None, raising=False)

    result = service_module.UnifiedDonationService().process_donation(
        models.DonationRequest(donor_name="Alex", amount=5, source="web"))

    assert mech.booked == [("Alex", 5)], "premise: the donation was booked"
    assert result.success, (
        f"The donation is in the ledger, but the service reported "
        f"{getattr(result, 'error_code', None)!r} - a donor told 'failed' may pay again."
    )
