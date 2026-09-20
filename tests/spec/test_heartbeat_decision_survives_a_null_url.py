# -*- coding: utf-8 -*-
"""Deciding whether the heartbeat runs never breaks the startup.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 04 F1, re-checked 2026-09-20):
the startup read ``heartbeat_cfg.get('ping_url', '').strip()``. With the key
present but null - an older config, a hand edit - that is
``None.strip()``: an AttributeError, which the surrounding
``except (OSError, KeyError, ValueError)`` does not catch. The rest of
``_setup_background_loops`` was skipped, including the first status message,
and nothing said so.

The decision now lives in ``_heartbeat_enabled`` and is tested here. It was
green from the start, so the mutation probe carries the proof (see the
commit): restoring ``.get('ping_url', '').strip()`` turns the "null" case
red.
"""

import pytest

from cogs.docker_control import _heartbeat_enabled


@pytest.mark.parametrize("config, expected, why", [
    ({}, False, "no heartbeat section at all"),
    ({"heartbeat": {"enabled": False, "ping_url": "https://example.com"}}, False, "switched off"),
    ({"heartbeat": {"enabled": True, "ping_url": "https://example.com"}}, True, "on, with a URL"),
    ({"heartbeat": {"enabled": True, "ping_url": ""}}, False, "on, but no URL"),
    ({"heartbeat": {"enabled": True, "ping_url": "   "}}, False, "on, but blank URL"),
    ({"heartbeat": {"enabled": True, "ping_url": None}}, False, "on, URL stored as null"),
    ({"heartbeat": {"enabled": True}}, False, "on, URL key missing"),
    ({"heartbeat": "nonsense"}, False, "heartbeat is not a section"),
])
def test_the_decision_holds_for_every_shape(config, expected, why):
    assert _heartbeat_enabled(config) is expected, why
