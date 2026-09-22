# -*- coding: utf-8 -*-
"""Resource thresholds as container-state rules (Phase 4b, part 3).

A container-state rule can now also react to high_cpu and high_memory, with
its own threshold and duration. Checked here:

* validation accepts the new states and refuses thresholds or durations out
  of range; the settings survive the save round trip;
* an event reaches only the rules whose threshold and duration measured it;
* the status loop feeds one resource watcher per distinct setting, from the
  cache entries' cpu_percent / memory_percent - a container above the
  threshold for the duration reaches the rules as one high_cpu event.

COUNTER-CHECK (2026-09-22): red before; removing the threshold match in the
engine turns the "only its own threshold" test red.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule, validate_rule_data
from services.automation.container_watch import WatchEvent


def _data(**trigger):
    base = {"type": "container_state", "states": ["high_cpu"], "cpu_threshold_percent": 80,
            "memory_threshold_percent": 90, "resource_minutes": 5}
    base.update(trigger)
    return {"id": "r", "name": "Hot", "trigger": base, "action": {"type": "NOTIFY"}}


def test_validation_and_round_trip():
    assert validate_rule_data(_data())[0]
    assert not validate_rule_data(_data(cpu_threshold_percent=150))[0]
    assert not validate_rule_data(_data(resource_minutes=0))[0]
    again = AutoActionRule.from_dict(AutoActionRule.from_dict(_data(states=["high_memory"])).to_dict())
    assert again.trigger.states == ["high_memory"]
    assert (again.trigger.cpu_threshold_percent, again.trigger.memory_threshold_percent,
            again.trigger.resource_minutes) == (80, 90, 5)


@pytest.mark.asyncio
async def test_an_event_reaches_only_the_rule_with_its_own_threshold():
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "global_cooldown_seconds": 0}
    rules = [AutoActionRule.from_dict({**_data(), "id": "eighty", "name": "eighty"}),
             AutoActionRule.from_dict({**_data(cpu_threshold_percent=95), "id": "ninety5", "name": "ninety5"})]
    service.config_service.get_rules.return_value = rules
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    service._send_feedback = AsyncMock()
    event = WatchEvent("web", "high_cpu", "hot", threshold=80, window_minutes=5)
    assert await service.process_container_events([event], bot=object(), control_channel_id=1) == ["eighty"]


@pytest.mark.asyncio
async def test_the_status_loop_turns_sustained_cpu_into_one_event(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    rules = [AutoActionRule.from_dict(_data(resource_minutes=1))]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)
    clock = iter([0, 30, 61, 90])
    monkeypatch.setattr(loops.time, "time", lambda: next(clock))

    def hot(cpu):
        return {"web": SimpleNamespace(success=True, not_found=False, is_running=True, health=None,
                                       restart_count=0, cpu_percent=cpu, memory_percent=10.0)}

    for cpu in (90.0, 91.0, 93.0, 95.0):
        await cog._feed_container_watchdog(hot(cpu), {})
    events = [e for call in engine.process_container_events.await_args_list for e in call.args[0]]
    assert [(e.container, e.kind, e.threshold) for e in events] == [("web", "high_cpu", 80)]
