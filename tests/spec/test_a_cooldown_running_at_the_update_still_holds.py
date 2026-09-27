# -*- coding: utf-8 -*-
"""A cooldown that was running when DDC was updated still holds afterwards.

THE FINDING (migration review v2.4.1 -> v3.0, 2026-09-27): v2.4.1 kept the
container cooldown of the auto-actions under the container's name alone
(v2.4.1 services/automation/auto_action_state_service.py:165), v3.0 keys it by
rule and container (cooldown_key, "<rule id>::<container>"). The state file
carries over, but nothing looked up the old keys any more: a restart rule that
fired an hour before the update, with a 24 h cooldown, could fire again the
moment the updated bot saw the next matching message.

WHAT HOLDS NOW: an old entry counts for every rule on that container - which
is what it meant in v2.4.1 - until it runs out.

HOW THIS TEST CAN FAIL: the old entry is ignored at either place that reads a
cooldown (check_cooldown, acquire_execution_locks), or an old entry that has
run out still blocks.

COUNTER-CHECK (2026-09-27): with _last_container_run reading only the new key,
both blocking cases went red.
"""

import json
import time

import pytest

from services.automation.auto_action_state_service import AutoActionStateService


@pytest.fixture
def state_from_v241(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    def make(fired_seconds_ago):
        # The shape v2.4.1 wrote: container_cooldowns keyed by the container name.
        (tmp_path / "auto_actions_state.json").write_text(json.dumps({
            "global_last_triggered": 0.0,
            "rule_cooldowns": {"rule-a": time.time() - fired_seconds_ago},
            "container_cooldowns": {"valheim": time.time() - fired_seconds_ago},
            "trigger_history": {},
        }))
        return AutoActionStateService()
    return make


def test_the_check_still_sees_it(state_from_v241):
    state = state_from_v241(fired_seconds_ago=3600)
    blocked, reason = state.check_cooldown("rule-a", "valheim", global_cooldown=0, rule_cooldown_mins=1440)
    assert blocked, "a cooldown running at the update was forgotten"
    assert "valheim" in reason


def test_the_atomic_lock_still_sees_it(state_from_v241):
    state = state_from_v241(fired_seconds_ago=3600)
    ok, reason, _ = state.acquire_execution_locks("rule-b", ["valheim"], global_cooldown=0, rule_cooldown_mins=1440)
    assert not ok, "another rule acted on the container although v2.4.1 held it for a day"


def test_a_run_out_old_cooldown_blocks_nothing(state_from_v241):
    state = state_from_v241(fired_seconds_ago=2 * 86400)
    ok, _, _ = state.acquire_execution_locks("rule-a", ["valheim"], global_cooldown=0, rule_cooldown_mins=1440)
    assert ok
