# -*- coding: utf-8 -*-
"""One container's failure does not drop the cooldown of the whole rule.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 11 F1, re-checked 2026-09-20):
an auto-action rule with several target containers records one outcome per
container. ``record_trigger`` set the RULE cooldown on SUCCESS and reset it
to 0 on FAILED - so with container A restarted successfully and container B
failing right after ("Container not found", a plain docker failure), the
rule's cooldown was wiped although the rule HAD just acted. The next
matching message triggers it again immediately, and A is restarted over and
over as long as the messages keep coming.

THE RULE NOW: a single container's outcome only moves that container's
cooldown. The rule's own cooldown is released once, by the caller, and only
when NOTHING in the batch succeeded.
"""

import asyncio
from threading import Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_state_service import AutoActionStateService

RULE = "r1"


@pytest.fixture
def state(tmp_path):
    service = AutoActionStateService.__new__(AutoActionStateService)
    service.base_dir = tmp_path
    service.state_file = tmp_path / "auto_actions_state.json"
    service._lock = Lock()
    service.global_last_triggered = 0.0
    service.rule_cooldowns = {}
    service.container_cooldowns = {}
    service.trigger_history = {}
    return service


def test_a_failure_after_a_success_keeps_the_rule_cooldown(state):
    state.acquire_execution_locks(RULE, ["alpha", "beta"], 30, 60)

    state.record_trigger(RULE, "Rule", "alpha", "RESTART", "SUCCESS", "")
    state.record_trigger(RULE, "Rule", "beta", "RESTART", "FAILED", "Container not found")

    assert state.container_cooldowns.get(state.cooldown_key(RULE, "beta")) == 0, (
        "premise: the failed container may be retried at once"
    )
    assert state.rule_cooldowns.get(RULE, 0) > 0, (
        "the rule acted on 'alpha', but its cooldown was wiped by the failure on "
        "'beta' - the next message triggers the whole rule again"
    )


def test_the_rule_cooldown_is_released_when_nothing_succeeded(state):
    state.acquire_execution_locks(RULE, ["alpha", "beta"], 30, 60)

    state.record_trigger(RULE, "Rule", "alpha", "RESTART", "FAILED", "Container not found")
    state.record_trigger(RULE, "Rule", "beta", "RESTART", "FAILED", "Container not found")
    state.release_rule_cooldown(RULE)

    assert state.rule_cooldowns.get(RULE, 0) == 0, (
        "nothing was done, so the rule must be free to run again"
    )


def _rule(containers):
    return SimpleNamespace(
        id=RULE, name="Rule", priority=1, only_if_running=False,
        action=SimpleNamespace(type="RESTART", containers=list(containers), delay_seconds=0,
                               silent=True, notification_channel_id=None),
        safety=SimpleNamespace(cooldown_minutes=60, cooldown_scope="rule"),
        cooldown_minutes=60, cooldown_scope="rule")


@pytest.mark.asyncio
async def test_the_service_releases_the_rule_cooldown_when_all_fail(state, monkeypatch):
    """The other half of the rule: the caller does release it when nothing worked."""
    from services.automation import automation_service as auto_mod

    service = auto_mod.AutomationService.__new__(auto_mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True,
                                                              "protected_containers": []}
    service.state_service = state
    monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_trigger_status_refresh", AsyncMock())
    context = auto_mod.TriggerContext(message_id="1", channel_id="9", guild_id="2",
                                      user_id="3", username="w", is_webhook=False,
                                      content="crash", embeds_text="")

    await service._execute_rule(_rule(["alpha", "beta"]), context,
                                {"protected_containers": [], "global_cooldown_seconds": 30}, None)

    assert state.rule_cooldowns.get(RULE, 0) == 0, (
        "every container failed, so the rule must be free to run again"
    )
