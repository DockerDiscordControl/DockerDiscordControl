# -*- coding: utf-8 -*-
"""The player options hold on every way in: auto-actions, rules, the panel, Discord.

Companion of test_a_task_waits_until_nobody_plays.py (the scheduler). Here:

* AUTO-ACTIONS are triggered NOW: "warn 10 minutes before" means warn now and
  act 10 minutes later; with wait_for_empty they act the moment the servers are
  empty or at the end of the wait (player_gate.hold_until_empty), and both
  execution paths of automation_service call it before touching a container.
* The warning reaches the status AND the control channels, each once.
* SAVING says what it will not do: a rule or a task that waits for an empty
  server whose player count cannot be read is saved WITH a warning (operator,
  2026-09-28: such a server counts as empty) - and options that make no sense
  are refused with our own sentence, not "Failed to add task".
* DISCORD: the dropdowns under a new task merge into its options and go
  through the same check.

COUNTER-CHECK (2026-09-28): with hold_until_empty returning at once, the three
timing cases went red; with the status channels left out of
warning_channel_ids, the channel case did; with the query-problem warning
removed from validate_rule_data, the rule-warning case did.
"""

import asyncio
import re
from pathlib import Path

import pytest

from services.scheduling import player_gate

ROOT = Path(__file__).resolve().parents[2]


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


def _run_hold(monkeypatch, options, players):
    """Run hold_until_empty; players is a function of the elapsed seconds."""
    clock = _Clock()
    start = clock.now
    posted = []

    async def _post(bot, text):
        posted.append((clock.now - start, text))
        return 1
    monkeypatch.setattr(player_gate, "post_warning", _post)
    monkeypatch.setattr(player_gate, "players_online", lambda name: players(clock.now - start))
    asyncio.run(player_gate.hold_until_empty(options, ["Valheim"], "restart", "Valheim", bot=None,
                                             clock=clock.time, sleep=clock.sleep))
    return clock.now - start, posted


def test_an_auto_action_warns_now_and_acts_after_the_warning(monkeypatch):
    waited, posted = _run_hold(monkeypatch, {"warn_minutes": 10}, lambda t: 4)
    assert waited == 600
    assert len(posted) == 1 and posted[0][0] == 0 and "10" in posted[0][1]


def test_an_auto_action_acts_the_moment_the_server_empties(monkeypatch):
    options = {"wait_for_empty": True, "max_wait_minutes": 120}
    waited, posted = _run_hold(monkeypatch, options, lambda t: 2 if t < 1800 else 0)
    assert 1800 <= waited < 1800 + 61 and posted == []


def test_an_auto_action_acts_at_the_end_of_the_wait_warned_before(monkeypatch):
    options = {"wait_for_empty": True, "max_wait_minutes": 60, "warn_minutes": 10}
    waited, posted = _run_hold(monkeypatch, options, lambda t: 3)
    assert waited == 3600
    assert len(posted) == 1 and 3000 <= posted[0][0] < 3600


def test_both_auto_action_paths_wait_before_they_act():
    source = (ROOT / "services" / "automation" / "automation_service.py").read_text(encoding="utf-8")
    assert source.count("player_gate.hold_until_empty(") == 2, \
        "an auto-action path acts without asking for an empty server"


def test_the_warning_goes_to_status_and_control_channels_once():
    config = {"channel_permissions": {
        "1": {"commands": {"serverstatus": True}},
        "2": {"commands": {"control": True}},
        "3": {"commands": {"serverstatus": True, "control": True}},
        "4": {"commands": {"schedule": True}},
    }}
    assert sorted(player_gate.warning_channel_ids(config)) == [1, 2, 3]


def test_a_rule_with_bad_options_is_refused_and_an_unreadable_count_is_said(monkeypatch):
    from services.automation.auto_action_config_service import validate_rule_data
    rule = {"name": "Valheim update", "priority": 10, "enabled": True,
            "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["update"]},
            "action": {"type": "RESTART", "containers": ["Valheim"], "delay_seconds": 0,
                       "player_options": {"wait_for_empty": True, "max_wait_minutes": 60}},
            "safety": {"cooldown_minutes": 60}}
    monkeypatch.setattr(player_gate, "query_problem", lambda name: "no player count has been read for it yet")
    ok, error, warnings = validate_rule_data(rule, [])
    assert ok, error
    assert any("player count cannot be read" in w for w in warnings), warnings

    rule["action"]["player_options"] = {"warn_minutes": 5}
    rule["action"]["type"] = "START"
    ok, error, _ = validate_rule_data(rule, [])
    assert not ok and "restart and stop" in error


def test_a_task_refusal_is_shown_in_our_words(monkeypatch):
    """Through the real route: a warning on a START is refused with our sentence."""
    from flask import Flask
    import app.auth as auth_module
    from app.blueprints.tasks_bp import tasks_bp
    monkeypatch.setattr(auth_module, "session_user", lambda: "admin")
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(tasks_bp)
    answer = app.test_client().post("/tasks/add", json={
        "container": "Valheim", "action": "start", "cycle": "daily",
        "schedule_details": {"time": "04:00", "options": {"warn_minutes": 5}}})
    assert answer.status_code == 400
    assert "restart and stop" in answer.get_json()["error"], "the panel hides the reason"


def test_the_panel_task_checks_and_warns(monkeypatch):
    from app.blueprints.tasks_bp import _player_warnings, _refused_player_options
    data = {"action": "restart", "schedule_details": {"time": "04:00", "options": {"wait_for_empty": True}}}
    assert _refused_player_options(data) is None
    assert data["schedule_details"]["options"] == {"wait_for_empty": True, "max_wait_minutes": 120}
    monkeypatch.setattr(player_gate, "query_problem", lambda name: "switched off")
    warnings = _player_warnings({"container": "Valheim", "target_is_group": False,
                                 "schedule_details": data["schedule_details"]})
    assert warnings and "Valheim: switched off" in warnings[0]


def test_discord_dropdowns_merge_and_check(monkeypatch):
    from cogs import task_player_options as view
    from services.scheduling import scheduler as scheduler_mod
    from services.scheduling.scheduler import ScheduledTask, CYCLE_DAILY
    task = ScheduledTask(task_id="t", container_name="Valheim", action="restart", cycle=CYCLE_DAILY,
                         hour=4, minute=0, timezone_str="UTC")
    task.options = {"warn_minutes": 10}
    saved = []
    monkeypatch.setattr(scheduler_mod, "find_task_by_id", lambda task_id: task)
    monkeypatch.setattr(scheduler_mod, "update_task", lambda t, check_collision=True: saved.append(dict(t.options)) or True)
    monkeypatch.setattr(player_gate, "query_problem", lambda name: None)

    result, error, warnings = view._save("t", {"wait_for_empty": True, "max_wait_minutes": 60})
    assert error is None and warnings == []
    assert saved[-1] == {"wait_for_empty": True, "max_wait_minutes": 60, "warn_minutes": 10}

    view._save("t", {"wait_for_empty": False})
    assert saved[-1] == {"warn_minutes": 10}, "switching the wait off left its minutes behind"


@pytest.mark.parametrize("path", ["app/templates/tasks/form.html", "app/templates/tasks/_edit_modal.html",
                                  "app/templates/_auto_actions_modal.html"])
def test_every_form_offers_the_options(path):
    html = (ROOT / path).read_text(encoding="utf-8")
    prefix = re.search(r'id="(\w+)PlayerGate"', html)
    assert prefix, f"{path} has no player options"
    for field in ("WaitEmpty", "MaxWait", "WarnMinutes"):
        assert f'id="{prefix.group(1)}{field}"' in html, (path, field)
