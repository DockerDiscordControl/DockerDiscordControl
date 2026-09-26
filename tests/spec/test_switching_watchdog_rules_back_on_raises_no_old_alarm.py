# -*- coding: utf-8 -*-
"""Switching the watchdog's rules back on raises no alarm about the past.

THE FINDING (audit 2026-09-26, F6). With no enabled container-state rule the
status loop returned before it looked at anything - and kept the watchers it
had. The operator switches the rule off, stops the container for maintenance,
switches the rule back on: the first poll compared "stopped" with the
running state remembered from days ago and reported a stop nobody needed to
hear about - and a RESTART rule restarted the container in maintenance. The
restart-loop and resource watchers kept their old counts the same way.

THE CONTRACT: while no rule watches, nothing is remembered; the first poll
after the rules come back is a fresh baseline.

COUNTER-CHECK (2026-09-26): red before the fix - one "stopped" event on the
first poll after the rule came back.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule

RULE = AutoActionRule.from_dict({
    "id": "r", "name": "Watch", "enabled": True,
    "trigger": {"type": "container_state", "states": ["stopped"]},
    "action": {"type": "NOTIFY"}})


def _state(running):
    return {"web": SimpleNamespace(success=True, not_found=False, is_running=running, status=None,
                                   health=None, restart_count=0, cpu_percent=None,
                                   memory_percent=None)}


@pytest.mark.asyncio
async def test_no_alarm_about_a_stop_made_while_nothing_watched(monkeypatch):
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    rules = [RULE]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: list(rules)))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)

    await cog._feed_container_watchdog(_state(True), {})    # watched: running
    rules.clear()
    await cog._feed_container_watchdog(_state(False), {})   # rule off, maintenance stop
    rules.append(RULE)
    await cog._feed_container_watchdog(_state(False), {})   # rule back on

    engine.process_container_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stop_while_watched_is_still_reported(monkeypatch):
    """Counter-case: forgetting must not start before the rules go."""
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: [RULE]))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)

    await cog._feed_container_watchdog(_state(True), {})
    await cog._feed_container_watchdog(_state(False), {})

    engine.process_container_events.assert_awaited_once()
