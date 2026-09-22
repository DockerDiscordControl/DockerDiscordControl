# -*- coding: utf-8 -*-
"""The number of history rows asked for is the number that comes back.

THE FINDING: ``DonationManagementService.get_donation_history(limit=100)``
documents "Maximum number of donations to return" and never looks at the
argument again. The panel (app/blueprints/main_routes.py:971) asks for 100 and
is handed every donation ever booked, each with its deletion rows; on an
install with a long history the page carries the whole ledger.

What the limit may NOT do is change the numbers next to the list: the totals
and the average are about every donation, not about the page. They are
counted before the list is cut.

COUNTER-CHECK (2026-09-23): red before - eight donations came back for a
limit of three. test_the_totals_still_count_everything holds the other side:
cutting the statistics down to the page would be green without it.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.donation.donation_management_service import DonationManagementService


@pytest.fixture
def ledger(tmp_path):
    """The service, reading an event log of eight $50 donations."""
    log = tmp_path / "events.jsonl"
    with open(log, "w", encoding="utf-8") as fh:
        for seq in range(1, 9):
            fh.write(json.dumps({
                "seq": seq,
                "type": "DonationAdded",
                "ts": f"2026-09-23T{seq:02d}:00:00Z",
                "payload": {"donor": f"Donor{seq}", "units": 5000},
            }) + "\n")

    mech_service = Mock()
    mech_service.get_mech_state_service.return_value = SimpleNamespace(
        success=True, total_donated=400.0, level=2)

    with patch("services.donation.donation_management_service.get_progress_paths",
               return_value=SimpleNamespace(event_log=log)), \
         patch("services.mech.mech_service.get_mech_service", return_value=mech_service):
        yield DonationManagementService()


def test_three_asked_for_three_returned(ledger):
    donations = ledger.get_donation_history(limit=3).data["donations"]

    assert len(donations) == 3, f"asked for 3, got {len(donations)}"
    assert [d["donor_name"] for d in donations] == ["Donor8", "Donor7", "Donor6"], (
        "the newest three are the ones a page of three shows")


def test_the_totals_still_count_everything(ledger):
    """Counter-check: the limit is about the list, not about the numbers."""
    stats = ledger.get_donation_history(limit=3).data["stats"]

    assert stats.total_donations == 8
    assert stats.total_power == pytest.approx(400.0)


def test_a_limit_nobody_reaches_changes_nothing(ledger):
    """Counter-check: the everyday case, where the page holds everything."""
    donations = ledger.get_donation_history(limit=100).data["donations"]

    assert len(donations) == 8


def test_no_limit_means_everything(ledger):
    """Counter-check: a caller that wants the whole ledger still gets it."""
    assert len(ledger.get_donation_history(limit=0).data["donations"]) == 8
