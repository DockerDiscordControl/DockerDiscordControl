# -*- coding: utf-8 -*-
"""While DDC cannot read its own container's name, no rule restarts or stops anything unnamed.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F9): DDC keeps
its own container out of every rule's reach (protected_names). Inside a
container, that name is read from Docker once; when the read failed (a proxy
timeout, a Docker hiccup) the answer was "" - "not in a container" - and DDC
dropped out of the protected set. A rule with no container list reacting to
DDC's own event then restarted DDC, the danger the comment there names.

THE CONTRACT: in a container whose name cannot be read, restart/stop/start
actions are skipped for that cycle ("own container unknown"); NOTIFY still
goes out. Outside a container nothing changes.

HOW THIS TEST CAN FAIL: DDC acts on its own container during such a lookup
failure.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.automation import automation_service as module
from services.automation.auto_action_config_service import AutoActionRule


def test_a_watchdog_rule_does_not_restart_ddc(monkeypatch):
    monkeypatch.setattr(module, "_own_name", None)
    monkeypatch.setattr("services.docker_service.self_restart.own_container_id", lambda: "abcdef123456")
    monkeypatch.setattr("services.docker_service.self_restart.describe_self",
                        lambda: (False, "ReadTimeout"))
    monkeypatch.setattr(module, "rule_may_act_on", lambda rule, container: True)
    acted = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "docker_action", acted)
    service = module.AutomationService.__new__(module.AutomationService)
    state = MagicMock()
    state.acquire_execution_locks.return_value = (True, "", None)
    service.state_service = state
    service._alert = AsyncMock()
    service.config_service = MagicMock()
    rule = AutoActionRule.from_dict({
        "id": "w1", "name": "watch", "enabled": True,
        "trigger": {"type": "container_state", "states": ["unhealthy"], "containers": []},
        "action": {"type": "RESTART", "containers": [], "silent": True},
        "safety": {"cooldown_minutes": 30, "cooldown_scope": "rule"}})
    event = SimpleNamespace(container="dockerdiscordcontrol", reason="unhealthy", kind="unhealthy")

    asyncio.run(service._execute_container_rule(rule, event, {}, object(), None))

    acted.assert_not_awaited()


def test_a_docker_without_ddc_on_it_does_not_block_anything(monkeypatch):
    """Counter-case: NotFound is an answer (DDC controls another host), not "unknown"."""
    monkeypatch.setattr(module, "_own_name", None)
    monkeypatch.setattr("services.docker_service.self_restart.own_container_id", lambda: "abcdef123456")
    monkeypatch.setattr("services.docker_service.self_restart.describe_self", lambda: (False, "NotFound"))

    assert asyncio.run(module.protected_names({})) == set()
