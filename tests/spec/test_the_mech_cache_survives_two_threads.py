# -*- coding: utf-8 -*-
"""The shared mech data cache does not fail a request when another thread touches it.

THE FINDING (stage 4 review before v3.1.0, section 22 pass 4 F5): the
singleton's cache dict had no protection. Two threads that expire the same
key both reached `del self._cache[key]` and the second raised KeyError; the
5-minute cleanup iterating self._cache.items() while another thread
inserted could raise RuntimeError. get_comprehensive_data turned either
into success=False for that request - once with the result already
computed. The data store is read from waitress threads and the bot's
loops (real threads; gevent is opt-in).

THE CONTRACT: the cache is read, expired and cleaned under a lock, with
operations that tolerate a key another thread already removed.

HOW THIS TEST CAN FAIL: the other thread's move makes the request fail.
Both cases play the other thread's move deterministically, inside the
dict, at the point where it used to hurt.

COUNTER-CHECK (2026-09-30): red before the change (KeyError, RuntimeError
-> success False).
"""

import time

from services.mech.mech_data_store import MechDataRequest, MechDataStore


class _OtherThreadExpiresIt(dict):
    """Between the membership check and the delete, the other thread deletes."""

    def __getitem__(self, key):
        entry = dict.__getitem__(self, key)
        dict.pop(self, key, None)
        return entry


class _OtherThreadInsertsWhileItIsRead(dict):
    """An entry whose reading lets the other thread insert into the cache -
    in the middle of the cleanup's walk over it."""

    def __init__(self, cache, **fields):
        super().__init__(**fields)
        self._cache = cache

    def get(self, key, default=None):
        self._cache[f"other_{len(self._cache)}"] = {"data": None, "timestamp": time.time()}
        return dict.get(self, key, default)


def test_an_entry_expired_by_another_thread_does_not_fail_the_request():
    store = MechDataStore()
    request = MechDataRequest()
    store.get_comprehensive_data(MechDataRequest(force_refresh=True))
    key = next(iter(store._cache))
    stale = dict(store._cache[key], timestamp=time.time() - 60)
    store._cache = _OtherThreadExpiresIt({key: stale})

    result = store.get_comprehensive_data(request)
    assert result.success, result.error


def test_an_insert_during_the_cleanup_does_not_fail_the_request():
    store = MechDataStore()
    store._cache["old"] = _OtherThreadInsertsWhileItIsRead(store._cache, data=None,
                                                           timestamp=time.time() - 60)
    store._last_cache_clear = time.time() - 301

    result = store.get_comprehensive_data(MechDataRequest(force_refresh=True))
    assert result.success, result.error
