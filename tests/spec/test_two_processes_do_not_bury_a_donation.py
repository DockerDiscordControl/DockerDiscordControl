# -*- coding: utf-8 -*-
"""Bot and web process do not bury each other's donations.

THE FINDING: the mech's progress state - the event log, the sequence number
and the snapshot - is guarded by a threading.RLock. The bot and the web panel
are two PROCESSES (supervisord), so that lock serialises nothing between
them. Both load the snapshot, both take "the next" sequence number and both
write: the second snapshot is written from a state that never saw the first
one's event, with a last_event_seq that says it did - and the check for a
lagging snapshot then never looks at that event again. A donation booked in
Discord can vanish from the mech's state while its event still sits in the
log.

The same file lock the scheduler and the query-support service use now
spans these cycles.

COUNTER-CHECK (2026-09-22): red before - the two processes booked $5 each and
the state held $5. The reader here needs its own counter-check: it read a
snapshot another test in the group had left in the cached path, and passed
alone while failing in the group. It now clears that cache; see the comment
below.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

DONOR = textwrap.dedent('''
    import sys, time
    sys.path.insert(0, {root!r})
    from services.mech import progress_service

    # widen the window between this process's read and its write
    real_persist = progress_service.persist_snapshot
    def slow_persist(snap):
        time.sleep({delay})
        return real_persist(snap)
    progress_service.persist_snapshot = slow_persist

    service = progress_service.get_progress_service()
    service.add_donation(5.0, donor={donor!r}, idempotency_key={donor!r})
''')


def _donor(tmp_path, name, delay):
    script = DONOR.format(root=str(ROOT), delay=delay, donor=name)
    # DDC_PROGRESS_DATA_DIR, not DDC_CONFIG_DIR: a configured progress
    # directory beats DDC_CONFIG_DIR (progress_paths.py:123-141), and in the
    # test runtime there IS one - these two processes were booking their $5
    # into the real mech state, and the check then read that state too.
    environment = dict(os.environ, DDC_CONFIG_DIR=str(tmp_path),
                       DDC_PROGRESS_DATA_DIR=str(tmp_path / "progress"))
    return subprocess.Popen([sys.executable, "-c", script], env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_both_donations_are_in_the_state(tmp_path, monkeypatch):
    import time

    first = _donor(tmp_path, "discord", delay=0.8)
    time.sleep(0.25)                      # the web process reads while the bot holds
    second = _donor(tmp_path, "panel", delay=0.0)
    for process in (first, second):
        assert process.wait(timeout=90) == 0, process.stderr.read()

    # Read the file, not the service: the service binds its directories once
    # per process at import (progress_service.py:110-116, progress_paths.py:171),
    # so in a group run the reader here kept whatever directory the first test
    # built and this test then checked another test's snapshot - green alone,
    # red in the group, both for the wrong reason.
    state = tmp_path / "progress" / "snapshots" / "main.json"
    assert state.is_file(), f"no snapshot under {tmp_path}: {list(tmp_path.rglob('*.json'))}"
    booked = json.loads(state.read_text(encoding="utf-8"))["cumulative_donations_cents"]

    assert booked == 1000, f"a donation was buried: {booked} cents in the state"
