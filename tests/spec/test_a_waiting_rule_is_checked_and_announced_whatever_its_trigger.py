# -*- coding: utf-8 -*-
"""A rule that waits for an empty server is checked and announced - also for groups and the watchdog.

THE FINDING (final check before v3.1.0, 2026-09-29), two gaps in the player
options of the auto-actions:

  * Saving a rule checks whether the player count of its containers can be
    read, and says so - a count that cannot be read counts as empty. The
    check ran over the raw action list: a rule on "group:Valheim" was told
    "group:Valheim: the player count is not switched on" while its members
    were never looked at, and a watchdog rule (its action list is empty, the
    trigger names the containers) was never checked at all.
  * A message rule that waits says so when it fires ("⚡ RESTART Icarus · only
    when nobody plays (at most 120 min)"). A watchdog rule said only "🚨 … →
    RESTART" and then nothing, possibly for hours.

THE CONTRACT: the save check looks at the containers the action really waits
for - groups resolved, the watched containers of a watchdog rule; and the
watchdog's notice names the options like the message rule's does.

HOW THIS TEST CAN FAIL: the check goes back to the raw list, or the watchdog
notice loses the options.

COUNTER-CHECK (2026-09-29): with the raw list back, the group and the
watchdog save tests go red; with the gate text removed from the watchdog
notice, the notice test goes red.
"""

from types import SimpleNamespace

import pytest

from services.scheduling import player_gate


def _checked(monkeypatch):
    names = []

    def _problem(name):
        names.append(name)
        return "no player count has been read for it yet"

    monkeypatch.setattr(player_gate, "query_problem", _problem)
    return names


def _options():
    return {"wait_for_empty": True, "max_wait_minutes": 60}


def test_a_group_rule_checks_the_members(monkeypatch):
    from services.automation import automation_service
    from services.automation.auto_action_config_service import validate_rule_data

    monkeypatch.setattr(automation_service, "_members_of_group",
                        lambda group, action=None: ["valheim1", "valheim2"] if group == "Valheim" else [])
    checked = _checked(monkeypatch)
    rule = {"name": "Valheim update", "priority": 10, "enabled": True,
            "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["update"]},
            "action": {"type": "RESTART", "containers": ["group:Valheim"], "delay_seconds": 0,
                       "player_options": _options()},
            "safety": {"cooldown_minutes": 60}}

    ok, error, warnings = validate_rule_data(rule, [])

    assert ok, error
    assert checked == ["valheim1", "valheim2"], checked
    assert warnings and "group:Valheim" not in " ".join(warnings), warnings


def test_a_watchdog_rule_checks_the_watched_containers(monkeypatch):
    from services.automation.auto_action_config_service import validate_rule_data

    checked = _checked(monkeypatch)
    rule = {"name": "Icarus unhealthy", "priority": 10, "enabled": True,
            "trigger": {"type": "container_state", "states": ["unhealthy"], "containers": ["Icarus"]},
            "action": {"type": "RESTART", "containers": [], "delay_seconds": 0,
                       "player_options": _options()},
            "safety": {"cooldown_minutes": 60}}

    ok, error, warnings = validate_rule_data(rule, [])

    assert ok, error
    assert checked == ["Icarus"], checked
    assert any("player count cannot be read" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_a_waiting_watchdog_rule_says_so_when_it_fires(monkeypatch):
    from services.automation import automation_service as module
    from services.automation.auto_action_config_service import AutoActionRule

    alerts = []

    async def _docker(name, action):
        return True

    monkeypatch.setattr(module, "docker_action", _docker)
    service = module.AutomationService()
    service.state_service = SimpleNamespace(
        record_trigger=lambda *a, **k: None, release_execution_lock=lambda *a, **k: None,
        release_rule_cooldown=lambda *a, **k: None)
    service.config_service = SimpleNamespace(increment_trigger_count=lambda *a: None)

    async def _alert(bot, channels, event, text):
        alerts.append(text)
        return True

    async def _refresh(*_args):
        return None

    service._alert = _alert
    service._trigger_status_refresh = _refresh
    rule = AutoActionRule.from_dict({
        "id": "w1", "name": "Icarus unhealthy", "enabled": True,
        "trigger": {"type": "container_state", "states": ["unhealthy"], "containers": ["Icarus"]},
        "action": {"type": "RESTART", "containers": [],
                   "player_options": {"wait_for_empty": True, "max_wait_minutes": 120}}})
    event = SimpleNamespace(reason="Icarus is unhealthy", kind="unhealthy")

    await service._act_on_container(rule, event, "RESTART", "Icarus", object(), [1])

    assert alerts and "only when nobody plays (at most 120 min)" in alerts[0], alerts
