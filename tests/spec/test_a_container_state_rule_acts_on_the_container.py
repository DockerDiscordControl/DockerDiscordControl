# -*- coding: utf-8 -*-
"""Container-state rules: the second trigger type of the auto-action system (Phase 4a, part 3).

Until now every auto-action rule waited for a Discord message. The watchdog
adds rules whose trigger is a container's state (ContainerWatcher: stopped,
unhealthy, restart_loop). Operator decision 2026-09-22: the notice goes to the
control channel by default, another channel can be chosen per rule.

What holds, checked below:
* a rule without trigger.type is a message rule, exactly as before, and keeps
  requiring channels and keywords;
* a container_state rule needs neither, but a valid set of states;
* it survives the save round trip (from_dict / to_dict);
* it never fires on a Discord message;
* on an event it matches, NOTIFY sends one notice naming container, reason and
  rule - to the control channel unless the rule names another one;
* RESTART acts on the container the event is about, even though a stopped
  container is "not running" (only_if_running would otherwise block exactly
  the case the rule exists for); a second event inside the cooldown does not;
* a protected container is not touched;
* events of other kinds or other containers do nothing.

COUNTER-CHECK (2026-09-22): written before the trigger type existed (red).
Removing the per-rule container filter turns "other containers do nothing"
red; removing the type check from the message pre-filter turns "never fires on
a message" red (that rule carries a keyword for exactly this reason).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.automation.auto_action_config_service import AutoActionRule, validate_rule_data
from services.automation.container_watch import WatchEvent

CONTROL = "111111111111111111"
OTHER = "222222222222222222"


def _rule(**overrides):
    data = {
        "id": "r1", "name": "Watch web", "enabled": True, "priority": 10,
        "trigger": {"type": "container_state", "states": ["stopped"], "containers": ["web"]},
        "action": {"type": "NOTIFY", "containers": []},
        "safety": {"cooldown_minutes": 30},
    }
    for key, value in overrides.items():
        data[key] = {**data[key], **value} if isinstance(value, dict) else value
    return data


def _valid(data):
    ok, error, _warnings = validate_rule_data(data)
    return ok, error


def test_a_rule_without_a_type_is_still_a_message_rule():
    rule = AutoActionRule.from_dict({"name": "old", "trigger": {"channel_ids": [CONTROL], "keywords": ["x"]},
                                     "action": {"type": "NOTIFY"}})
    assert rule.trigger.type == "message"
    ok, error = _valid({"name": "old", "trigger": {"keywords": ["x"]}, "action": {"type": "NOTIFY"}})
    assert not ok and "channel" in error.lower()


def test_a_container_state_rule_needs_states_not_channels():
    assert _valid(_rule()) == (True, "")
    ok, error = _valid(_rule(trigger={"states": []}))
    assert not ok and "state" in error.lower()
    ok, error = _valid(_rule(trigger={"states": ["exploded"]}))
    assert not ok and "exploded" in error


def test_it_survives_the_save_round_trip():
    data = _rule(trigger={"states": ["stopped", "restart_loop"], "restart_threshold": 5,
                          "restart_window_minutes": 20})
    again = AutoActionRule.from_dict(AutoActionRule.from_dict(data).to_dict())
    assert again.trigger.type == "container_state"
    assert again.trigger.states == ["stopped", "restart_loop"]
    assert (again.trigger.restart_threshold, again.trigger.restart_window_minutes) == (5, 20)
    assert again.trigger.containers == ["web"]


@pytest.fixture
def engine(monkeypatch):
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "protected_containers": ["ddc"],
                                                               "global_cooldown_seconds": 0}
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.side_effect = [(True, "", None), (False, "cooldown", "web")] * 5
    sent = []

    async def _feedback(bot, channel_id, message):
        sent.append((channel_id, message))
        return True  # delivered - since 2026-09-26 an undelivered notice falls back

    service._send_feedback = _feedback
    service._trigger_status_refresh = AsyncMock()
    action = AsyncMock(return_value=True)
    monkeypatch.setattr(mod, "docker_action", action)
    monkeypatch.setattr(mod, "is_container_exists", AsyncMock(return_value=True))
    return service, sent, action


def _rules(service, *datas):
    service.config_service.get_rules.return_value = [AutoActionRule.from_dict(d) for d in datas]


STOPPED = WatchEvent("web", "stopped", "Container 'web' stopped (it was running).")


@pytest.mark.asyncio
async def test_notify_goes_to_the_control_channel_by_default(engine):
    service, sent, action = engine
    _rules(service, _rule())
    await service.process_container_events([STOPPED], bot=object(), control_channel_id=CONTROL)
    assert len(sent) == 1
    channel, text = sent[0]
    assert channel == CONTROL and "web" in text and "stopped" in text and "Watch web" in text
    action.assert_not_called()


@pytest.mark.asyncio
async def test_a_chosen_channel_wins(engine):
    service, sent, _ = engine
    _rules(service, _rule(action={"notification_channel_id": OTHER}))
    await service.process_container_events([STOPPED], bot=object(), control_channel_id=CONTROL)
    assert [c for c, _ in sent] == [OTHER]


@pytest.mark.asyncio
async def test_restart_acts_on_the_stopped_container_once_per_cooldown(engine):
    service, sent, action = engine
    _rules(service, _rule(action={"type": "RESTART"}))
    await service.process_container_events([STOPPED], bot=object(), control_channel_id=CONTROL)
    action.assert_awaited_once_with("web", "restart")
    await service.process_container_events([STOPPED], bot=object(), control_channel_id=CONTROL)
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_protected_container_is_not_touched(engine):
    service, sent, action = engine
    _rules(service, _rule(trigger={"containers": ["ddc"]}, action={"type": "RESTART"}))
    await service.process_container_events([WatchEvent("ddc", "stopped", "x")], bot=object(),
                                           control_channel_id=CONTROL)
    action.assert_not_called()


@pytest.mark.asyncio
async def test_other_kinds_and_other_containers_do_nothing(engine):
    service, sent, action = engine
    _rules(service, _rule())
    await service.process_container_events(
        [WatchEvent("web", "unhealthy", "x"), WatchEvent("db", "stopped", "y")],
        bot=object(), control_channel_id=CONTROL)
    assert sent == [] and not action.called


@pytest.mark.asyncio
async def test_a_container_state_rule_never_fires_on_a_message(engine):
    from services.automation.automation_service import TriggerContext

    service, sent, action = engine
    # Keywords and an action target on purpose: without keywords no message could
    # match, and without a target a wrong match would do nothing visible - either
    # way the test would pass without proving that the type keeps the rule out
    # (its first version did exactly that).
    _rules(service, _rule(trigger={"containers": [], "keywords": ["web"]},
                          action={"containers": ["web"]}))
    ctx = TriggerContext(message_id="1", channel_id=CONTROL, guild_id="9", user_id="5", username="u",
                         is_webhook=False, content="web stopped", embeds_text="")
    assert await service.process_message(ctx, bot_instance=object()) == []
    assert sent == [] and not action.called
