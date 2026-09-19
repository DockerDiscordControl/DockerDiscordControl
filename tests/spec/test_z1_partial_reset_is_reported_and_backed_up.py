# -*- coding: utf-8 -*-
# @covers Z1
"""Z1 - a reset that breaks off half-way says so, and the backup is there.

THE FINDING THAT WAS NOT ONE (stage 4 review pass 1, section 17 F7,
re-checked 2026-09-19): the reviewer read ``reset_donations`` as leaving the
instance in a half-reset state - event log cleared, counter and snapshot
untouched - if a step after ``_clear_event_log`` fails. That is true, but it
is neither silent nor a loss: the backup (SPEC.md Z1) is written before the
deletion and inside the same lock, and the failure is reported with
``success=False``. Nothing is changed here; the behaviour the re-check
relied on is pinned so it stays that way.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.donation.unified import reset as reset_module


@pytest.fixture
def broken_reset(tmp_path, monkeypatch):
    """A reset whose sequence counter cannot be written; records the order of steps."""
    steps = []

    def _step(name, boom=False):
        def run(*_a, **_k):
            steps.append(name)
            if boom:
                raise OSError("disk full")
        return run

    monkeypatch.setattr(reset_module, "_backup_before_reset", _step("backup"))
    monkeypatch.setattr(reset_module, "_clear_event_log", _step("clear"))
    monkeypatch.setattr(reset_module, "_reset_sequence_counter", _step("counter", boom=True))
    monkeypatch.setattr(reset_module, "_write_fresh_snapshot", _step("snapshot"))
    mech = MagicMock()
    mech.get_state.return_value = SimpleNamespace(level=1, Power=0.0, power_level=0.0)
    return mech, steps


def test_a_reset_that_breaks_off_reports_failure(broken_reset):
    mech, steps = broken_reset

    result = reset_module.reset_donations(mech, MagicMock(), source="test")

    assert not result.success, "a reset that did not finish must not report success"
    assert steps[:2] == ["backup", "clear"], (
        f"the backup must run BEFORE anything is deleted (SPEC.md Z1); order was {steps}"
    )
