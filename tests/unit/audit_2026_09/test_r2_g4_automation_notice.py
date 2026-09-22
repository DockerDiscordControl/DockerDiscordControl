# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""
Audit 2026-09, review round 2, package G4 - Auto-Actions.

R4-3  only_if_running stays enforced, but a rule skipped for that reason now posts ONE
      short Discord notice per rule trigger (same channel + silent handling as the other
      auto-action feedback messages) instead of being visible only in the history.
"""

from pathlib import Path
from threading import Lock
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import automation_service as auto_mod
from services.automation.auto_action_config_service import AutoActionConfigService
from services.automation.auto_action_state_service import AutoActionStateService
from services.automation.automation_service import AutomationService, TriggerContext

CHANNEL_ID = "123456789012345678"
NOTIFY_CHANNEL_ID = "876543210987654321"
RULE_NAME = "Icarus Update Watcher"
SKIP_MARKER = "⏭️"


@pytest.fixture
def config_service(tmp_path: Path) -> AutoActionConfigService:
    (tmp_path / "config").mkdir(exist_ok=True)
    svc = AutoActionConfigService.__new__(AutoActionConfigService)
    svc.base_dir = tmp_path
    svc.config_file = tmp_path / "config" / "auto_actions.json"
    svc._ensure_config_exists()
    return svc


@pytest.fixture
def state_service(tmp_path: Path) -> AutoActionStateService:
    (tmp_path / "config").mkdir(exist_ok=True)
    svc = AutoActionStateService.__new__(AutoActionStateService)
    svc.base_dir = tmp_path
    svc.state_file = tmp_path / "config" / "auto_actions_state.json"
    svc._lock = Lock()
    svc.global_last_triggered = 0.0
    svc.rule_cooldowns = {}
    svc.container_cooldowns = {}
    svc.trigger_history = {}
    return svc


@pytest.fixture
def automation(monkeypatch, config_service, state_service) -> AutomationService:
    monkeypatch.setattr(auto_mod, "get_auto_action_config_service", lambda: config_service)
    monkeypatch.setattr(auto_mod, "get_auto_action_state_service", lambda: state_service)
    monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
    return AutomationService()


@pytest.fixture
def docker_action(monkeypatch) -> AsyncMock:
    action = AsyncMock(return_value=True)
    monkeypatch.setattr(auto_mod, "docker_action", action)
    return action


class FakeBot:
    """bot.get_channel(id) -> channel whose send() is recorded per channel id."""

    def __init__(self):
        self.channels = {}

    def get_channel(self, channel_id):
        if channel_id not in self.channels:
            channel = MagicMock()
            channel.send = AsyncMock()
            self.channels[channel_id] = channel
        return self.channels[channel_id]

    def get_cog(self, _name):
        return None  # no status refresh in these tests

    def sent(self, channel_id):
        channel = self.channels.get(int(channel_id))
        return [c.args[0] for c in channel.send.await_args_list] if channel else []


def _running_states(monkeypatch, states):
    monkeypatch.setattr(auto_mod, "get_docker_info",
                        AsyncMock(side_effect=lambda name: {"State": {"Running": states[name]}}))


def _rule(containers, action="RESTART", silent=False, notification_channel_id=None):
    return {
        "name": RULE_NAME,
        "enabled": True,
        "priority": 10,
        "trigger": {
            "channel_ids": [CHANNEL_ID],
            "keywords": ["update"],
            "required_keywords": [],
            "ignore_keywords": [],
            "match_mode": "any",
            "regex_pattern": None,
            "search_in": ["content", "embeds"],
            "source_filter": {"allowed_user_ids": [], "allowed_usernames": [], "is_webhook": None},
        },
        "action": {
            "type": action,
            "containers": containers,
            "delay_seconds": 0,
            "notification_channel_id": notification_channel_id,
            "silent": silent,
        },
        "safety": {"cooldown_minutes": 1440, "only_if_running": True},
    }


def _ctx():
    return TriggerContext(
        message_id="1", channel_id=CHANNEL_ID, guild_id="2", user_id="3",
        username="watcher", is_webhook=False, content="Server update available", embeds_text="",
    )


def _skip_notices(bot, channel_id=CHANNEL_ID):
    return [m for m in bot.sent(channel_id) if SKIP_MARKER in m]


class TestOnlyIfRunningNotice:

    async def test_skipped_rule_posts_one_notice_in_trigger_channel(self, automation, config_service,
                                                                     state_service, docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus"])).success
        _running_states(monkeypatch, {"Icarus": False})
        bot = FakeBot()

        assert await automation.process_message(_ctx(), bot) == []

        docker_action.assert_not_awaited()
        notices = _skip_notices(bot)
        assert len(notices) == 1
        assert RULE_NAME in notices[0] and "`Icarus`" in notices[0]
        assert "only if running" in notices[0]
        # Enforcement and history unchanged
        assert [e["result"] for e in state_service.get_history()] == ["SKIPPED"]

    async def test_multi_container_rule_posts_a_single_notice(self, automation, config_service,
                                                              docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus", "Icarus2"])).success
        _running_states(monkeypatch, {"Icarus": False, "Icarus2": False})
        bot = FakeBot()

        await automation.process_message(_ctx(), bot)

        notices = _skip_notices(bot)
        assert len(notices) == 1
        assert "`Icarus`" in notices[0] and "`Icarus2`" in notices[0]

    async def test_partially_skipped_rule_names_only_the_stopped_target(self, automation, config_service,
                                                                        docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus", "Icarus2"])).success
        _running_states(monkeypatch, {"Icarus": True, "Icarus2": False})
        bot = FakeBot()

        assert await automation.process_message(_ctx(), bot) == [RULE_NAME]

        docker_action.assert_awaited_once_with("Icarus", "restart")
        notices = _skip_notices(bot)
        assert len(notices) == 1
        assert "`Icarus2`" in notices[0] and "`Icarus`," not in notices[0]

    async def test_silent_rule_posts_nothing(self, automation, config_service, docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus"], silent=True)).success
        _running_states(monkeypatch, {"Icarus": False})
        bot = FakeBot()

        await automation.process_message(_ctx(), bot)

        assert bot.channels == {}

    async def test_notice_goes_to_configured_notification_channel(self, automation, config_service,
                                                                  docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus"], notification_channel_id=NOTIFY_CHANNEL_ID)).success
        _running_states(monkeypatch, {"Icarus": False})
        bot = FakeBot()

        await automation.process_message(_ctx(), bot)

        assert len(_skip_notices(bot, NOTIFY_CHANNEL_ID)) == 1
        assert _skip_notices(bot, CHANNEL_ID) == []

    async def test_running_container_gets_no_skip_notice(self, automation, config_service,
                                                         docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus"])).success
        _running_states(monkeypatch, {"Icarus": True})
        bot = FakeBot()

        assert await automation.process_message(_ctx(), bot) == [RULE_NAME]

        assert _skip_notices(bot) == []
        assert any("RESTART" in m for m in bot.sent(CHANNEL_ID))  # normal ⚡ feedback unchanged

    async def test_without_bot_nothing_breaks(self, automation, config_service, docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["Icarus"])).success
        _running_states(monkeypatch, {"Icarus": False})

        assert await automation.process_message(_ctx()) == []

    def test_broken_translation_falls_back_to_english(self, monkeypatch):
        monkeypatch.setattr(auto_mod, "_", lambda text: "{kaputt} {rule}")

        notice = AutomationService._only_if_running_notice("Rule", ["a", "b"])

        assert notice.startswith(SKIP_MARKER)
        assert "'Rule'" in notice and "`a`, `b`" in notice
