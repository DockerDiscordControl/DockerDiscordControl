# -*- coding: utf-8 -*-
"""The donation history does not depend on a mech state it never uses.

THE FINDING (stage 4 review before v3.1.0, section 17 pass 4 F6): the
history and the statistics fetched the mech state first and failed the
whole call when that failed - although the value was never read (every
number comes from the event log). An unreadable snapshot file (open()
raising PermissionError, which nothing on that path catches) therefore
took the ledger page away, and with it the delete/restore rebuild that
would have rewritten the snapshot.

THE CONTRACT: history and statistics read the event log only; a broken mech
state does not reach them.

HOW THIS TEST CAN FAIL: the history or the statistics fail again when the
mech state cannot be read or reports a failure.

COUNTER-CHECK (2026-09-30): red before the change (success False).
"""

import pytest

from services.donation.donation_management_service import DonationManagementService
from tests.spec.test_one_damaged_ledger_line_does_not_kill_the_history import _event, ledger  # noqa: F401


@pytest.fixture(params=["raises", "fails"])
def broken_mech_state(request, monkeypatch):
    from unittest.mock import MagicMock
    import services.mech.mech_service as mech_service

    service = MagicMock()
    if request.param == "raises":
        service.get_mech_state_service.side_effect = PermissionError("snapshot unreadable")
    else:
        service.get_mech_state_service.return_value = MagicMock(success=False)
    monkeypatch.setattr(mech_service, "get_mech_service", lambda *a, **k: service)


def test_the_history_still_opens(ledger, broken_mech_state):  # noqa: F811
    ledger([_event(1, "Ada", 500)])
    result = DonationManagementService().get_donation_history()
    assert result.success, result.error
    assert [row.get("seq") for row in result.data["donations"]] == [1]


def test_the_statistics_still_open(ledger, broken_mech_state):  # noqa: F811
    ledger([_event(1, "Ada", 500)])
    result = DonationManagementService().get_donation_stats()
    assert result.success, result.error
