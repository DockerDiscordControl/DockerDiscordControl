# -*- coding: utf-8 -*-
"""Watchers for settings no rule uses any more are dropped (Phase 4b).

THE FINDING: the status loop keeps one watcher per distinct setting in a dict
on the cog, keyed by (threshold, window) or (metric, threshold, minutes), and
never removed one. Every time the operator changes a threshold in the panel a
new watcher is added and the old one stays for the life of the process, each
with its own per-container bookkeeping.

The second half is worse than the memory: a watcher that comes back - the
operator sets 90, then 80, then 90 again - still carries `_alerted` from its
first life, so a container that has been hot the whole time is never reported
again. A setting nobody uses is now forgotten, and a setting that returns
starts fresh.

COUNTER-CHECK (2026-09-22): red before - the watcher dict kept growing with
every threshold, and the returning setting reported nothing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule


def _rule(threshold):
    return AutoActionRule.from_dict({
        "id": f"r{threshold}", "name": f"hot {threshold}",
        "trigger": {"type": "container_state", "states": ["high_cpu"],
                    "cpu_threshold_percent": threshold, "resource_minutes": 1},
        "action": {"type": "NOTIFY"}})


@pytest.fixture
def world(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    rules = [_rule(80)]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)
    clock = {"t": 0.0}
    # The loop measures durations with time.monotonic() now (a wall-clock
    # correction must not delay or fake a report), so the stand-in clock is that one.
    monkeypatch.setattr(loops.time, "monotonic", lambda: clock["t"])
    return SimpleNamespace(cog=cog, rules=rules, engine=engine, clock=clock)


def _hot(cpu=95.0):
    return {"web": SimpleNamespace(success=True, not_found=False, is_running=True, health=None,
                                   restart_count=0, cpu_percent=cpu, memory_percent=5.0)}


async def _poll(world, seconds):
    world.clock["t"] += seconds
    await world.cog._feed_container_watchdog(_hot(), {})


def _events(world):
    return [e for call in world.engine.process_container_events.await_args_list for e in call.args[0]]


@pytest.mark.asyncio
async def test_a_threshold_nobody_uses_is_forgotten(world):
    await _poll(world, 0)
    for threshold in (85, 90, 95):
        world.rules[:] = [_rule(threshold)]
        await _poll(world, 30)

    watchers = world.cog._container_watchers
    keys = [key for key in watchers if key != 'base']
    assert len(keys) == 1, f"{len(keys)} watchers for one rule: {keys}"


@pytest.mark.asyncio
async def test_a_threshold_that_comes_back_starts_fresh(world):
    await _poll(world, 0)
    await _poll(world, 61)                     # reported at 80
    assert len(_events(world)) == 1

    world.rules[:] = [_rule(90)]               # operator changes it
    await _poll(world, 30)
    world.rules[:] = [_rule(80)]               # and back again
    await _poll(world, 30)
    await _poll(world, 61)

    assert len(_events(world)) == 2, (
        "the returning setting kept its old 'already reported' memory, so a container "
        "that has been hot the whole time was never reported again")


@pytest.mark.asyncio
async def test_an_unchanged_setting_keeps_its_watcher(world):
    """Counter-check: dropping the watcher every poll would restart the timer
    for ever, and nothing would ever be reported."""
    await _poll(world, 0)
    await _poll(world, 30)
    await _poll(world, 31)

    assert len(_events(world)) == 1
