# -*- coding: utf-8 -*-
"""A groups.json of the wrong shape does not stop the other watchdog rules.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F10): a
groups.json that is valid JSON with a wrong shape - "containers": null, a
hand edit - made the group lookup raise TypeError. The rule engine caught
only OSError there and the status loop neither, so every watchdog event of
that poll was lost for EVERY rule, on every poll, for as long as the file
stayed that way.

THE CONTRACT: a group that cannot be read resolves to nothing, with an ERROR
line; the other rules act.

HOW THIS TEST CAN FAIL: the TypeError escapes again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.automation import automation_service as module
from services.automation.auto_action_config_service import AutoActionRule


def _rule(rule_id, containers, action):
    return AutoActionRule.from_dict({
        "id": rule_id, "name": rule_id, "enabled": True,
        "trigger": {"type": "container_state", "states": ["stopped"], "containers": containers},
        "action": {"type": action, "containers": [], "silent": True},
        "safety": {"cooldown_minutes": 30, "cooldown_scope": "rule"}})


def test_the_other_rule_still_acts(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "groups.json").write_text(json.dumps(
        {"groups": [{"name": "g", "containers": None}]}), encoding="utf-8")
    from services.config.group_service import reset_group_service
    reset_group_service()
    monkeypatch.setattr(module, "protected_names", AsyncMock(return_value=set()))
    monkeypatch.setattr("services.automation.maintenance.pauses", lambda: {})
    service = module.AutomationService.__new__(module.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True}
    service.config_service.get_rules.return_value = [_rule("r1", ["group:g"], "NOTIFY"),
                                                     _rule("r2", [], "NOTIFY")]
    state = MagicMock()
    state.acquire_execution_locks.return_value = (True, "", None)
    service.state_service = state
    service._alert = AsyncMock(return_value=True)
    event = SimpleNamespace(container="x", reason="x stopped", kind="stopped")

    asyncio.run(service.process_container_events([event], bot=object()))

    acted = [c.args[0] for c in state.record_trigger.call_args_list if c.args[4] == "SUCCESS"]
    assert "r2" in acted, f"a misshapen groups.json stopped the other rule: {acted}"
