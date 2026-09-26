# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""
Audit 2026-09, package C1 - Auto-Actions.

Regression tests for:
    C1-2  multi-container rules: global cooldown checked once, all cooldowns set in one
          locked operation, nothing stays locked when the rule is blocked
          (live case: "Icarus Update Watcher" on [alpha, beta] never executed)
    C1-5  the ReDoS check no longer rejects ordinary regex triggers
    C1-6  the rule option only_if_running is enforced before acting
"""

import time
from pathlib import Path
from threading import Lock
from unittest.mock import AsyncMock

import pytest

from services.automation import automation_service as auto_mod
from services.automation.auto_action_config_service import (
    AutoActionConfigService,
    validate_regex_pattern,
    validate_rule_data,
)
from services.automation.auto_action_state_service import AutoActionStateService
from services.automation.automation_service import AutomationService, TriggerContext

CHANNEL_ID = "123456789012345678"
RULE_NAME = "Icarus Update Watcher"


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


def _running_states(monkeypatch, states):
    """Patch get_docker_info so each container reports the given running state."""
    info = AsyncMock(side_effect=lambda name: {"State": {"Running": states[name]}})
    monkeypatch.setattr(auto_mod, "get_docker_info", info)
    return info


def _rule(containers, action="RESTART", only_if_running=True, regex=None):
    return {
        "name": RULE_NAME,
        "enabled": True,
        "priority": 10,
        "trigger": {
            "channel_ids": [CHANNEL_ID],
            "keywords": [] if regex else ["update"],
            "required_keywords": [],
            "ignore_keywords": [],
            "match_mode": "any",
            "regex_pattern": regex,
            "search_in": ["content", "embeds"],
            "source_filter": {"allowed_user_ids": [], "allowed_usernames": [], "is_webhook": None},
        },
        "action": {
            "type": action,
            "containers": containers,
            "delay_seconds": 0,
            "notification_channel_id": None,
            "silent": True,
        },
        "safety": {"cooldown_minutes": 1440, "only_if_running": only_if_running},
    }


def _ctx(content="Server update available"):
    return TriggerContext(
        message_id="1", channel_id=CHANNEL_ID, guild_id="2", user_id="3",
        username="watcher", is_webhook=False, content=content, embeds_text="",
    )


def _results(state_service):
    return {e["container"]: (e["result"], e["details"]) for e in state_service.get_history()}


# --------------------------------------------------------------------------- #
# C1-2: multi-container cooldown locking                                       #
# --------------------------------------------------------------------------- #

class TestMultiContainerLocks:

    def test_all_containers_locked_together(self, state_service):
        ok, reason, blocked = state_service.acquire_execution_locks("r1", ["alpha", "beta"], 30, 1440)

        assert (ok, reason, blocked) == (True, "", None)
        # keyed per rule and container since 2026-09-26
        assert state_service.container_cooldowns[state_service.cooldown_key("r1", "alpha")] > 0
        assert state_service.container_cooldowns[state_service.cooldown_key("r1", "beta")] > 0
        assert state_service.global_last_triggered > 0

    def test_blocked_container_leaves_nothing_locked(self, state_service):
        state_service.container_cooldowns[state_service.cooldown_key("r1", "beta")] = time.time()

        ok, reason, blocked = state_service.acquire_execution_locks("r1", ["alpha", "beta"], 30, 1440)

        assert ok is False and blocked == "beta"
        assert "beta" in reason
        assert state_service.cooldown_key("r1", "alpha") not in state_service.container_cooldowns
        assert state_service.global_last_triggered == 0.0
        assert "r1" not in state_service.rule_cooldowns

    def test_global_cooldown_leaves_nothing_locked(self, state_service):
        state_service.global_last_triggered = time.time()

        ok, reason, blocked = state_service.acquire_execution_locks("r1", ["alpha", "beta"], 30, 1440)

        assert ok is False and blocked == "alpha"
        assert "Global cooldown" in reason
        assert state_service.container_cooldowns == {}

    def test_single_container_wrapper_unchanged(self, state_service):
        assert state_service.acquire_execution_lock("r1", "nginx", 30, 60) == (True, "")
        ok, reason = state_service.acquire_execution_lock("r2", "redis", 30, 60)
        assert ok is False and "Global cooldown" in reason


class TestMultiContainerRuleExecution:

    async def test_rule_restarts_every_target(self, automation, config_service, state_service,
                                              docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha", "beta"])).success
        _running_states(monkeypatch, {"alpha": True, "beta": True})

        assert await automation.process_message(_ctx()) == [RULE_NAME]

        assert [c.args for c in docker_action.await_args_list] == [("alpha", "restart"), ("beta", "restart")]
        assert {k: v[0] for k, v in _results(state_service).items()} == {"alpha": "SUCCESS", "beta": "SUCCESS"}

    async def test_blocked_rule_does_not_lock_other_targets(self, automation, config_service, state_service,
                                                            docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha", "beta"])).success
        _running_states(monkeypatch, {"alpha": True, "beta": True})
        rule_id = config_service.get_rules()[0].id
        state_service.container_cooldowns[state_service.cooldown_key(rule_id, "beta")] = time.time()

        assert await automation.process_message(_ctx()) == []

        docker_action.assert_not_awaited()
        assert state_service.cooldown_key(rule_id, "alpha") not in state_service.container_cooldowns
        history = state_service.get_history()
        assert len(history) == 1
        assert (history[0]["container"], history[0]["result"]) == ("beta", "SKIPPED")


# --------------------------------------------------------------------------- #
# C1-6: only_if_running                                                        #
# --------------------------------------------------------------------------- #

class TestOnlyIfRunning:

    async def test_stopped_container_is_not_restarted(self, automation, config_service, state_service,
                                                      docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha"])).success
        _running_states(monkeypatch, {"alpha": False})

        assert await automation.process_message(_ctx()) == []

        docker_action.assert_not_awaited()
        result, details = _results(state_service)["alpha"]
        assert result == "SKIPPED" and "only_if_running" in details
        # Nothing was executed, so the container cooldown was released again
        rule_id = config_service.get_rules()[0].id
        assert not state_service.container_cooldowns.get(state_service.cooldown_key(rule_id, "alpha"))

    async def test_only_running_targets_are_restarted(self, automation, config_service, state_service,
                                                      docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha", "beta"])).success
        _running_states(monkeypatch, {"alpha": True, "beta": False})

        assert await automation.process_message(_ctx()) == [RULE_NAME]

        docker_action.assert_awaited_once_with("alpha", "restart")
        results = _results(state_service)
        assert results["alpha"][0] == "SUCCESS"
        assert results["beta"][0] == "SKIPPED"

    async def test_stop_rule_skips_stopped_container(self, automation, config_service, state_service,
                                                     docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha"], action="STOP")).success
        _running_states(monkeypatch, {"alpha": False})

        assert await automation.process_message(_ctx()) == []
        docker_action.assert_not_awaited()

    async def test_flag_off_restarts_stopped_container(self, automation, config_service,
                                                       docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha"], only_if_running=False)).success
        info = _running_states(monkeypatch, {"alpha": False})

        assert await automation.process_message(_ctx()) == [RULE_NAME]
        docker_action.assert_awaited_once_with("alpha", "restart")
        info.assert_not_awaited()

    @pytest.mark.parametrize("info_mock", [
        AsyncMock(side_effect=RuntimeError("docker down")),
        AsyncMock(return_value=None),
    ])
    async def test_unknown_state_does_not_block(self, info_mock, automation, config_service,
                                                docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha"])).success
        monkeypatch.setattr(auto_mod, "get_docker_info", info_mock)

        assert await automation.process_message(_ctx()) == [RULE_NAME]
        docker_action.assert_awaited_once_with("alpha", "restart")

    async def test_start_rules_are_not_gated(self, automation, config_service, docker_action, monkeypatch):
        assert config_service.add_rule(_rule(["alpha"], action="START")).success
        info = _running_states(monkeypatch, {"alpha": False})

        assert await automation.process_message(_ctx()) == [RULE_NAME]
        docker_action.assert_awaited_once_with("alpha", "start")
        info.assert_not_awaited()


# --------------------------------------------------------------------------- #
# C1-5: ReDoS heuristic                                                        #
# --------------------------------------------------------------------------- #

class TestRegexWorkerResult:
    """V2 review B2: the regex search runs in a killable worker process.

    Regression guard for a control-flow bug of the first version: the result had already been
    received, but the child was still exiting, which was mistaken for a timeout - so every
    regex trigger silently reported "no match" and rules stopped firing.
    """

    def test_result_counts_even_while_the_worker_is_still_exiting(self):
        from services.automation.automation_service import AutomationService

        service = AutomationService.__new__(AutomationService)
        assert service._safe_regex_search(r"err(or)?\s+\d+", "error 500") is True
        assert service._safe_regex_search("needle", "no match here") is False

    def test_catastrophic_pattern_is_killed_and_reported_as_no_match(self):
        import time as _t
        from services.automation.automation_service import AutomationService, REGEX_TIMEOUT_SECONDS

        service = AutomationService.__new__(AutomationService)
        started = _t.time()
        assert service._safe_regex_search(r"(a|a)+$", "a" * 30 + "b") is False
        # killed at the budget instead of running for minutes
        assert _t.time() - started < REGEX_TIMEOUT_SECONDS + 5


class TestRegexValidation:

    @pytest.mark.parametrize("pattern", [
        "crash",
        r"server (crashed|down)",
        r"error:\s+\d+",
        r"err(or)?\s+\d+",
        r"(fatal|panic): .*",
        r"\bplayer \w+ (joined|left)\b",
        r"update (available|required) for \S+",
        r"c\+\+",
        r"\(a+\)+",     # escaped parentheses - no group
        r"([+-]\d)+",   # quantifier characters only inside a character class
    ])
    def test_legitimate_patterns_accepted(self, pattern):
        ok, msg = validate_regex_pattern(pattern)
        assert ok is True, msg

    @pytest.mark.parametrize("pattern", [
        "(a+)+",
        r"(\w+)+",
        "(.*)+",
        "(.+)+",
        "([a-z]+)*",
        r"(\d+\s?)+",
        "(x+){2,}",
        r"^(\w+\s?)*$",
    ])
    def test_nested_quantifiers_rejected(self, pattern):
        ok, msg = validate_regex_pattern(pattern)
        assert ok is False
        assert "ReDoS" in msg

    def test_invalid_and_too_long_patterns_still_rejected(self):
        ok, msg = validate_regex_pattern("[unclosed")
        assert ok is False and "Invalid regex" in msg
        ok, msg = validate_regex_pattern("a" * 501)
        assert ok is False and "too long" in msg

    def test_rule_with_regex_trigger_can_be_saved(self, config_service):
        payload = _rule(["alpha"], regex=r"server (crashed|down)")
        ok, msg, _ = validate_rule_data(payload)
        assert ok is True, msg
        assert config_service.add_rule(payload).success
