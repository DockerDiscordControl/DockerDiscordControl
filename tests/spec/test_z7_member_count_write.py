# -*- coding: utf-8 -*-
# @covers Z7
"""Z7, place 3 of 5 - the member count snapshot.

``MemberCountService.persist_member_count_snapshot``
(``services/member_count/service.py:153``) writes the file with a plain
``Path.write_text`` (:174). An abort in the middle leaves it truncated.

Why this is more than a number: the member count determines the **prices** in
the donation system - ``requirement_for_level_and_bin(..., member_count=...)``
derives from it what the next level costs. A half-written file is either
unreadable (then the calculation falls back to a default value) or contains a
wrong number. Both silently shift how much money a level costs - nobody sees
it, and the display looks normal.

Boundary to the existing test: ``tests/test_member_count_service.py:121``
checks that the four fields land correctly in the file. That is a real
contract and stays untouched - it just says nothing about the crash case.
This adds to it, it does not duplicate it.

IMPORTANT about the interception: this place writes via ``Path.write_text``,
not via ``open(..., "w")``. The helper proven in the two previous Z7 passes
intercepts ``builtins.open`` and ``os.fdopen`` - neither applies here. Had I
adopted it unchecked, the guard would have fired and the test would have
failed for the wrong reason. ``Path.write_text`` is therefore intercepted as
well.

COUNTER-CHECK (performed 2026-09-16) - this test was worthless TWICE before it
proved anything. Both times it was green:

*Version 1:* ``_write_text`` raised immediately, without touching the file.
Then nothing is ever truncated, the old content survives, and the guarantee
below is fulfilled - by the dummy, not by the code. The interception point
was BEFORE the damage.

*Version 2 (same run):* ``test_no_temp_leftovers_after_success`` counted
"everything except the target file" as leftover and was therefore red for the
wrong reason - ``ProgressPaths.from_base_dir`` also creates ``events.jsonl``
and ``last_seq.txt`` in the same storage. The assumption from the previous Z7
pass (target file lies alone) had been adopted unchecked.

*Version 3:* the damage is reproduced instead of prevented - the file is
opened with "w" (and thereby truncated), THEN the error comes. Only now red::

    assert ''   # The snapshot is empty

After the fix to ``atomic_write_json``: 3 green. The existing
``tests/test_member_count_service.py`` stayed green unchanged (4),
``tests/unit/extended`` as well (731).

EVIDENCE OF EFFECT by mutation: with an ``atomic_write_text`` that swallows
all errors, this test turns red; restored, green again. A green test does not
prove that it bites - only the mutation does.
"""

import json
import os
from pathlib import Path

import pytest

import services.member_count.service as mc_module
from services.member_count.service import MemberCountService
from services.mech.progress_paths import ProgressPaths

ORIGINAL = {
    "count": 42,
    "last_updated": "2026-01-01T00:00:00+00:00",
    "source": "status_channels",
    "description": "State before the crash",
}


class _WriteErrorOnWrite:
    """Makes every write fail - on all three paths.

    ``builtins.open`` and ``os.fdopen`` cover the previous places,
    ``Path.write_text`` this one. An atomic implementation would write via
    ``os.fdopen``; without the third path the guard below would fire instead
    of checking the guarantee.
    """

    def __init__(self, monkeypatch):
        self.hit = False
        real_open, real_fdopen = open, os.fdopen
        real_write_text = Path.write_text

        def _raises(*_a, **_k):
            raise OSError("no space left on device")

        def _prepare(fh):
            self.hit = True
            fh.write = _raises
            return fh

        def _open(file, mode="r", *a, **kw):
            fh = real_open(file, mode, *a, **kw)
            return _prepare(fh) if ("w" in mode or "a" in mode) else fh

        def _fdopen(fd, mode="r", *a, **kw):
            fh = real_fdopen(fd, mode, *a, **kw)
            return _prepare(fh) if ("w" in mode or "a" in mode) else fh

        def _write_text(path, *a, **kw):
            # REPRODUCE the damage, do not prevent it. The first version raised
            # immediately and never touched the file - then nothing is ever
            # truncated, the old content survives, and the guarantee below is
            # fulfilled: by the dummy, not by the code. The test was green
            # without proving anything.
            #
            # The real ``Path.write_text`` opens with "w" and thereby truncates
            # on open. Exactly that is done here before the write error comes.
            self.hit = True
            with real_open(path, "w", encoding="utf-8"):
                pass
            raise OSError("no space left on device")

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)
        monkeypatch.setattr(Path, "write_text", _write_text)
        self._real_write_text = real_write_text


@pytest.fixture
def snapshot_service(tmp_path, monkeypatch):
    """Service with an already populated snapshot."""
    paths = ProgressPaths.from_base_dir(tmp_path, create_missing=True)
    monkeypatch.setattr(mc_module, "get_progress_paths", lambda: paths)
    paths.member_count_file.write_text(json.dumps(ORIGINAL, indent=2), encoding="utf-8")
    return MemberCountService(), paths.member_count_file


def test_aborted_write_leaves_the_snapshot_intact(snapshot_service, monkeypatch):
    """If writing fails, the old state is still fully there."""
    service, file = snapshot_service
    failure = _WriteErrorOnWrite(monkeypatch)

    with pytest.raises(OSError):
        service.persist_member_count_snapshot(
            99, source="status_channels", description="New state"
        )

    assert failure.hit, (
        "The write error was not triggered at all - then this test checks "
        "nothing. Probably the implementation writes through a fourth path."
    )
    content = file.read_text(encoding="utf-8")
    assert content.strip(), (
        "The snapshot is empty - the member count determines the prices "
        "in the donation system, and an unreadable file shifts them silently"
    )
    assert json.loads(content) == ORIGINAL, (
        f"The snapshot was damaged: {content!r}"
    )


def test_successful_write_replaces_the_state(snapshot_service):
    """The opposite direction: without an error the replacement is correct.

    Without this case one could tighten the method to "never writes" and the
    test above would stay green.
    """
    service, file = snapshot_service

    service.persist_member_count_snapshot(
        99, source="status_channels", description="New state", note="Probe"
    )

    afterwards = json.loads(file.read_text(encoding="utf-8"))
    assert afterwards["count"] == 99
    assert afterwards["note"] == "Probe"


def test_no_temp_leftovers_after_success(snapshot_service):
    """An atomic implementation cleans up its temp file.

    Unlike in the two previous Z7 passes, the target file here does NOT lie
    alone in its directory: ``ProgressPaths.from_base_dir`` also creates
    ``events.jsonl`` and ``last_seq.txt`` in the same storage. The first
    version of this test counted "everything except the target file" as
    leftover and was therefore red for the wrong reason - the assumption from
    the previous case had been adopted unchecked.

    What is checked now is the inventory before versus after: whatever is
    added and stays is a leftover.
    """
    service, file = snapshot_service
    before = {p.name for p in file.parent.iterdir() if p.is_file()}

    service.persist_member_count_snapshot(
        99, source="status_channels", description="New state"
    )

    after = {p.name for p in file.parent.iterdir() if p.is_file()}
    leftovers = sorted(after - before)
    assert leftovers == [], f"Temp leftovers remained: {leftovers}"
