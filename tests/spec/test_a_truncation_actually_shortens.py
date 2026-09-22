# -*- coding: utf-8 -*-
"""
THE FINDING (review C15, section 35 F5): `truncate_string(text, max_length)`
promises a string of at most `max_length` characters, suffix included. Its last
line is

    return text[:max_length - len(suffix)] + suffix

When `max_length` is smaller than the suffix (3 characters by default), the
slice index goes negative: `truncate_string("hello world", 2)` computes
`text[:-1]`, which keeps almost the whole string, and then appends "...". The
result is twelve characters long for a limit of two - longer than the input it
was asked to shorten.

The counter-check (test_the_ordinary_case_is_unchanged) holds the normal path:
a real truncation still lands exactly on the limit, and a short string is
returned untouched.
"""

import pytest

from utils.common_helpers import truncate_string


@pytest.mark.parametrize("max_length", [0, 1, 2, 3])
def test_a_tiny_limit_still_produces_a_short_string(max_length):
    """THE FINDING: the result must never be longer than the limit."""
    result = truncate_string("hello world", max_length)

    assert len(result) <= max_length


def test_a_tiny_limit_does_not_grow_the_text():
    """Stated the other way round, because that is the absurd part."""
    assert len(truncate_string("hello world", 2)) < len("hello world")


def test_the_ordinary_case_is_unchanged():
    """COUNTER-CHECK: the normal path must keep behaving exactly as before."""
    assert truncate_string("hello", 10) == "hello"
    assert truncate_string("abcde", 5) == "abcde"
    assert truncate_string("abcdefghij", 8) == "abcde..."
    assert len(truncate_string("abcdefghij", 8)) == 8
    assert truncate_string("abcdefghij", 6, suffix="~") == "abcde~"
