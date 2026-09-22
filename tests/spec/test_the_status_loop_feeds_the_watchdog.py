# -*- coding: utf-8 -*-
"""The status loop feeds the container watchdog (Phase 4a, part 4).

Parts 1-3 built the watcher, the data and the rules - none of which does
anything unless the status loop, the one place that polls every container,
hands its results on. This checks the call site, not the parts: two real
cycles of status_update_loop with a container that goes from running to
exited must reach the automation service as one "stopped" event, with the
control channel from the configuration as default notice channel.

Also here: a rule's own restart threshold and window. Two rules with
different ones each get the restart_loop events of their own watcher, not the
other's.

COUNTER-CHECK (2026-09-22): red before the loop fed anything; removing the
"pending action = expected" line makes the DDC-initiated stop test red.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent


def _result(running, restarts=0):
    return SimpleNamespace(success=True, not_found=False, is_running=running, health=None,
                           restart_count=restarts, error_message=None)


def _rule(rule_id, states, threshold=3, window=10):
    return AutoActionRule.from_dict({
        "id": rule_id, "name": rule_id, "trigger": {"type": "container_state", "states": states,
                                                   "restart_threshold": threshold,
                                                   "restart_window_minutes": window},
        "action": {"type": "NOTIFY"}})


@pytest.fixture
def cog(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.cache_ttl_seconds = 75
    cog.status_refresh_interval_seconds = 30
    cog.status_cache_service = MagicMock()
    cog._mark_status_cache_refreshed = MagicMock()
    cog.pending_actions = {}
    cog.results = [{"web": _result(True)}, {"web": _result(False)}]
    cog.bulk_fetch_container_status = AsyncMock(side_effect=lambda names: cog.results.pop(0))

    config = {"channel_permissions": {"999": {"commands": {"control": True}}}}
    monkeypatch.setattr(loops, "load_config", lambda: config)
    monkeypatch.setattr(loops, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [{"docker_name": "web"}]))
    monkeypatch.setattr("utils.settings.get_setting", lambda key, default=None: 30)
    monkeypatch.setattr(type(cog).status_update_loop, "change_interval", lambda **kw: None, raising=False)

    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)
    rules = [_rule("r1", ["stopped"])]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    return cog, engine


async def _two_cycles(cog):
    await cog.status_update_loop.coro(cog)
    await cog.status_update_loop.coro(cog)


def _events(engine):
    return [e for call in engine.process_container_events.await_args_list for e in call.args[0]]


@pytest.mark.asyncio
async def test_a_container_that_stops_reaches_the_rules(cog):
    cog, engine = cog
    await _two_cycles(cog)
    events = _events(engine)
    assert [(e.container, e.kind) for e in events] == [("web", "stopped")]
    last = engine.process_container_events.await_args_list[-1]
    assert last.kwargs["control_channel_id"] == 999


@pytest.mark.asyncio
async def test_a_stop_ddc_is_doing_itself_is_not_an_event(cog):
    cog, engine = cog
    await cog.status_update_loop.coro(cog)
    cog.pending_actions = {"web": {"action": "stop"}}
    await cog.status_update_loop.coro(cog)
    assert _events(engine) == []


@pytest.mark.asyncio
async def test_each_rule_gets_restart_loops_by_its_own_threshold():
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "global_cooldown_seconds": 0}
    service.config_service.get_rules.return_value = [_rule("fast", ["restart_loop"], 3, 10),
                                                     _rule("slow", ["restart_loop"], 5, 30)]
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    service._send_feedback = AsyncMock()
    event = WatchEvent("web", "restart_loop", "x", threshold=3, window_minutes=10)
    assert await service.process_container_events([event], bot=object(), control_channel_id=1) == ["fast"]
