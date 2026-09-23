# -*- coding: utf-8 -*-
"""One damaged ledger line does not take the whole donation history with it.

THE FINDING (independent review of the donation path, 2026-09-23):
_iter_event_log deliberately tolerates damaged lines - but only lines that
cannot be PARSED. A line that is valid JSON and a dict, yet has no ``seq``,
walks straight into

    donations_map[None] = {...}
    sorted(donations_map.keys(), reverse=True)
    -> TypeError: '<' not supported between 'NoneType' and 'int'

and TypeError is in none of the four except clauses of get_donation_history or
get_donation_stats. So it escapes the service, the donation history page
answers 500, and it keeps answering 500 - including the delete and restore
buttons, which are the only way to repair the ledger from the panel. The
operator is locked out of the page by the very thing they would use it to fix.

The same class: ``payload.get('units', 0) / 100.0`` when ``units`` arrived as
the string "500".

A line the reader cannot make sense of is skipped and said out loud, exactly
as a corrupt line already is. Nothing is repaired silently: the event log is
append-only and is not rewritten here.

HOW THIS TEST CAN FAIL: it puts one seq-less line in a ledger with two good
donations and asks for the history. An error, or a missing good donation,
is red.

COUNTER-CHECK (2026-09-23): red before - ServiceResult.success was False and
the reason was a TypeError about NoneType and int. The last test keeps the
tolerance honest: a line that is skipped is logged, not swallowed.
"""

import json
import logging

import pytest

from services.donation.donation_management_service import DonationManagementService


def _event(seq, donor, units, kind="DonationAdded"):
    event = {"type": kind, "mech_id": "main", "ts": "2026-09-01T10:00:00+00:00",
             "payload": {"donor": donor, "units": units}}
    if seq is not None:
        event["seq"] = seq
    return event


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A real event log on disk, and a mech state the service can read."""
    from unittest.mock import MagicMock
    import services.mech.mech_service as mech_service
    import services.donation.donation_management_service as module

    log = tmp_path / "events.jsonl"
    # Imported by NAME at the top of the module, so that is what to replace.
    monkeypatch.setattr(module, "get_progress_paths",
                        lambda *a, **k: MagicMock(event_log=log))

    state = MagicMock()
    state.success = True
    state.total_donated = 12.0
    state.level = 2
    service = MagicMock()
    service.get_mech_state_service.return_value = state
    monkeypatch.setattr(mech_service, "get_mech_service", lambda *a, **k: service)

    def write(events):
        log.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    return write


def _history():
    return DonationManagementService().get_donation_history()


def test_the_history_still_opens(ledger, caplog):
    """THE FINDING: the page answered 500, including its repair buttons."""
    ledger([_event(1, "Ada", 500),
            _event(None, "the damaged line", 700),
            _event(3, "Bob", 900)])

    with caplog.at_level(logging.DEBUG):
        result = _history()

    assert result.success, f"the donation history could not be read at all: {result.error}"


def test_the_good_donations_are_all_there(ledger):
    """Only the unreadable line is left out, not the ledger around it."""
    ledger([_event(1, "Ada", 500),
            _event(None, "the damaged line", 700),
            _event(3, "Bob", 900)])

    donors = [row["donor_name"] for row in _history().data["donations"]]

    assert "Ada" in donors and "Bob" in donors, donors


def test_an_amount_that_is_not_a_number_does_not_kill_it_either(ledger):
    """The same class of damage, one field along."""
    ledger([_event(1, "Ada", 500), _event(2, "Broken", "700")])

    result = _history()

    assert result.success, f"a string amount took the page down: {result.error}"
    assert "Ada" in [row["donor_name"] for row in result.data["donations"]]


def test_a_skipped_line_is_said_out_loud(ledger, caplog):
    """Counter-check: tolerating damage must not mean hiding it."""
    ledger([_event(1, "Ada", 500), _event(None, "the damaged line", 700)])

    with caplog.at_level(logging.DEBUG):
        _history()

    said = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert said, "a line was dropped from the ledger and nothing said so"


def test_an_undamaged_ledger_is_unchanged(ledger):
    """Counter-check: the everyday case reads exactly as before."""
    ledger([_event(1, "Ada", 500), _event(2, "Bob", 900)])

    result = _history()

    assert result.success
    assert sorted(row["donor_name"] for row in result.data["donations"]) == ["Ada", "Bob"]
    assert result.data["stats"].total_donations == 2


def test_the_statistics_survive_the_same_damage(ledger):
    """The twin reader: it does not sort, but it counts and it divides.

    A seq-less line would merge EVERY such line into one entry there, so the
    donation count and the average would both be wrong - and a string amount
    raises from the division just the same.
    """
    ledger([_event(1, "Ada", 500),
            _event(None, "the damaged line", 700),
            _event(2, "Broken", "900")])

    result = DonationManagementService().get_donation_stats()

    assert result.success, f"the statistics could not be read: {result.error}"
    assert result.data.total_donations == 2, (
        f"the damaged line was counted as a donation: {result.data}")
    assert result.data.total_power == pytest.approx(5.0), result.data
