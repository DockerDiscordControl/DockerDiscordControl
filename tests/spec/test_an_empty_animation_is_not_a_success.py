# -*- coding: utf-8 -*-
"""
THE FINDING (review C13, section 21 F2): `get_mech_animation` guards its result
with

    if animation_bytes is None:
        return MechAnimationResult(success=False, ...)

but the producer it calls does not always return None when it fails.
`_get_animation_internal` returns `b""` when the base cache file is missing and
`pre_generate_animation()` cannot create it - the documented case is the
Cache-Only Docker deployment, where `assets_dir` is None and pre-generation
quietly does nothing. Empty bytes are not None, so the guard waves them through
and the caller is handed

    MechAnimationResult(success=True, animation_bytes=b"", ...)

A caller that checks `result.success` - which is exactly what a result object
is for - is told the animation was generated. What it has is nothing.

The counter-check (test_real_bytes_are_still_a_success) keeps the fix from
becoming "nothing succeeds any more".
"""

import pytest

from services.mech.animation_cache_service import (
    AnimationCacheService,
    MechAnimationRequest,
)


@pytest.fixture
def service():
    return AnimationCacheService.__new__(AnimationCacheService)


def _request(**kwargs):
    params = dict(evolution_level=3, speed_level=2, power_level=50.0)
    params.update(kwargs)
    return MechAnimationRequest(**params)


def test_empty_bytes_are_reported_as_a_failure(service, monkeypatch):
    """THE FINDING: b"" is what the producer returns when it could not build
    anything - it must not arrive as success=True."""
    monkeypatch.setattr(service, "get_animation_with_speed_and_power",
                        lambda **kwargs: b"")

    result = service.get_mech_animation(_request())

    assert result.success is False
    assert result.error_message


def test_none_is_still_reported_as_a_failure(service, monkeypatch):
    """The case the guard already covered stays covered."""
    monkeypatch.setattr(service, "get_animation_with_speed_and_power",
                        lambda **kwargs: None)

    assert service.get_mech_animation(_request()).success is False


def test_real_bytes_are_still_a_success(service, monkeypatch):
    """COUNTER-CHECK: a working animation is still a working animation."""
    monkeypatch.setattr(service, "get_animation_with_speed_and_power",
                        lambda **kwargs: b"RIFF....WEBP")
    monkeypatch.setattr(service, "get_expected_canvas_size",
                        lambda level, kind: (256, 256))

    result = service.get_mech_animation(_request())

    assert result.success is True
    assert result.animation_bytes == b"RIFF....WEBP"
