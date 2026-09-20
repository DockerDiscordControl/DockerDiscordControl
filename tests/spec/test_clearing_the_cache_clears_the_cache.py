# -*- coding: utf-8 -*-
"""
THE FINDING (review C22, section 21 F1): `clear_cache()` says in its own
docstring and log line what it is for - "Clear all cached animations to force
regeneration with new PNG files", "new walk animations will be generated" - and
then does one third of it:

    self.cleanup_old_animations(keep_hours=0)

which deletes only the files matching `*.cache`, the 100%-speed base files. It
never clears `self._focused_cache`, the RAM cache of up to four ready-made
animations, and never deletes the derived speed-adjusted files
`mech_L*_S*.webp`. So the very next request for a combination that is still in
RAM, or that already has a speed file on disk, is served the OLD animation -
straight past the base cache that was just emptied. The operator drops in new
PNGs, calls the function that promises regeneration, and keeps seeing the old
mech.

`invalidate_animation_cache()` three hundred lines further down already does
all three. `clear_cache()` was a narrower copy of it.

The counter-check (test_an_unrelated_file_is_left_alone) keeps the clearing
from turning into "delete everything in the directory". Its first version put
the speed files in the directory too and so went red for the finding's own
reason - worthless as a blindness probe; it now touches only a base file and an
unrelated one.
"""

import pytest

from services.mech.animation_cache_service import AnimationCacheService


@pytest.fixture
def service(tmp_path):
    instance = AnimationCacheService.__new__(AnimationCacheService)
    instance.cache_dir = tmp_path
    instance._focused_cache = {}
    return instance


def _fill(service):
    (service.cache_dir / "mech_L3_walk.cache").write_bytes(b"base")
    (service.cache_dir / "mech_L3_S7.webp").write_bytes(b"speed variant")
    (service.cache_dir / "mech_L4_S2.webp").write_bytes(b"another speed variant")
    service._focused_cache["L3_S7_walk_small"] = b"in RAM"


def test_the_speed_variants_go_too(service):
    """THE FINDING: the derived files outlive the base file they came from."""
    _fill(service)

    service.clear_cache()

    left = sorted(p.name for p in service.cache_dir.iterdir())
    assert left == []


def test_the_ram_cache_goes_too(service):
    """Four ready-made animations in RAM are served before any file is read."""
    _fill(service)

    service.clear_cache()

    assert len(service._focused_cache) == 0


def test_an_unrelated_file_is_left_alone(service):
    """COUNTER-CHECK: clearing the animation cache is not "empty the
    directory". Only the two files this test writes are involved, so it holds
    the same line before and after the fix and cannot go red for the finding's
    reason."""
    (service.cache_dir / "mech_L3_walk.cache").write_bytes(b"base")
    (service.cache_dir / "notes.txt").write_text("not an animation")

    service.clear_cache()

    assert [p.name for p in service.cache_dir.iterdir()] == ["notes.txt"]
