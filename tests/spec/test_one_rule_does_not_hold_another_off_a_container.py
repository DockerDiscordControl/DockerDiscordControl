# -*- coding: utf-8 -*-
"""One rule acting on a container does not hold every other rule off it.

THE FINDING, measured live on the operator's server on 2026-09-26: two NOTIFY
rules on the same container, A (priority 10) and B (priority 5). A hand stop
of the container: A reported it, and B was recorded as

    SKIPPED  Container 'ddc-watchdog-probe' cooldown active (0m remaining)

The container cooldown was keyed by the container ALONE, so whichever rule
acted first locked every other rule out of that container for its own
cooldown. A NOTIFY beside a RESTART on the same event never fired, and an
image-update notice at 06:00 (24 h cooldown) kept a crash restart away until
the next morning. "0m remaining" was the floor of 0.x minutes.

OPERATOR DECISION (2026-09-26): cooldowns per rule AND container. A rule still
cannot fire twice on the same container within its own cooldown.

HOW THIS TEST CAN FAIL: a second rule blocked by the first one's cooldown, or
one rule firing twice on a container inside its cooldown.

COUNTER-CHECK (2026-09-26): red before the fix - the second rule got
"Container 'web' cooldown active (0m remaining)".
"""

import pytest

from services.automation.auto_action_state_service import AutoActionStateService


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    return AutoActionStateService()


def test_a_second_rule_on_the_same_container_still_acts(state):
    assert state.acquire_execution_locks("restart-rule", ["web"], 0, 30)[0]
    state.record_trigger("restart-rule", "Restart", "web", "RESTART", "SUCCESS", "stopped")

    allowed, reason, _ = state.acquire_execution_locks("notify-rule", ["web"], 0, 30)

    assert allowed, reason


def test_the_same_rule_is_still_held_off(state):
    """Counter-case: the cooldown still does its job for the rule that acted."""
    assert state.acquire_execution_locks("restart-rule", ["web"], 0, 30)[0]
    state.record_trigger("restart-rule", "Restart", "web", "RESTART", "SUCCESS", "stopped")

    allowed, reason, _ = state.acquire_execution_locks("restart-rule", ["web"], 0, 30)

    assert not allowed
    assert "cooldown" in reason and "(0m" not in reason, reason
