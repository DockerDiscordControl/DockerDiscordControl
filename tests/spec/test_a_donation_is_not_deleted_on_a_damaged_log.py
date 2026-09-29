# -*- coding: utf-8 -*-
"""Deleting a donation on an event log with an unreadable line changes nothing - and says so.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F1, verified
2026-09-29). ProgressService.delete_donation appended its DonationDeleted
event and then called rebuild_from_events(), which REFUSES to rebuild from a
log with damaged lines - and returns the old state instead of raising. So
with one unreadable line anywhere in events.jsonl the panel said "Event
deleted successfully", the history (built from the events) showed the entry
deleted, and level, power and total still counted the donation. No write
path healed it: _snapshot_lags does not look at DonationDeleted.

THE CONTRACT: on a damaged log a delete or restore is refused before
anything is written, and the answer says it failed.

HOW THIS TEST CAN FAIL: the tombstone is appended before the damage check
again, or the refusal is reported as success.

It goes through DonationManagementService.delete_donation - the call behind
the panel's delete button - on a real event log.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

from tests.spec.test_a_new_release_refuels_an_empty_mech import (  # noqa: F401 - fixtures
    mech, module)


def _donation_seq(module):
    return next(e.seq for e in module.read_events() if e.type == "DonationAdded")


def test_a_delete_on_a_damaged_log_is_refused_and_writes_nothing(module, mech):
    from services.donation.donation_management_service import DonationManagementService

    mech.add_donation(10.0, donor="someone", idempotency_key="k1")
    seq = _donation_seq(module)
    log = module.runtime.paths.event_log
    with open(log, "a", encoding="utf-8") as f:
        f.write("{broken\n")
    before = log.read_text(encoding="utf-8")

    result = DonationManagementService().delete_donation(seq)

    assert not result.success, "a delete that changed nothing was reported as done"
    assert log.read_text(encoding="utf-8") == before, "a tombstone was written anyway"


def test_a_delete_on_a_sound_log_still_works(module, mech):
    """Counter-check: the ordinary delete goes through."""
    from services.donation.donation_management_service import DonationManagementService

    mech.add_donation(10.0, donor="someone", idempotency_key="k1")

    result = DonationManagementService().delete_donation(_donation_seq(module))

    assert result.success, result.error
    assert any(e.type == "DonationDeleted" for e in module.read_events())
