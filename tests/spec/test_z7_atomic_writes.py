# -*- coding: utf-8 -*-
# @covers Z7
"""Z7 - A configuration survives every write.

Every write to configuration or state files is atomic (temp file + rename).
A crash in the middle of writing leaves the old file intact.

This file starts with ``next_seq()`` (``services/mech/progress_service.py:256``).
Of the four non-atomic spots in the inventory, this is the most serious: it
reads, increments and writes the same counter - and this counter numbers the
donation ledger, whose integrity Z1 guarantees. An abort there does not merely
leave a broken file behind, it can hand out a sequence number twice.

The remaining three spots (``_deactivate_container``,
``persist_member_count_snapshot``, ``save_server_order``) follow as separate
passes - in descending order of damage, not of convenience.

On the lock, to draw the boundary: ``next_seq()`` demonstrably runs under ``LOCK``
(``progress_service.py:1027`` encloses :1044, :1066, :1071). The lock protects
against interleaving, NOT against crashes - even under the lock an abort in the
middle of writing leaves a truncated file. This test covers the crash, not the
concurrency.

COUNTER-CHECK (carried out 2026-09-16):

Before the fix, ``test_interrupted_write...`` failed on its own assertion - and
the result was worse than expected::

    assert '' == '5'

The file was not half written but **empty**: ``open(..., "w")`` truncates it
already on opening, before a single byte is written. ``next_seq()`` would then
have read ``int("" or 0)`` and started again at 1 - in the middle of an event
log in which the numbers 1 to 5 are already taken.

The guard ``failure.hit`` did NOT fire and ``pytest.raises(OSError)`` held: so
the error really arrived and was not swallowed. That was the purpose of these
two safeguards - they separate "assertion broken" from "test did not take hold
at all".

After the fix 18 green; the groups mech/donation/integration/extended stayed
green unchanged (447 / 52 / 5 / 731).

Honestly, on the significance of the three tests: ``test_no_temp_leftovers_after_success``
was trivially green before, because the old version did not create a temp file
at all. It only checks something since the fix, and fails if the cleanup is
missing. ``test_successful_write_still_increments`` was green before and after -
it only exists so that the lock cannot be tightened to "never writes".
"""

import os

import pytest

import services.mech.progress_service as ps


class _WriteFailsOnWrite:
    """Lets files be opened, but makes every write fail.

    Intercepts ``builtins.open`` AND ``os.fdopen``. Both are necessary, and
    deliberately implementation-independent: today's version writes via
    ``open(...)``, an atomic version via ``mkstemp`` + ``os.fdopen``. Whoever
    intercepts only ``builtins.open`` builds a test that silently checks nothing
    after the fix - exactly that happened to
    ``tests/unit/extended/test_docker_infra_gaps.py:1112``.
    """

    def __init__(self, monkeypatch):
        self.hit = False
        real_open = open
        real_fdopen = os.fdopen

        def _prepare(fh):
            self.hit = True

            def _raise(*_a, **_k):
                raise OSError("no space left on device")

            fh.write = _raise
            return fh

        def _open(file, mode="r", *a, **kw):
            fh = real_open(file, mode, *a, **kw)
            return _prepare(fh) if ("w" in mode or "a" in mode) else fh

        def _fdopen(fd, mode="r", *a, **kw):
            fh = real_fdopen(fd, mode, *a, **kw)
            return _prepare(fh) if ("w" in mode or "a" in mode) else fh

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)


@pytest.fixture
def counter(tmp_path, monkeypatch):
    """Sequence counter with a known value in its own storage."""
    file = tmp_path / "last_seq.txt"
    file.write_text("5", encoding="utf-8")
    monkeypatch.setattr(ps, "SEQ_FILE", file)
    return file


def test_interrupted_write_leaves_the_counter_intact(counter, monkeypatch):
    """If the write fails, the old value is still in the file.

    Today ``next_seq()`` opens the file with ``"w"`` - which truncates it already
    on opening, before anything has been written. The counter is then gone, and
    with it the numbering of the donation ledger.
    """
    failure = _WriteFailsOnWrite(monkeypatch)

    with pytest.raises(OSError):
        ps.next_seq()

    assert failure.hit, (
        "The write error was never triggered - then this test checks "
        "nothing. The implementation probably writes via a third path that "
        "is not intercepted here."
    )
    assert counter.read_text(encoding="utf-8").strip() == "5", (
        "The write failed and destroyed the counter in the process - "
        "the next sequence number starts again at 1 and hands out numbers "
        "twice that already appear in the donation ledger"
    )


def test_successful_write_still_increments(counter):
    """The opposite direction: without an error it keeps counting normally.

    Without this case one could tighten ``next_seq()`` to "never writes"
    and the test above would stay green.
    """
    assert ps.next_seq() == 6
    assert counter.read_text(encoding="utf-8").strip() == "6"
    assert ps.next_seq() == 7


def test_no_temp_leftovers_after_success(counter):
    """An atomic implementation cleans up its temp file.

    Not cosmetic: if leftovers lie around, they pile up in the donation
    ledger's storage, and a later reader cannot tell them apart from real
    files.
    """
    ps.next_seq()

    leftovers = [p.name for p in counter.parent.iterdir() if p.name != counter.name]
    assert leftovers == [], f"Temp leftovers remain: {leftovers}"
