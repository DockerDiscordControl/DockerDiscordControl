# -*- coding: utf-8 -*-
"""A ledger line with "payload": null does not take the donation history down.

THE FINDING (stage 4 review before v3.1.0, section 17 pass 4 F4): the
history and the statistics read event.get('payload', {}) - which is None
when the key is present as null - and then called .get() on it; a
PowerGiftGranted with "campaign_id": null broke .lower(). One such line (a
hand edit, a restored backup) turned the whole history into "Error
processing donation data", and with it the delete and restore buttons. The
other readers of the same log already treat null as empty.

THE CONTRACT: a null payload or campaign reads as empty; the history and
the statistics still open.

HOW THIS TEST CAN FAIL: one such line kills the page again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from services.donation.donation_management_service import DonationManagementService
from tests.spec.test_one_damaged_ledger_line_does_not_kill_the_history import _event, ledger  # noqa: F401


def _lines():
    gift = {"seq": 3, "type": "PowerGiftGranted", "mech_id": "main",
            "ts": "2026-09-01T10:00:00+00:00", "payload": {"campaign_id": None, "power_units": 100}}
    empty = {"seq": 2, "type": "DonationAdded", "mech_id": "main",
             "ts": "2026-09-01T10:00:00+00:00", "payload": None}
    deleted = {"seq": 4, "type": "DonationDeleted", "mech_id": "main",
               "ts": "2026-09-01T10:00:00+00:00", "payload": None}
    return [_event(1, "Ada", 500), empty, gift, deleted]


def test_the_history_still_opens(ledger):  # noqa: F811
    ledger(_lines())
    result = DonationManagementService().get_donation_history()
    assert result.success, result.error
    assert 1 in [row.get("seq") for row in result.data["donations"]]


def test_the_statistics_still_open(ledger):  # noqa: F811
    ledger(_lines())
    result = DonationManagementService().get_donation_stats()
    assert result.success, result.error
