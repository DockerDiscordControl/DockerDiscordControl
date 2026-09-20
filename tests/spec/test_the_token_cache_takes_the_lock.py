# -*- coding: utf-8 -*-
"""The token cache is touched under the same lock as everything else.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 11 F3, re-checked 2026-09-20):
``get_cached_token``, ``set_cached_token`` and ``clear_token_cache`` read and
write ``_token_cache`` and ``_token_cache_hash`` without taking
``_cache_lock`` - while every other method of the class takes it, including
``invalidate_cache``, which clears those very two fields.

``set_cached_token`` writes the token first and its hash second. A reader
between the two sees the NEW token next to the OLD hash: ``get_cached_token``
compares the hash it was asked for against a hash that no longer describes
the token it then returns - a decrypted bot token handed out for the wrong
key. The window is small and the callers may well be one thread today;
nothing says they must stay that way, and the fields are already guarded
everywhere else.
"""

import threading

import pytest

from services.config.config_cache_service import ConfigCacheService

TOKEN = "a-decrypted-bot-token"
ENCRYPTED = "encrypted-blob"
PASSWORD_HASH = "hash-of-the-password"


class _WatchedLock:
    """A real lock that counts how often it was entered."""

    def __init__(self):
        self._lock = threading.Lock()
        self.entered = 0

    def __enter__(self):
        self._lock.acquire()
        self.entered += 1
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


@pytest.fixture
def service():
    cache = ConfigCacheService()
    cache._cache_lock = _WatchedLock()
    return cache


def test_invalidate_cache_takes_the_lock(service):
    """Premise: the watched lock sees what the class already does right."""
    service.invalidate_cache()

    assert service._cache_lock.entered == 1


def test_setting_the_token_takes_the_lock(service):
    service.set_cached_token(ENCRYPTED, PASSWORD_HASH, TOKEN)

    assert service._cache_lock.entered == 1, "the token and its hash are written unguarded"


def test_reading_the_token_takes_the_lock(service):
    service._cache_lock.entered = 0
    service.get_cached_token(ENCRYPTED, PASSWORD_HASH)

    assert service._cache_lock.entered == 1, "the two-step check runs unguarded"


def test_clearing_the_token_takes_the_lock(service):
    service.clear_token_cache()

    assert service._cache_lock.entered == 1


def test_the_cache_still_works(service):
    """Counter-check: guarding it must not break what it is for."""
    assert service.get_cached_token(ENCRYPTED, PASSWORD_HASH) is None

    service.set_cached_token(ENCRYPTED, PASSWORD_HASH, TOKEN)
    assert service.get_cached_token(ENCRYPTED, PASSWORD_HASH) == TOKEN
    assert service.get_cached_token(ENCRYPTED, "another-password") is None

    service.clear_token_cache()
    assert service.get_cached_token(ENCRYPTED, PASSWORD_HASH) is None


class _SwappingLock:
    """A lock that only shows the cached token while it is held.

    Counting entries cannot tell "takes the lock" from "takes the lock and then
    reads the fields outside it" - a mutation that did exactly that went
    unnoticed. This lock puts the hit in place on enter and takes it away again
    on exit, so only a read INSIDE the lock can find it.
    """

    def __init__(self, service, cache_key):
        self._lock = threading.Lock()
        self._service = service
        self._cache_key = cache_key

    def __enter__(self):
        self._lock.acquire()
        self._service._token_cache = TOKEN
        self._service._token_cache_hash = self._cache_key
        return self

    def __exit__(self, *exc):
        self._service._token_cache_hash = "gone-again"
        self._lock.release()
        return False


class _RecordingLock:
    """Remembers what the guarded fields held when the lock was released."""

    def __init__(self, service):
        self._lock = threading.Lock()
        self._service = service
        self.seen_on_exit = None

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self.seen_on_exit = (self._service._token_cache, self._service._token_cache_hash)
        self._lock.release()
        return False


def _cache_key(service):
    service._cache_lock = _WatchedLock()
    service.set_cached_token(ENCRYPTED, PASSWORD_HASH, TOKEN)
    return service._token_cache_hash


def test_the_token_is_read_inside_the_lock():
    """Counter-check: added after a mutation that read the fields outside it."""
    service = ConfigCacheService()
    key = _cache_key(service)
    service._token_cache_hash = "not-the-key"
    service._cache_lock = _SwappingLock(service, key)

    assert service.get_cached_token(ENCRYPTED, PASSWORD_HASH) == TOKEN, (
        "the fields were read outside the lock - the hit was not there yet"
    )


def test_the_token_is_written_inside_the_lock():
    """Counter-check: the same for the write."""
    service = ConfigCacheService()
    service._cache_lock = _RecordingLock(service)

    service.set_cached_token(ENCRYPTED, PASSWORD_HASH, TOKEN)

    token, token_hash = service._cache_lock.seen_on_exit
    assert token == TOKEN and token_hash, (
        "when the lock was released the fields were still unset - they are "
        "written outside it"
    )
