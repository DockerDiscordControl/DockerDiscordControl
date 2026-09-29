# -*- coding: utf-8 -*-
"""A file lock that cannot be taken does not leave the ledger blocked for good.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F4, verified
2026-09-29). ProcessSafeLock.__enter__ acquired the in-process RLock and
then entered the cross-process file lock. If that raised - a progress.lock
owned by root (one exists on the live host), a full disk - the exception
left __enter__ with the RLock still held and no __exit__ to release it:
every later donation, gift or state read in any other thread waited on
`with LOCK:` for ever.

THE CONTRACT: a failed file lock releases the RLock before the error goes
on; another thread can take the lock afterwards.

HOW THIS TEST CAN FAIL: __enter__ raises with the RLock held again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import threading

import pytest


def test_a_failed_file_lock_releases_the_thread_lock(monkeypatch, tmp_path):
    from services.mech.progress.runtime import ProcessSafeLock
    import utils.atomic_io as atomic_io

    def _refused(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(atomic_io, "cross_process_lock", _refused)
    lock = ProcessSafeLock(lambda: tmp_path / "progress.lock")

    with pytest.raises(PermissionError):
        lock.__enter__()

    taken = []
    probe = threading.Thread(target=lambda: taken.append(lock._lock.acquire(timeout=1)))
    probe.start()
    probe.join(3)
    assert taken == [True], "another thread would wait on the ledger for ever"
