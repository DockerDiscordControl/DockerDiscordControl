# -*- coding: utf-8 -*-
"""Two near-simultaneous deletes of one donation do not cancel each other out.

THE FINDING (stage 4 review before v3.1.0, section 17 pass 3 F5 + pass 4
F1): the "is it already deleted?" guard of the panel's delete reads the
ledger WITHOUT the ledger lock, and the delete itself toggles (odd number of
tombstones = deleted) without looking again. Two requests for the same
donation whose reads both came before the first write - a double click, two
tabs; waitress serves them in parallel - both passed the guard, both
appended a tombstone, both answered "Deleted" - and the donation was active
again.

THE CONTRACT: the intent travels into the locked section; a delete of a
donation that is already deleted there is refused.

HOW THIS TEST CAN FAIL: the second delete toggles it back again.

It simulates the race by giving the second request the ledger as it was
before the first delete.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from tests.spec.test_a_new_release_refuels_an_empty_mech import (  # noqa: F401 - fixtures
    mech, module)


def test_the_second_delete_is_refused(module, mech, monkeypatch):
    import services.donation.donation_management_service as dms

    mech.add_donation(10.0, donor="someone", idempotency_key="k1")
    seq = next(e.seq for e in module.read_events() if e.type == "DonationAdded")
    stale = list(dms._iter_event_log(module.runtime.paths.event_log))   # read before either write

    first = dms.DonationManagementService().delete_donation(seq)
    monkeypatch.setattr(dms, "_iter_event_log", lambda path: iter(stale))
    second = dms.DonationManagementService().delete_donation(seq)

    tombstones = [e for e in module.read_events() if e.type == "DonationDeleted"]
    assert first.success
    assert not second.success, "the second delete was answered 'Deleted' and restored the donation"
    assert len(tombstones) == 1, f"{len(tombstones)} tombstones - the donation is active again"
