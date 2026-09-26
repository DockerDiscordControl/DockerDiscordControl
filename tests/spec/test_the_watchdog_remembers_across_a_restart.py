# -*- coding: utf-8 -*-
"""The watchdog remembers the containers across a DDC restart.

THE FINDING (audit 2026-09-26, F11). Every start began with a silent baseline:
the watchers lived in memory only. A container that went down while DDC was
offline - during a rebuild (60-90 s), a host reboot, a crash of DDC itself -
or that did not come back up after the reboot, was simply taken as "stopped"
from the first poll on and never reported. Those are the watchdog's main
cases.

OPERATOR DECISION (2026-09-26): save the state. The last known state of each
container is kept in config/watchdog_state.json; after a start, a container
that was running then and is stopped now is reported once, saying it happened
while DDC was offline. While no rule watches, nothing is kept (see
test_switching_watchdog_rules_back_on_raises_no_old_alarm.py).

COUNTER-CHECK (2026-09-26): red before the fix - the second cog's first poll
produced no event.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import ContainerState, ContainerWatcher

RULE = AutoActionRule.from_dict({
    "id": "r", "name": "Watch", "enabled": True,
    "trigger": {"type": "container_state", "states": ["stopped"]},
    "action": {"type": "NOTIFY"}})


def _state(running):
    return {"web": SimpleNamespace(success=True, not_found=False, is_running=running, status=None,
                                   health=None, restart_count=0, cpu_percent=None,
                                   memory_percent=None)}


def _cog(monkeypatch, rules):
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: list(rules)))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)
    return cog, engine


@pytest.mark.asyncio
async def test_a_stop_while_ddc_was_down_is_reported_after_the_start(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    before, _ = _cog(monkeypatch, [RULE])
    await before._feed_container_watchdog(_state(True), {})     # running, then DDC goes down

    after, engine = _cog(monkeypatch, [RULE])                    # a new process
    await after._feed_container_watchdog(_state(False), {})

    events = [e for call in engine.process_container_events.await_args_list for e in call.args[0]]
    assert [(e.container, e.kind) for e in events] == [("web", "stopped")]
    assert "offline" in events[0].reason, events[0].reason


@pytest.mark.asyncio
async def test_it_is_reported_once(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    before, _ = _cog(monkeypatch, [RULE])
    await before._feed_container_watchdog(_state(True), {})
    after, engine = _cog(monkeypatch, [RULE])
    await after._feed_container_watchdog(_state(False), {})
    await after._feed_container_watchdog(_state(False), {})

    assert engine.process_container_events.await_count == 1


@pytest.mark.asyncio
async def test_nothing_is_kept_while_no_rule_watches(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    rules = [RULE]
    cog, _ = _cog(monkeypatch, rules)
    await cog._feed_container_watchdog(_state(True), {})
    rules.clear()
    await cog._feed_container_watchdog(_state(True), {})

    assert not (tmp_path / "watchdog_state.json").exists()


def test_a_restored_state_is_not_an_alarm_when_nothing_changed():
    """Counter-case: running before, running now - silence."""
    watcher = ContainerWatcher()
    watcher.restore({"web": {"running": True, "health": None}})

    assert watcher.observe({"web": ContainerState(True, None)}, 0.0) == []
