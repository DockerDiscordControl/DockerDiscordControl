# -*- coding: utf-8 -*-
"""
THE FINDING (review C47, section 29 F4): an invalid timezone in the config
takes the whole container refresh down instead of only the displayed time.

`_get_formatted_timestamp` wraps the timezone lookup in a handler whose comment
says "Fallback to system timezone" - and catches `except (RuntimeError)`.
`pytz.timezone()` raises `UnknownTimeZoneError`, which subclasses KeyError. So
neither the inner handler nor the outer one takes it; the exception travels up
into `refresh_containers`, whose top-level clause DOES list KeyError, and an
already-successful refresh is reported as a failure.

Two fallbacks were written for this, and the wrong exception type in front of
them made both unreachable.

The counter-checks keep the real timezone working and the fallback from
becoming the answer.
"""

import time

import pytest

from services.web.container_refresh_service import ContainerRefreshService


@pytest.fixture
def service():
    return ContainerRefreshService()


def _dependencies(timezone_value):
    return {
        'docker_cache': {'global_timestamp': 1789000000.0},
        'load_config': lambda: {'timezone': timezone_value},
    }


def test_an_invalid_timezone_only_costs_the_formatting(service):
    """THE FINDING: the refresh must survive a bad timezone name."""
    result = service._get_formatted_timestamp(_dependencies("Not/AZone"))

    assert result['timestamp'] == 1789000000.0
    assert result['formatted_time'], "no time was formatted at all"


def test_an_empty_timezone_is_survived_too(service):
    """The other shape of the same mistake in the config."""
    result = service._get_formatted_timestamp(_dependencies(""))

    assert result['formatted_time']


def test_a_real_timezone_is_still_used(service):
    """COUNTER-CHECK: the fallback must not become the answer."""
    result = service._get_formatted_timestamp(_dependencies("Asia/Tokyo"))

    assert result['formatted_time'].startswith("2026-09-10 ")
    assert result['formatted_time'].endswith("JST")
