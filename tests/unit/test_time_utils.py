import os
from datetime import datetime, timezone

import pytest

from utils.time_utils import (
    get_current_time,
    get_utc_timestamp,
    timestamp_to_datetime,
    datetime_to_timestamp,
    format_duration,
    is_same_day,
    get_timezone_offset,
    format_datetime_with_timezone,
    parse_timestamp,
)


def test_get_current_time_default_utc():
    dt = get_current_time()
    assert dt.tzinfo is not None
    # Should be UTC by default
    assert dt.tzinfo.utcoffset(dt) == timezone.utc.utcoffset(dt)


def test_get_utc_timestamp_monotonic():
    t1 = get_utc_timestamp()
    t2 = get_utc_timestamp()
    assert t2 >= t1


def test_timestamp_roundtrip():
    now_dt = datetime.now(timezone.utc)
    ts = datetime_to_timestamp(now_dt)
    back = timestamp_to_datetime(ts)
    # Allow small rounding differences
    assert abs((back - now_dt).total_seconds()) < 1


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (5, "5.0s"),
        (65, "1m 5s"),
        (3600 + 2 * 60, "1h 2m"),
        (2 * 24 * 3600 + 3 * 3600, "2d 3h"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_is_same_day_with_tz():
    dt1 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    # 21:00 UTC = 22:00 Europe/Berlin on Jan 1 (CET), still same local day
    dt2 = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    assert is_same_day(dt1, dt2, tz_name="Europe/Berlin") is True


def test_get_timezone_offset_valid_and_invalid():
    off = get_timezone_offset("Europe/Berlin")
    assert isinstance(off, str)
    off_bad = get_timezone_offset("Not/AZone")
    assert off_bad == "+00:00"


def test_format_datetime_with_timezone_and_env_tz(monkeypatch):
    # Force TZ via env
    monkeypatch.setenv("TZ", "Europe/Berlin")
    dt = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    formatted = format_datetime_with_timezone(dt)
    assert "2025" in formatted
    # time_only
    formatted_time_only = format_datetime_with_timezone(dt, time_only=True)
    assert ":" in formatted_time_only


@pytest.mark.parametrize(
    "inp,valid",
    [
        ("2025-01-01T12:00:00Z", True),
        ("2025-01-01T12:00:00.123456Z", True),
        ("2025-01-01 12:00:00", True),
        ("2025-01-01 12:00", True),
        ("2025-01-01", True),
        ("not-a-date", False),
    ],
)
def test_parse_timestamp_variants(inp, valid):
    dt = parse_timestamp(inp)
    assert (dt is not None) == valid


