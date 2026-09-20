# -*- coding: utf-8 -*-
"""
THE FINDING (review C46, section 29 F5): the donation status endpoint has a
fallback for exactly this case and cannot reach it.

`_build_status_data_from_cache` reads `cache_result.bars.mech_progress_current`
and three siblings with no guard. Directly below it sits a handler that returns
a complete minimal status - "Return minimal fallback status" - but it catches
`except (RuntimeError)`, and a missing `bars` raises AttributeError. Its
caller, `get_donation_status`, catches `(RuntimeError)` as well. So the
exception leaves the service entirely and the panel gets a traceback instead of
the degraded status the code was written to produce.

The fallback is right there. Only the clause in front of it was wrong.

The counter-checks keep the normal answer intact and keep a real failure a
failure.
"""

import pytest

from services.web.donation_status_service import DonationStatusService


class _Bars:
    mech_progress_current = 30.0
    mech_progress_max = 100.0
    Power_current = 12.5
    Power_max_for_level = 50.0


class _CacheResult:
    success = True
    cache_age_seconds = 1.0
    level = 3
    power = 12.5
    total_donated = 300.0
    name = "ARMORED MECH"
    threshold = 800
    glvl = 3
    glvl_max = 100
    speed_description = "steady"
    speed_color = "#00FF00"
    bars = _Bars()


@pytest.fixture
def service():
    return DonationStatusService()


def _speed():
    return {"level": 4, "description": "steady", "color": "#00FF00"}


def _evolution():
    return {"decay_per_day": 1.0, "name": "ARMORED MECH"}


def test_a_missing_bars_object_gives_the_fallback_status(service):
    """THE FINDING: the minimal status below the handler must be reachable."""
    broken = _CacheResult()
    broken.bars = None

    status = service._build_status_data_from_cache(broken, _speed(), _evolution())

    assert isinstance(status, dict)
    assert status.get("mech_level") is not None


def test_a_bars_object_missing_a_field_gives_the_fallback_status(service):
    """The same for a bars object that is there but incomplete."""
    broken = _CacheResult()
    broken.bars = object()

    status = service._build_status_data_from_cache(broken, _speed(), _evolution())

    assert isinstance(status, dict)


def test_the_normal_answer_still_carries_the_real_numbers(service):
    """COUNTER-CHECK: the fallback must not become the answer."""
    status = service._build_status_data_from_cache(_CacheResult(), _speed(), _evolution())

    assert status["total_amount"] == 300.0
    assert status["bars"]["mech_progress_current"] == 30.0
    assert status["mech_level"] == 3
