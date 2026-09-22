# -*- coding: utf-8 -*-
"""A deleted donation counts nowhere, not in the total and not in the count.

THE FINDING (review D6, pass 2, section 17 F1): `get_donation_history`
computes

    total_power = sum of the donations that are NOT deleted
    total_count = len(donations_map)          # every donation ever recorded
    average     = total_power / total_count

so after an admin deletes one donation the panel shows an inflated count and
an average diluted by exactly the entries that were taken out. The comment on
that line says "Only count actual donations, not deletions" - it says the
opposite of what the line does.

`get_donation_stats`, which reads the same log for the same numbers, filters
both consistently. The two views of one ledger disagreed.
"""

import json

import pytest

from services.donation.donation_management_service import DonationManagementService
from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache, get_progress_paths


def _donation(seq, units, donor):
    return {"seq": seq, "ts": f"2026-09-21T10:0{seq}:00+00:00", "type": "DonationAdded",
            "mech_id": "main",
            "payload": {"donation_id": f"d{seq}", "idempotency_key": f"k{seq}",
                        "units": units, "donor": donor}}


def _deletion(seq, deleted_seq, units, donor):
    return {"seq": seq, "ts": f"2026-09-21T11:0{seq}:00+00:00", "type": "DonationDeleted",
            "mech_id": "main",
            "payload": {"deleted_seq": deleted_seq, "units": units, "donor": donor,
                        "reason": "admin_deletion"}}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A ledger of three $10 donations, one of them deleted."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    log = get_progress_paths().event_log
    log.parent.mkdir(parents=True, exist_ok=True)
    events = [_donation(1, 1000, "a"), _donation(2, 1000, "b"), _donation(3, 1000, "c"),
              _deletion(4, 2, 1000, "b")]
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    try:
        yield DonationManagementService()
    finally:
        reset_progress_runtime()
        clear_progress_paths_cache()


def test_the_deleted_one_is_not_counted(ledger):
    stats = ledger.get_donation_history().data["stats"]

    assert stats.total_donations == 2, (
        f"three donations, one deleted, and the panel counts {stats.total_donations}"
    )


def test_the_average_is_of_what_is_left(ledger):
    stats = ledger.get_donation_history().data["stats"]

    assert stats.average_donation == pytest.approx(10.0), (
        f"two donations of $10 each, and the average is ${stats.average_donation}"
    )


def test_the_two_views_of_the_ledger_agree(ledger):
    """The history page and the statistics read the same log for the same
    numbers. They must not disagree about it."""
    history = ledger.get_donation_history().data["stats"]
    statistics = ledger.get_donation_stats().data

    assert history.total_donations == statistics.total_donations
    assert history.total_power == pytest.approx(statistics.total_power)
    assert history.average_donation == pytest.approx(statistics.average_donation)


def test_the_deletion_is_still_shown(ledger):
    """Counter-check: not counting it must not mean hiding it - the admin
    needs to see that the entry was removed, and by whom."""
    donations = ledger.get_donation_history().data["donations"]

    assert any(entry.get("is_deletion") for entry in donations)
    assert any(entry.get("is_deleted") for entry in donations if not entry.get("is_deletion"))


def test_an_untouched_ledger_is_unaffected(tmp_path, monkeypatch):
    """Counter-check: with nothing deleted, both numbers stay as they were."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "p2"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "c2"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    log = get_progress_paths().event_log
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(json.dumps(e) for e in
                             [_donation(1, 1000, "a"), _donation(2, 3000, "b")]) + "\n",
                   encoding="utf-8")
    try:
        stats = DonationManagementService().get_donation_history().data["stats"]
        assert stats.total_donations == 2
        assert stats.average_donation == pytest.approx(20.0)
    finally:
        reset_progress_runtime()
        clear_progress_paths_cache()
