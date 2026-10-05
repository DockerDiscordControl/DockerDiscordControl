# -*- coding: utf-8 -*-
"""A game server nobody plays on is reported once it has been empty for its minutes.

NEW (operator, 2026-10-05): "stop Valheim when nobody was online for 30
minutes" - a watchdog trigger "no_players" with its own minutes, actions STOP
or NOTIFY. Settled with the operator the same day: an unreadable player count
counts as EMPTY; the save says so; a freshly started server gets the full
minutes; the rule must name its game servers ("all" would stop every
container that has no players because it is no game server).

THE CONTRACT:
* the watcher reports a running server once after ``minutes`` of 0 players,
  starts afresh when somebody plays, when it was down, or when DDC itself
  stopped or restarted it; never a server that is not running;
* validation: game servers must be ticked, only STOP or NOTIFY, 5-1440
  minutes; the minutes survive the save; warnings for an unreadable count
  and for a cooldown longer than the minutes;
* an event reaches only the rules with its minutes;
* the status loop turns an unreadable count on a running server into such an
  event after the minutes.

HOW THIS TEST CAN FAIL: an event too early, twice, or for a stopped server;
a rule saved without game servers or with RESTART; an unreadable count that
the loop treats as "somebody plays".

COUNTER-CHECK (2026-10-05): red with the watcher's reset on players > 0
removed, with the containers check removed, and with the loop handing None
instead of 0 for an unreadable count.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule, validate_rule_data
from services.automation.container_watch import NO_PLAYERS, EmptyServerWatcher, WatchEvent

MIN = 60


def _kinds(events):
    return [(e.container, e.kind) for e in events]


def test_the_watcher_reports_once_after_the_minutes():
    watcher = EmptyServerWatcher(30)
    assert watcher.observe({"valheim": 0}, 0) == []
    assert watcher.observe({"valheim": 0}, 29 * MIN) == []
    assert _kinds(watcher.observe({"valheim": 0}, 30 * MIN)) == [("valheim", NO_PLAYERS)]
    assert watcher.observe({"valheim": 0}, 90 * MIN) == [], "reported twice for one empty stretch"


def test_a_player_or_a_stop_starts_the_minutes_afresh():
    watcher = EmptyServerWatcher(30)
    watcher.observe({"valheim": 0}, 0)
    watcher.observe({"valheim": 1}, 20 * MIN)          # somebody played
    assert watcher.observe({"valheim": 0}, 40 * MIN) == []   # empty again from here
    assert watcher.observe({"valheim": 0}, 69 * MIN) == []
    assert _kinds(watcher.observe({"valheim": 0}, 70 * MIN)) == [("valheim", NO_PLAYERS)]
    watcher.observe({"valheim": None}, 80 * MIN)       # stopped: not running
    assert watcher.observe({"valheim": None}, 200 * MIN) == [], "a stopped server was reported"
    watcher.observe({"valheim": 0}, 210 * MIN)         # started again: full minutes
    assert watcher.observe({"valheim": 0}, 239 * MIN) == []
    assert _kinds(watcher.observe({"valheim": 0}, 240 * MIN)) == [("valheim", NO_PLAYERS)]


def test_ddcs_own_restart_starts_the_minutes_afresh():
    watcher = EmptyServerWatcher(30)
    watcher.observe({"valheim": 0}, 0)
    watcher.observe({"valheim": 0}, 25 * MIN, expected={"valheim"})   # a task restarted it
    assert watcher.observe({"valheim": 0}, 31 * MIN) == []           # empty again from here
    assert watcher.observe({"valheim": 0}, 60 * MIN) == []
    assert _kinds(watcher.observe({"valheim": 0}, 61 * MIN)) == [("valheim", NO_PLAYERS)]


def _data(**over):
    trigger = {"type": "container_state", "states": ["no_players"], "containers": ["valheim"],
               "empty_minutes": 30}
    trigger.update(over.pop("trigger", {}))
    data = {"id": "idle", "name": "Idle stop", "trigger": trigger,
            "action": {"type": over.pop("action", "STOP")}, "safety": {"cooldown_minutes": 1}}
    data.update(over)
    return data


def test_validation(monkeypatch):
    monkeypatch.setattr("services.scheduling.player_gate.query_problems", lambda name, is_group: [])
    assert validate_rule_data(_data())[0]
    assert validate_rule_data(_data(action="NOTIFY"))[0]
    assert not validate_rule_data(_data(trigger={"containers": []}))[0], "saved without game servers"
    assert not validate_rule_data(_data(action="RESTART"))[0]
    assert not validate_rule_data(_data(trigger={"empty_minutes": 4}))[0]
    assert not validate_rule_data(_data(trigger={"empty_minutes": 1441}))[0]
    again = AutoActionRule.from_dict(AutoActionRule.from_dict(_data(trigger={"empty_minutes": 45})).to_dict())
    assert again.trigger.empty_minutes == 45 and again.trigger.states == ["no_players"]


def test_the_save_warns_about_an_unreadable_count_and_a_long_cooldown(monkeypatch):
    monkeypatch.setattr("services.scheduling.player_gate.query_problems",
                        lambda name, is_group: [f"{name}: the player count is switched off"])
    ok, _error, warnings = validate_rule_data(_data(safety={"cooldown_minutes": 1440}))
    assert ok
    text = " ".join(warnings)
    assert "counts as empty" in text and "valheim" in text
    assert "cooldown of 1440 minutes" in text


@pytest.mark.asyncio
async def test_an_event_reaches_only_the_rule_with_its_minutes():
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "global_cooldown_seconds": 0}
    rules = [AutoActionRule.from_dict({**_data(action="NOTIFY"), "id": "thirty", "name": "thirty"}),
             AutoActionRule.from_dict({**_data(action="NOTIFY", trigger={"empty_minutes": 60}),
                                       "id": "sixty", "name": "sixty"})]
    service.config_service.get_rules.return_value = rules
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    service._send_feedback = AsyncMock()
    service._alert = AsyncMock()
    event = WatchEvent("valheim", NO_PLAYERS, "empty", window_minutes=30)
    assert await service.process_container_events([event], bot=object(), control_channel_id=1) == ["thirty"]


@pytest.mark.asyncio
async def test_the_status_loop_reports_an_unreadable_running_server(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    rules = [AutoActionRule.from_dict(_data(action="NOTIFY"))]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    monkeypatch.setattr(loops, "_load_watch_state", lambda: {})
    monkeypatch.setattr(loops, "_save_watch_state", lambda state: None)
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)
    ticks = [0, 15 * MIN, 31 * MIN]
    monkeypatch.setattr(loops.time, "monotonic", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])

    def poll():
        def server(players):
            return SimpleNamespace(success=True, not_found=False, is_running=True, status="running",
                                   health=None, restart_count=0, players_online=players)
        return {"valheim": server(None), "busy": server(3)}

    for _ in range(3):
        await cog._feed_container_watchdog(poll(), {})
    events = [e for call in engine.process_container_events.await_args_list for e in call.args[0]]
    assert _kinds(events) == [("valheim", NO_PLAYERS)]
