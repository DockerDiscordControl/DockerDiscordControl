# -*- coding: utf-8 -*-
"""An event on a protected container does not spend a watchdog rule's rule-wide cooldown.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F3, verified
2026-09-29). _execute_container_rule takes the cooldown locks before it
checks for a protected container (so the protected notice is rate-limited)
- and the protected branch returned without freeing the RULE cooldown. A
rule with cooldown_scope 'rule' whose event came from a protected
container - always including DDC itself - skipped every other container
for the whole cooldown, "Rule cooldown active", although nothing had been
done. Everywhere else a batch that did nothing frees the rule cooldown.

THE CONTRACT: the protected branch frees the rule-wide cooldown; the
container's own cooldown stays and keeps the notice rate-limited.

HOW THIS TEST CAN FAIL: the protected branch keeps the rule cooldown again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


def test_the_protected_branch_frees_the_rule_cooldown(monkeypatch):
    from services.automation import automation_service as module
    from services.automation.auto_action_config_service import AutoActionRule

    monkeypatch.setattr(module, "protected_names", AsyncMock(return_value={"ddc"}))
    monkeypatch.setattr(module, "rule_may_act_on", lambda rule, container: True)
    service = module.AutomationService.__new__(module.AutomationService)
    state = MagicMock()
    state.acquire_execution_locks.return_value = (True, "", None)
    service.state_service = state
    service._alert = AsyncMock()
    rule = AutoActionRule.from_dict({
        "id": "w1", "name": "watch", "enabled": True,
        "trigger": {"type": "container_state", "states": ["unhealthy"], "containers": []},
        "action": {"type": "RESTART", "containers": [], "silent": True},
        "safety": {"cooldown_minutes": 30, "cooldown_scope": "rule"}})
    event = SimpleNamespace(container="ddc", reason="ddc is unhealthy", kind="unhealthy")

    acted = asyncio.run(service._execute_container_rule(rule, event, {}, object(), None))

    assert acted is False
    state.release_rule_cooldown.assert_called_once_with("w1")
