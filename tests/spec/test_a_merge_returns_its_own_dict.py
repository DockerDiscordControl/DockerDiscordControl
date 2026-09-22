# -*- coding: utf-8 -*-
"""
THE FINDING (review C39, section 35 F6): `deep_merge_dicts` hands back a
dictionary whose untouched branches ARE the caller's own objects.

    result = dict1.copy()          # shallow

For a key that exists only in dict1 - or is taken straight from dict2 - the
nested value in the result is the same object as in the input. So

    merged = deep_merge_dicts(defaults, overrides)
    merged['section']['x'] = 1

quietly writes into `defaults`, and every later merge starts from a `defaults`
that is no longer the defaults. A function called "deep merge" that returns a
result entangled with its inputs is a trap, and the docstring says nothing
about it.

WHAT IS TRUE ABOUT THE REACH: nothing in the project calls this function. Only
tests do. It is a trap rather than a live bug, fixed rather than deleted for
the same reason as reviews C30, C36 and C38 - and because a caller-less helper
with this name is exactly what someone reaches for when merging config.

The counter-checks keep the merge a merge: the values still merge the way they
did, and the inputs themselves are never touched.
"""

import pytest

from utils.common_helpers import deep_merge_dicts


def test_the_result_does_not_share_a_branch_with_the_first_input():
    """THE FINDING: writing into the result must not write into the input."""
    defaults = {"section": {"x": 1}}

    merged = deep_merge_dicts(defaults, {})
    merged["section"]["x"] = 99

    assert defaults == {"section": {"x": 1}}


def test_the_result_does_not_share_a_branch_with_the_second_input():
    """The same for a key taken straight from the second dictionary."""
    overrides = {"section": {"y": 2}}

    merged = deep_merge_dicts({}, overrides)
    merged["section"]["y"] = 99

    assert overrides == {"section": {"y": 2}}


def test_a_list_is_not_shared_either():
    """Lists are the other kind of value people mutate in place."""
    defaults = {"servers": ["a", "b"]}

    merged = deep_merge_dicts(defaults, {})
    merged["servers"].append("c")

    assert defaults == {"servers": ["a", "b"]}


def test_the_merge_still_merges():
    """COUNTER-CHECK: independence must not be bought with wrong values."""
    merged = deep_merge_dicts(
        {"a": 1, "nested": {"keep": 1, "replace": 1}},
        {"b": 2, "nested": {"replace": 2}})

    assert merged == {"a": 1, "b": 2, "nested": {"keep": 1, "replace": 2}}


def test_neither_input_is_modified():
    """COUNTER-CHECK: the merge itself never writes into what it was given."""
    first = {"a": {"x": 1}}
    second = {"a": {"y": 2}}

    deep_merge_dicts(first, second)

    assert first == {"a": {"x": 1}}
    assert second == {"a": {"y": 2}}
