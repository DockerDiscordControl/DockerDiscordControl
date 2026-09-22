# -*- coding: utf-8 -*-
# @covers Z1
"""Z1 - The donation ledger is never lost without a backup.

No operation empties or overwrites the event log without first creating a
restorable copy - not even when the operator triggers the operation
themselves.

Why this matters: according to the operator, the event log is the local
instance's only truth about the real donations. ``reset_donations`` currently
writes ``""`` into it (``services/donation/unified/reset.py:96``) - without a
backup, without asking.

The convention already exists in the project: ``scripts/reset_donations.sh:32-44``
creates a ``backup_<timestamp>/`` with ``events.jsonl`` and ``snapshots/``
before the same deletion and additionally asks for confirmation. Two paths, the
same task - only one of them is careful. These tests demand that care from the
service path too.

The tests touch no real data: ``reset_donations`` accepts ``paths``, so that
everything ends up in a temp directory.

COUNTER-CHECK (carried out 2026-09-16): before the fix in
``services/donation/unified/reset.py`` all three tests failed, each on its own
assertion - not on a stub or an import:

* ``test_reset_leaves_a_restorable_copy`` -> ``assert []``
  (no copy present)
* ``test_reset_aborts_if_the_backup_fails`` ->
  ``assert '{"seq": 1, ...}' in ''`` (log emptied although the backup failed)
* ``test_second_reset_does_not_overwrite_the_first_backup`` -> ``assert set()``
  (even the first backup was missing)

After the fix all three green; the groups donation/integration/mech/web stayed
green unchanged (52 / 5 / 447 / 358).
"""

import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.donation.unified.reset import reset_donations
from services.mech.progress_paths import ProgressPaths

EVENTS = [
    '{"seq": 1, "type": "DonationAdded", "donor": "Anna", "cents": 500}',
    '{"seq": 2, "type": "DonationAdded", "donor": "Bea", "cents": 250}',
    '{"seq": 3, "type": "LevelUp", "level": 2}',
]


@pytest.fixture
def paths(tmp_path):
    """Isolated storage with a filled event log."""
    p = ProgressPaths.from_base_dir(tmp_path / "progress")
    p.event_log.write_text("\n".join(EVENTS) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def services():
    """Stubs for mech_service and event_manager.

    ``DonationResult.from_states`` only reads ``level`` and ``Power`` via
    ``getattr``; ``emit_reset_event`` only calls ``emit_event``. Nothing more is
    needed - and the test should not touch anything more either.
    """
    mech_service = SimpleNamespace(
        get_state=lambda: SimpleNamespace(level=2, Power=7.5)
    )
    return mech_service, MagicMock()


def _restorable_copies(p: ProgressPaths):
    """All files under the storage that preserve the content of the log.

    Deliberately searched broadly: the guarantee demands a restorable copy,
    not a particular file name. So the test does not dictate to the
    implementation how it has to back up.
    """
    hits = []
    for file in p.data_dir.rglob("*"):
        if not file.is_file() or file == p.event_log:
            continue
        try:
            content = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if all(line in content for line in EVENTS):
            hits.append(file)
    return hits


def test_reset_leaves_a_restorable_copy(paths, services):
    """After the reset the log is empty - but the content is still readable somewhere."""
    mech_service, event_manager = services

    result = reset_donations(
        mech_service, event_manager, source="test", paths=paths
    )

    assert result.success is True
    assert paths.event_log.read_text(encoding="utf-8").strip() == "", \
        "The reset should actually empty the log"
    copies = _restorable_copies(paths)
    assert copies, (
        "No restorable state of the donation ledger found - the reset "
        "destroyed the only record of the real donations"
    )


def test_reset_aborts_if_the_backup_fails(paths, services, monkeypatch):
    """If the backup fails, the log stays untouched.

    A backup that only warns on failure and deletes anyway does not fulfil
    Z1: that is exactly when the data would be gone.
    """
    mech_service, event_manager = services

    def _fail(*_a, **_kw):
        raise OSError("no space left on device")

    monkeypatch.setattr(shutil, "copy2", _fail)
    monkeypatch.setattr(shutil, "copytree", _fail)

    result = reset_donations(
        mech_service, event_manager, source="test", paths=paths
    )

    content = paths.event_log.read_text(encoding="utf-8")
    for line in EVENTS:
        assert line in content, (
            "The backup failed, yet the donation ledger was emptied"
        )
    assert result.success is False


def test_second_reset_does_not_overwrite_the_first_backup(paths, services):
    """Two resets yield two restorable states, not one.

    A rolling backup (a single ``.bak``) is not enough here: the second reset
    would overwrite the backup of the first, and an accidental double click
    would destroy everything.
    """
    mech_service, event_manager = services

    reset_donations(mech_service, event_manager, source="test", paths=paths)
    first = set(_restorable_copies(paths))
    assert first, "first backup is already missing"

    # New content, so that the second state differs from the first.
    paths.event_log.write_text(
        "\n".join(EVENTS) + '\n{"seq": 4, "type": "DonationAdded"}\n',
        encoding="utf-8",
    )
    reset_donations(mech_service, event_manager, source="test", paths=paths)
    second = set(_restorable_copies(paths))

    assert first <= second, "The first backup was overwritten"
    assert len(second) > len(first), "The second reset backed up nothing"
