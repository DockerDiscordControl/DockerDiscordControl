# -*- coding: utf-8 -*-
"""Uptime is formatted in one place, not three.

cogs/status_handlers.py built the "2d 3h 5m" uptime text three times, in the
bulk fetch (from StartedAt and from the service's uptime_seconds) and in the
single fetch - the same rules written out three times. Twins drift; the
question is only when. Found when the container watchdog (Phase 4a) had to add
two lines to StatusHandlersMixin, which the class-size ceiling does not allow:
merging the three copies made the room.

The table below is the contract the three copies shared; the source check
keeps a fourth copy from appearing.

COUNTER-CHECK (2026-09-22): red before the merge (no helper, three copies).
"""

import pytest
from pathlib import Path

CASES = [
    ((0, 0), "0m"),
    ((0, 59), "0m"),
    ((0, 60), "1m"),
    ((0, 3600), "1h"),
    ((0, 3660), "1h 1m"),
    ((1, 0), "1d"),
    ((2, 3 * 3600 + 5 * 60), "2d 3h 5m"),
    ((3, 120), "3d 2m"),
]


@pytest.mark.parametrize("days_seconds,expected", CASES)
def test_the_uptime_text(days_seconds, expected):
    from cogs.status_handlers import format_uptime

    assert format_uptime(*days_seconds) == expected


def test_there_is_one_copy():
    source = (Path(__file__).resolve().parents[2] / "cogs" / "status_handlers.py").read_text(encoding="utf-8")
    assert source.count("uptime_parts = []") == 1, source.count("uptime_parts = []")
