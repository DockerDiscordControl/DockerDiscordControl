# -*- coding: utf-8 -*-
"""A donation reset that fails after emptying the ledger puts the ledger back.

THE FINDING (stage 4 review before v3.1.0, section 17 pass 3 F4 + pass 4
F2): the reset takes a backup, empties the event log, then writes the
sequence counter and a fresh snapshot. When one of those last two writes
failed (a full disk, a read-only data directory), the ledger was already
empty while the old snapshot - level, power - stayed live, and the report
said only "File I/O error". The backup existed (Z1 held), but restoring it
was left to the operator. An error of another type escaped the reset
entirely.

THE CONTRACT: any failure after the backup restores the event log, the
counter and the snapshots from it; the reset answers a failure, never
raises.

HOW THIS TEST CAN FAIL: the log stays empty after a failed reset, or the
error escapes.

COUNTER-CHECK (2026-09-30): both cases red before the change.
"""

import pytest

import services.donation.unified.reset as reset_mod
from tests.spec.test_z1_donation_ledger_backup import EVENTS, paths, services  # noqa: F401


@pytest.mark.parametrize("error", [OSError("disk full"), ValueError("goal helper")])
def test_the_ledger_is_back_after_a_failed_reset(paths, services, monkeypatch, error):  # noqa: F811
    before = paths.event_log.read_text(encoding="utf-8")

    def _broken(p):
        raise error
    monkeypatch.setattr(reset_mod, "_write_fresh_snapshot", _broken)

    result = reset_mod.reset_donations(*services, source="test", paths=paths)

    assert not result.success
    assert paths.event_log.read_text(encoding="utf-8") == before, "the ledger stayed empty"
