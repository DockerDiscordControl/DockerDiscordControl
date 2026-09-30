# -*- coding: utf-8 -*-
"""The ledger line of a donation is on the disk before the snapshot that counts it.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F8): the
ledger append was not fsynced, while the snapshot written right after it
was. On a power loss or kernel crash in the writeback window the snapshot
survived with the donation - last_event_seq pointing at it - while the
ledger line was gone; the next rebuild (an admin delete or restore)
dropped that donation without a word. The ledger is the only record of
the real donations (SPEC Z1). Needs a machine crash, not a process crash,
so the test watches the order of the fsync calls instead.

THE CONTRACT: the event log is fsynced after the append, before the
snapshot is written.

HOW THIS TEST CAN FAIL: the append is not fsynced, or only after the
snapshot.

COUNTER-CHECK (2026-09-30): red before the change (only the snapshot and
the sequence file were fsynced).
"""

import os

from tests.spec.test_a_new_release_refuels_an_empty_mech import mech, module  # noqa: F401 - fixtures


def test_the_event_log_is_synced_before_the_snapshot(module, mech, monkeypatch):
    synced = []
    real_fsync = os.fsync

    def fsync(fd):
        synced.append(os.path.basename(os.readlink(f"/proc/self/fd/{fd}")))
        return real_fsync(fd)
    monkeypatch.setattr(os, "fsync", fsync)

    mech.add_donation(5.0, idempotency_key="k-24-6")

    log_name = module.EVENT_LOG.name
    assert log_name in synced, f"the ledger was never synced: {synced}"
    # persist_snapshot writes ".main.json.<random>.tmp" and renames it
    snapshot_syncs = [i for i, name in enumerate(synced) if name.startswith(".main.json.")]
    assert synced.index(log_name) < max(snapshot_syncs), f"the ledger was synced after the snapshot: {synced}"
