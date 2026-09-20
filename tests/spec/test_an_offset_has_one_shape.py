# -*- coding: utf-8 -*-
"""
THE FINDING (review C38, section 36 F4): `get_timezone_offset` returns two
differently shaped strings depending on whether it worked.

    return now.strftime('%z')      # "+0100" - no colon
    ...
    return "+00:00"                # with colon

and the docstring's own example says `"+01:00"`, which matches neither the
success path nor a valid zone. A caller that compares, parses or displays the
result gets one shape on a good day and the other on a bad one, with nothing
to tell them apart.

WHAT IS TRUE ABOUT THE REACH: nothing in the project calls this function. It is
a trap rather than a wrong answer on screen - a helper that looks usable and
whose own documentation is wrong about what it returns. Fixed rather than
deleted for the same reason as reviews C30 and C36.

The shape chosen is the one the docstring promises, "+01:00", because that is
what a reader of this function has been told to expect and it is the ISO form.

The counter-check (test_the_offset_is_the_real_offset) keeps the shape from
being bought with a wrong value.
"""

import re

import pytest

from utils.time_utils import get_timezone_offset


SHAPE = re.compile(r"^[+-]\d{2}:\d{2}$")


@pytest.mark.parametrize("zone", [
    "Europe/Berlin",
    "UTC",
    "America/New_York",
    "Asia/Tokyo",
    "not-a-real-zone",
    "",
])
def test_every_answer_has_the_same_shape(zone):
    """THE FINDING: one function, one shape - working or not."""
    assert SHAPE.match(get_timezone_offset(zone)), get_timezone_offset(zone)


def test_the_offset_is_the_real_offset():
    """COUNTER-CHECK: the shape must not be bought with a wrong value."""
    assert get_timezone_offset("UTC") == "+00:00"
    assert get_timezone_offset("Asia/Tokyo") == "+09:00"
    # Berlin is +01:00 in winter and +02:00 in summer - both are real.
    assert get_timezone_offset("Europe/Berlin") in ("+01:00", "+02:00")


def test_an_unknown_zone_still_says_zero():
    """COUNTER-CHECK: the fallback keeps its meaning."""
    assert get_timezone_offset("not-a-real-zone") == "+00:00"
