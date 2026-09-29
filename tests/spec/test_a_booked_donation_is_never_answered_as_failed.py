# -*- coding: utf-8 -*-
"""A donation that is in the ledger is never answered as failed.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F5, verified
2026-09-29). ProgressService.add_donation appends DonationAdded to the
ledger first and updates the snapshot after. If anything in between
raised - persist_snapshot on a full disk, a bad decay value - the donor was
told the donation failed although it was in the ledger (the next booking
heals the snapshot and credits it). A Discord donor who retries gets a new
interaction id, a new idempotency key - and is credited twice: the
"Z3 in reverse" that SPEC Z8 and review A7 already count as a defect.

THE CONTRACT: once the ledger line is written, a failure after it is
reported as "recorded, the display catches up" (error_code
LEDGER_WRITTEN_STATE_PENDING), and the donation service answers success.

HOW THIS TEST CAN FAIL: a failure after the ledger write is a plain
failure again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import pytest

from tests.spec.test_a_new_release_refuels_an_empty_mech import (  # noqa: F401 - fixtures
    mech, module)


def test_a_failure_after_the_ledger_write_says_it_was_recorded(module, mech, monkeypatch):
    from services.exceptions import MechStateError

    mech.add_donation(10.0, donor="first", idempotency_key="k0")
    real, armed = module.persist_snapshot, {"on": True}

    def _disk_full_once(snap):            # the NEXT snapshot write: after the ledger line
        if armed["on"]:
            armed["on"] = False
            raise OSError(28, "No space left on device")
        return real(snap)

    monkeypatch.setattr(module, "persist_snapshot", _disk_full_once)

    with pytest.raises(MechStateError) as raised:
        mech.add_donation(5.0, donor="someone", idempotency_key="k1")

    assert raised.value.error_code == "LEDGER_WRITTEN_STATE_PENDING"
    assert any(e.type == "DonationAdded" and e.payload.get("idempotency_key") == "k1"
               for e in module.read_events()), "premise: the donation is in the ledger"


def test_the_donation_service_answers_success_for_it(monkeypatch):
    from services.donation.unified.models import DonationRequest
    from services.donation.unified.service import UnifiedDonationService
    from services.exceptions import MechStateError

    class _Mech:
        def get_state(self):
            return None

        def add_donation(self, *a, **k):
            raise MechStateError("recorded", error_code="LEDGER_WRITTEN_STATE_PENDING")

    service = UnifiedDonationService()
    service.mech_service = _Mech()
    monkeypatch.setattr("services.donation.unified.service.execute_sync_donation",
                        lambda mech, request: mech.add_donation())

    result = service.process_donation(DonationRequest(donor_name="someone", amount=5.0, source="web"))

    assert result.success, f"a booked donation was answered as failed: {result.error_message}"
