# -*- coding: utf-8 -*-
"""The watchdog measures durations with a clock that cannot be set backwards.

THE FINDING: every duration the watchdog works with - the restart-loop
window, "above the threshold for N minutes", the six hours between image
checks - was measured with time.time(), the wall clock. An NTP correction, or
a host whose clock is set at boot, moves it. A step BACK makes `now - since`
negative, so a container that has been hot for ten minutes is reported only
after the step has been made up; a step FORWARD can satisfy "five minutes" on
a single sample and report a container that was hot for one poll.

Durations are now measured with time.monotonic(), which only ever moves
forward. The wall clock keeps the jobs it is for: log lines and timestamps.

COUNTER-CHECK (2026-09-22): red before - with the wall clock jumping forward
by an hour between two polls, one sample produced a high_cpu event.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule


@pytest.fixture
def world(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    rules = [AutoActionRule.from_dict({
        "id": "r", "name": "hot", "trigger": {"type": "container_state", "states": ["high_cpu"],
                                              "cpu_threshold_percent": 80, "resource_minutes": 5},
        "action": {"type": "NOTIFY"}})]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)

    wall = {"t": 1_700_000_000.0}
    steady = {"t": 0.0}
    monkeypatch.setattr(loops.time, "time", lambda: wall["t"])
    monkeypatch.setattr(loops.time, "monotonic", lambda: steady["t"])
    return SimpleNamespace(cog=cog, engine=engine, wall=wall, steady=steady)


def _hot(cpu=95.0):
    return {"web": SimpleNamespace(success=True, not_found=False, is_running=True, health=None,
                                   restart_count=0, cpu_percent=cpu, memory_percent=5.0)}


def _events(world):
    return [e for call in world.engine.process_container_events.await_args_list for e in call.args[0]]


@pytest.mark.asyncio
async def test_a_wall_clock_jump_forward_reports_nothing(world):
    await world.cog._feed_container_watchdog(_hot(), {})
    world.wall["t"] += 3600          # NTP sets the clock an hour ahead
    world.steady["t"] += 30          # half a minute really passed
    await world.cog._feed_container_watchdog(_hot(), {})

    assert _events(world) == [], (
        "a container hot for 30 seconds was reported as hot for five minutes")


@pytest.mark.asyncio
async def test_a_wall_clock_jump_backwards_does_not_delay_the_report(world):
    await world.cog._feed_container_watchdog(_hot(), {})
    world.wall["t"] -= 7200          # and an hour back again
    world.steady["t"] += 301
    await world.cog._feed_container_watchdog(_hot(), {})

    assert [(e.container, e.kind) for e in _events(world)] == [("web", "high_cpu")], (
        "the report waited for the wall clock to catch up")


@pytest.mark.asyncio
async def test_the_ordinary_case_still_reports(world):
    """Counter-check: a container hot for the whole duration is still reported."""
    await world.cog._feed_container_watchdog(_hot(), {})
    world.wall["t"] += 301
    world.steady["t"] += 301
    await world.cog._feed_container_watchdog(_hot(), {})

    assert len(_events(world)) == 1
