# -*- coding: utf-8 -*-
"""The animation cache stays inside its limit, and keeps what is being used.

Two findings about cached_animations/, the directory of speed-adjusted WebP
files:

* the limit (DDC_ANIM_DISK_LIMIT_MB, 200 by default) was enforced in
  __init__ and nowhere else. Speed variants are written on demand for the
  whole life of the process - 11 levels x 2 types x 2 resolutions x the
  speed buckets - so an operator who set 50 MB got 50 MB at boot and
  whatever accumulated afterwards. It is enforced again after a new variant
  is written;
* eviction sorted by modification time, which is when a file was ENCODED and
  is never touched again by a read. The variant of the current level is
  written once at warm-up and then served on every refresh, so it was the
  oldest file in the directory and the first to be deleted - after which the
  next request re-encoded it. A cache hit marks the file as used.

COUNTER-CHECK (2026-09-22): red before - the limit was not enforced after a
write, and the file that had just been read was the one evicted.
"""

import os
import time

import pytest


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_ANIM_DISK_LIMIT_MB", "1")
    from services.mech.animation_cache_service import AnimationCacheService

    instance = object.__new__(AnimationCacheService)
    instance.cache_dir = tmp_path
    instance._disk_cache_limit_mb = 1
    return instance


def _variant(service, name, size, age_seconds=0):
    path = service.cache_dir / name
    path.write_bytes(b"x" * size)
    when = time.time() - age_seconds
    os.utime(path, (when, when))
    return path


def test_a_file_that_was_read_is_not_the_first_to_go(service):
    old_but_used = _variant(service, "mech_L1_S10.webp", 400_000, age_seconds=3600)
    younger = _variant(service, "mech_L9_S30.webp", 400_000, age_seconds=60)
    _variant(service, "mech_L8_S20.webp", 400_000, age_seconds=30)

    service.note_cache_hit(old_but_used)          # it is served on every refresh
    service.enforce_disk_cache_limit(1)

    assert old_but_used.exists(), "the file in use was evicted and has to be re-encoded"
    assert not younger.exists(), "nothing was evicted at all"


def test_the_limit_is_enforced_after_a_new_variant_is_written(service, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "enforce_disk_cache_limit", lambda mb: calls.append(mb))

    service._write_cache_file_atomic(service.cache_dir / "mech_L2_S10.webp", b"x" * 10)

    assert calls == [1], "the cache grows unchecked until the next restart"


def test_a_cache_under_the_limit_is_left_alone(service):
    """Counter-check: eviction must not run for its own sake."""
    kept = _variant(service, "mech_L1_S10.webp", 1000)

    assert service.enforce_disk_cache_limit(1) == 0
    assert kept.exists()
