# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Automation Service Unit Tests                  #
# ============================================================================ #
"""
Functional unit tests for the Auto-Action automation system.

Targets:
    services.automation.automation_service
    services.automation.auto_action_config_service
    services.automation.auto_action_state_service

Strategy:
    * Redirect each service's ``base_dir`` to ``tmp_path`` so writes land in a
      sandboxed config directory.
    * Patch ``docker_action`` / ``is_container_exists`` on the
      ``automation_service`` module (imported-by-name) so no real Docker
      daemon is required.
    * Build an AutomationService manually with our sandboxed singletons —
      the real ``__init__`` resolves them via ``get_*`` factories that we
      monkeypatch into the module namespace.

We never mutate ``sys.modules``.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import (
    auto_action_config_service as cfg_mod,
    auto_action_state_service as state_mod,
    automation_service as auto_mod,
)
from services.automation.auto_action_config_service import (
    ActionConfig,
    AutoActionConfigService,
    AutoActionRule,
    ConfigResult,
    TriggerConfig,
    sanitize_string,
    validate_discord_snowflake,
    validate_regex_pattern,
    validate_rule_data,
)
from services.automation.auto_action_state_service import (
    AutoActionStateService,
    TriggerEvent,
)
from services.automation.automation_service import (
    AutomationService,
    TriggerContext,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sandbox_config_dir(tmp_path: Path) -> Path:
    """Create a tmp ``<tmp>/config`` dir used as the service base_dir/config."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path  # base_dir; service appends "config/<file>.json"


@pytest.fixture
def config_service(sandbox_config_dir: Path) -> AutoActionConfigService:
    """Fresh AutoActionConfigService rooted at the sandbox tmp dir."""
    svc = AutoActionConfigService.__new__(AutoActionConfigService)
    svc.base_dir = sandbox_config_dir
    svc.config_file = sandbox_config_dir / "config" / "auto_actions.json"
    svc._ensure_config_exists()
    return svc


@pytest.fixture
def state_service(sandbox_config_dir: Path) -> AutoActionStateService:
    """Fresh AutoActionStateService rooted at the sandbox tmp dir."""
    from threading import Lock
    svc = AutoActionStateService.__new__(AutoActionStateService)
    svc.base_dir = sandbox_config_dir
    svc.state_file = sandbox_config_dir / "config" / "auto_actions_state.json"
    svc._lock = Lock()
    svc.global_last_triggered = 0.0
    svc.rule_cooldowns = {}
    svc.container_cooldowns = {}
    svc.trigger_history = {}
    return svc


@pytest.fixture
def automation(monkeypatch, config_service, state_service) -> AutomationService:
    """An AutomationService wired to our sandboxed singletons."""
    monkeypatch.setattr(
        auto_mod, "get_auto_action_config_service", lambda: config_service
    )
    monkeypatch.setattr(
        auto_mod, "get_auto_action_state_service", lambda: state_service
    )
    return AutomationService()


def _valid_rule_payload(**overrides) -> Dict[str, Any]:
    """Build a baseline valid rule payload that passes ``validate_rule_data``."""
    payload = {
        "name": "Restart on Crash",
        "enabled": True,
        "priority": 10,
        "trigger": {
            "channel_ids": ["123456789012345678"],
            "keywords": ["crash", "fatal"],
            "required_keywords": [],
            "ignore_keywords": [],
            "match_mode": "any",
            "regex_pattern": None,
            "search_in": ["content", "embeds"],
            "source_filter": {
                "allowed_user_ids": [],
                "allowed_usernames": [],
                "is_webhook": None,
            },
        },
        "action": {
            "type": "RESTART",
            "containers": ["nginx"],
            "delay_seconds": 0,
            "notification_channel_id": None,
            "silent": False,
        },
        "safety": {
            "cooldown_minutes": 60,
            "only_if_running": True,
        },
    }
    for k, v in overrides.items():
        payload[k] = v
    return payload


def _ctx(**overrides) -> TriggerContext:
    base = dict(
        message_id="999",
        channel_id="123456789012345678",
        guild_id="100",
        user_id="200",
        username="alice",
        is_webhook=False,
        content="",
        embeds_text="",
    )
    base.update(overrides)
    return TriggerContext(**base)


# ===========================================================================
# auto_action_config_service.py
# ===========================================================================

class TestValidationHelpers:
    """Pure-function validation helpers."""

    def test_validate_discord_snowflake_accepts_empty(self):
        ok, msg = validate_discord_snowflake("", "Channel ID")
        assert ok is True and msg == ""

    def test_validate_discord_snowflake_accepts_valid(self):
        ok, _ = validate_discord_snowflake("123456789012345678", "Channel ID")
        assert ok is True

    def test_validate_discord_snowflake_rejects_short(self):
        ok, msg = validate_discord_snowflake("123", "Channel ID")
        assert ok is False
        assert "Channel ID" in msg

    def test_validate_regex_pattern_accepts_empty(self):
        ok, msg = validate_regex_pattern("")
        assert ok is True and msg == ""

    def test_validate_regex_pattern_rejects_redos_nested(self):
        # (a+)+ is in the dangerous list
        ok, msg = validate_regex_pattern("(a+)+")
        assert ok is False
        assert "ReDoS" in msg

    def test_validate_regex_pattern_rejects_invalid_compile(self):
        ok, msg = validate_regex_pattern("[unclosed")
        assert ok is False

    def test_validate_regex_pattern_rejects_too_long(self):
        # Pattern of dots only — does not trip the dangerous-pattern heuristics,
        # so it falls through to the length check.
        ok, msg = validate_regex_pattern("." * 600)
        assert ok is False
        assert "too long" in msg

    def test_validate_regex_pattern_accepts_normal(self):
        # The dangerous-pattern heuristic is aggressive (it flags any user
        # pattern containing word chars). A pattern of dots passes cleanly.
        ok, _ = validate_regex_pattern(r"\.\.\.")
        assert ok is True

    def test_sanitize_string_strips_html_brackets(self):
        out = sanitize_string("<b>Hi</b>")
        assert "<" not in out and ">" not in out
        assert "Hi" in out

    def test_sanitize_string_truncates(self):
        out = sanitize_string("x" * 500, max_length=10)
        assert len(out) <= 10

    def test_sanitize_string_handles_empty(self):
        assert sanitize_string("") == ""


class TestValidateRuleData:

    def test_valid_payload_passes(self):
        ok, err, warnings = validate_rule_data(_valid_rule_payload())
        assert ok is True, err
        assert err == ""
        assert warnings == []

    def test_missing_name_fails(self):
        payload = _valid_rule_payload()
        payload["name"] = ""
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "name is required" in err.lower()

    def test_invalid_priority_fails(self):
        payload = _valid_rule_payload()
        payload["priority"] = 9999
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "Priority" in err

    def test_missing_channel_ids_fails(self):
        payload = _valid_rule_payload()
        payload["trigger"]["channel_ids"] = []
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "channel" in err.lower()

    def test_no_keywords_or_regex_fails(self):
        payload = _valid_rule_payload()
        payload["trigger"]["keywords"] = []
        payload["trigger"]["required_keywords"] = []
        payload["trigger"]["regex_pattern"] = None
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "keyword" in err.lower() or "regex" in err.lower()

    def test_invalid_action_type_fails(self):
        payload = _valid_rule_payload()
        payload["action"]["type"] = "DELETE"
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "action" in err.lower()

    def test_protected_container_emits_warning(self):
        payload = _valid_rule_payload()
        payload["action"]["containers"] = ["DDC", "nginx"]
        ok, _, warnings = validate_rule_data(payload, protected_containers=["ddc"])
        assert ok is True
        assert any("protected" in w.lower() for w in warnings)

    def test_invalid_match_mode_fails(self):
        payload = _valid_rule_payload()
        payload["trigger"]["match_mode"] = "weird"
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "match_mode" in err

    def test_cooldown_out_of_range_fails(self):
        payload = _valid_rule_payload()
        payload["safety"]["cooldown_minutes"] = 0
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "Cooldown" in err

    def test_delay_out_of_range_fails(self):
        payload = _valid_rule_payload()
        payload["action"]["delay_seconds"] = -1
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "Delay" in err


class TestDataclasses:

    def test_trigger_config_roundtrip(self):
        data = {
            "channel_ids": ["111111111111111111"],
            "keywords": ["k1"],
            "required_keywords": ["r1"],
            "ignore_keywords": ["i1"],
            "match_mode": "all",
            "regex_pattern": r"\bx\b",
            "search_in": ["content"],
            "source_filter": {
                "allowed_user_ids": ["222222222222222222"],
                "allowed_usernames": ["bob"],
                "is_webhook": True,
            },
        }
        tc = TriggerConfig.from_dict(data)
        assert tc.channel_ids == ["111111111111111111"]
        assert tc.match_mode == "all"
        assert tc.allowed_usernames == ["bob"]
        assert tc.is_webhook is True
        out = tc.to_dict()
        assert out["match_mode"] == "all"
        assert out["source_filter"]["is_webhook"] is True

    def test_action_config_defaults(self):
        ac = ActionConfig.from_dict({})
        assert ac.type == "NOTIFY"
        assert ac.containers == []
        assert ac.delay_seconds == 0
        assert ac.silent is False

    def test_auto_action_rule_roundtrip(self):
        rule = AutoActionRule.from_dict(_valid_rule_payload())
        d = rule.to_dict()
        # Round-trip preserves shape
        rule2 = AutoActionRule.from_dict(d)
        assert rule2.name == rule.name
        assert rule2.cooldown_minutes == rule.cooldown_minutes
        assert rule2.action.type == "RESTART"

    def test_auto_action_rule_generates_id_when_missing(self):
        payload = _valid_rule_payload()
        # No 'id' key
        rule = AutoActionRule.from_dict(payload)
        assert rule.id  # uuid generated


class TestConfigService:

    def test_ensure_config_creates_default(self, config_service: AutoActionConfigService):
        assert config_service.config_file.exists()
        data = json.loads(config_service.config_file.read_text())
        assert data["global_settings"]["enabled"] is True
        assert "ddc" in data["global_settings"]["protected_containers"]
        assert data["auto_actions"] == []

    def test_get_global_settings_returns_defaults(
        self, config_service: AutoActionConfigService
    ):
        settings = config_service.get_global_settings()
        assert settings["enabled"] is True
        assert settings["global_cooldown_seconds"] == 30

    def test_add_rule_persists(self, config_service: AutoActionConfigService):
        result = config_service.add_rule(_valid_rule_payload())
        assert result.success is True
        assert isinstance(result.data, AutoActionRule)

        rules = config_service.get_rules()
        assert len(rules) == 1
        assert rules[0].name == "Restart on Crash"

    def test_add_rule_fails_validation(self, config_service: AutoActionConfigService):
        bad = _valid_rule_payload()
        bad["name"] = ""
        result = config_service.add_rule(bad)
        assert result.success is False
        assert result.error and "Validation failed" in result.error

    def test_add_rule_generates_id_and_metadata(
        self, config_service: AutoActionConfigService
    ):
        result = config_service.add_rule(_valid_rule_payload())
        assert result.success is True
        rule_id = result.data.id
        assert rule_id

        # Persisted dict carries metadata
        on_disk = json.loads(config_service.config_file.read_text())
        rule_dict = on_disk["auto_actions"][0]
        assert rule_dict["metadata"]["trigger_count"] == 0
        assert "created_at" in rule_dict["metadata"]

    def test_get_rule_by_id(self, config_service: AutoActionConfigService):
        result = config_service.add_rule(_valid_rule_payload())
        rid = result.data.id
        fetched = config_service.get_rule(rid)
        assert fetched is not None
        assert fetched.id == rid
        assert config_service.get_rule("does-not-exist") is None

    def test_update_rule_success(self, config_service: AutoActionConfigService):
        result = config_service.add_rule(_valid_rule_payload())
        rid = result.data.id

        updated_payload = _valid_rule_payload()
        updated_payload["name"] = "Renamed"
        updated_payload["priority"] = 50

        upd = config_service.update_rule(rid, updated_payload)
        assert upd.success is True
        fetched = config_service.get_rule(rid)
        assert fetched.name == "Renamed"
        assert fetched.priority == 50

    def test_update_rule_not_found(self, config_service: AutoActionConfigService):
        upd = config_service.update_rule("missing-id", _valid_rule_payload())
        assert upd.success is False
        assert "not found" in upd.error.lower()

    def test_update_rule_invalid_payload(self, config_service: AutoActionConfigService):
        result = config_service.add_rule(_valid_rule_payload())
        rid = result.data.id

        bad = _valid_rule_payload()
        bad["priority"] = 999
        upd = config_service.update_rule(rid, bad)
        assert upd.success is False

    def test_delete_rule_success(self, config_service: AutoActionConfigService):
        result = config_service.add_rule(_valid_rule_payload())
        rid = result.data.id
        d = config_service.delete_rule(rid)
        assert d.success is True
        assert config_service.get_rule(rid) is None

    def test_delete_rule_not_found(self, config_service: AutoActionConfigService):
        d = config_service.delete_rule("nope")
        assert d.success is False

    def test_update_global_settings_merges(
        self, config_service: AutoActionConfigService
    ):
        result = config_service.update_global_settings(
            {"enabled": False, "global_cooldown_seconds": 90}
        )
        assert result.success is True
        s = config_service.get_global_settings()
        assert s["enabled"] is False
        assert s["global_cooldown_seconds"] == 90
        # Still has other defaults preserved
        assert "protected_containers" in s

    def test_increment_trigger_count(self, config_service: AutoActionConfigService):
        added = config_service.add_rule(_valid_rule_payload())
        rid = added.data.id

        assert config_service.increment_trigger_count(rid) is True
        assert config_service.increment_trigger_count(rid) is True

        on_disk = json.loads(config_service.config_file.read_text())
        meta = on_disk["auto_actions"][0]["metadata"]
        assert meta["trigger_count"] == 2
        assert "last_triggered" in meta

    def test_increment_trigger_count_unknown_rule(
        self, config_service: AutoActionConfigService
    ):
        assert config_service.increment_trigger_count("nope") is False

    def test_load_config_handles_corrupt_file(
        self, config_service: AutoActionConfigService
    ):
        # Write invalid JSON
        config_service.config_file.write_text("{not-json")
        data = config_service._load_config_file()
        # Returns sane fallback
        assert "global_settings" in data
        assert data["auto_actions"] == []

    def test_get_rules_skips_invalid_entries(
        self, config_service: AutoActionConfigService
    ):
        # Add one valid rule, then corrupt one entry on disk
        config_service.add_rule(_valid_rule_payload())
        on_disk = json.loads(config_service.config_file.read_text())
        # Inject an entry that will trigger an exception in from_dict
        # (None.get(...) will raise AttributeError)
        on_disk["auto_actions"].append({"id": None, "trigger": "not-a-dict"})
        config_service.config_file.write_text(json.dumps(on_disk))

        rules = config_service.get_rules()
        # First valid rule still surfaces, broken one is filtered
        assert len(rules) >= 1


# ===========================================================================
# auto_action_state_service.py
# ===========================================================================

class TestStateService:

    def test_acquire_lock_succeeds_when_no_cooldowns(
        self, state_service: AutoActionStateService
    ):
        ok, reason = state_service.acquire_execution_lock(
            "rule-1", "nginx", global_cooldown=30, rule_cooldown_mins=60
        )
        assert ok is True
        assert reason == ""
        assert state_service.global_last_triggered > 0
        assert "nginx" in state_service.container_cooldowns
        assert "rule-1" in state_service.rule_cooldowns

    def test_acquire_lock_blocked_by_global_cooldown(
        self, state_service: AutoActionStateService
    ):
        # First acquire sets global cooldown
        state_service.acquire_execution_lock(
            "rule-1", "nginx", 30, 60
        )
        # Immediate second attempt with a different container: blocked globally
        ok, reason = state_service.acquire_execution_lock(
            "rule-2", "redis", 30, 60
        )
        assert ok is False
        assert "Global cooldown" in reason

    def test_acquire_lock_blocked_by_container_cooldown(
        self, state_service: AutoActionStateService
    ):
        # Set the container cooldown directly to avoid global cooldown blocking
        state_service.container_cooldowns["nginx"] = time.time()
        # global_last_triggered is 0 so global passes; container blocks
        ok, reason = state_service.acquire_execution_lock(
            "rule-9", "nginx", global_cooldown=0, rule_cooldown_mins=60
        )
        assert ok is False
        assert "Container" in reason and "cooldown" in reason.lower()

    def test_check_cooldown_does_not_mutate_state(
        self, state_service: AutoActionStateService
    ):
        blocked, _ = state_service.check_cooldown("r1", "nginx", 30, 60)
        assert blocked is False
        # No side-effects
        assert state_service.global_last_triggered == 0.0
        assert state_service.container_cooldowns == {}

    def test_check_cooldown_reports_global_block(
        self, state_service: AutoActionStateService
    ):
        state_service.global_last_triggered = time.time()
        blocked, reason = state_service.check_cooldown("r1", "nginx", 30, 60)
        assert blocked is True
        assert "Global" in reason

    def test_check_cooldown_reports_container_block(
        self, state_service: AutoActionStateService
    ):
        state_service.container_cooldowns["nginx"] = time.time()
        blocked, reason = state_service.check_cooldown(
            "r1", "nginx", global_cooldown=0, rule_cooldown_mins=60
        )
        assert blocked is True
        assert "nginx" in reason

    def test_record_trigger_success_persists_history_and_state(
        self, state_service: AutoActionStateService
    ):
        state_service.record_trigger(
            "r1", "Restart", "nginx", "RESTART", "SUCCESS", "ok"
        )
        hist = state_service.get_history("nginx")
        assert len(hist) == 1
        assert hist[0]["result"] == "SUCCESS"
        # Cooldowns confirmed
        assert state_service.container_cooldowns["nginx"] > 0
        assert state_service.rule_cooldowns["r1"] > 0
        # File written
        assert state_service.state_file.exists()

    def test_record_trigger_failed_releases_cooldowns(
        self, state_service: AutoActionStateService
    ):
        # First acquire to set cooldowns
        state_service.acquire_execution_lock("r1", "nginx", 30, 60)
        assert state_service.container_cooldowns["nginx"] > 0

        state_service.record_trigger(
            "r1", "Restart", "nginx", "RESTART", "FAILED", "boom"
        )
        # Failed (without "cooldown" in details) -> reset to 0
        assert state_service.container_cooldowns["nginx"] == 0
        assert state_service.rule_cooldowns["r1"] == 0

    def test_record_trigger_skipped_no_state_change(
        self, state_service: AutoActionStateService
    ):
        # SKIPPED (e.g. blocked by cooldown / protected) — no cooldowns mutated
        state_service.record_trigger(
            "r1", "Restart", "nginx", "RESTART", "SKIPPED", "Protected container"
        )
        assert state_service.container_cooldowns == {}
        assert state_service.rule_cooldowns == {}
        # But history is still recorded
        assert len(state_service.get_history("nginx")) == 1

    def test_history_pruned_to_100(self, state_service: AutoActionStateService):
        for i in range(105):
            state_service.record_trigger(
                f"r{i}", "Rule", "nginx", "RESTART", "SUCCESS", str(i)
            )
        hist = state_service.get_history("nginx", limit=200)
        assert len(hist) == 100

    def test_get_history_global_sorted(self, state_service: AutoActionStateService):
        state_service.record_trigger("r1", "A", "nginx", "RESTART", "SUCCESS")
        state_service.record_trigger("r2", "B", "redis", "RESTART", "SUCCESS")
        all_hist = state_service.get_history()
        assert len(all_hist) == 2
        # Sorted desc by timestamp
        assert all_hist[0]["timestamp"] >= all_hist[1]["timestamp"]

    def test_load_state_migrates_old_key(self, sandbox_config_dir: Path):
        from threading import Lock
        # Pre-seed state file with old key
        state_file = sandbox_config_dir / "config" / "auto_actions_state.json"
        state_file.write_text(json.dumps({
            "global_cooldown_last_triggered": 12345.6,
            "rule_cooldowns": {"r1": 1.0},
            "container_cooldowns": {"nginx": 2.0},
            "trigger_history": {},
        }))

        svc = AutoActionStateService.__new__(AutoActionStateService)
        svc.base_dir = sandbox_config_dir
        svc.state_file = state_file
        svc._lock = Lock()
        svc.global_last_triggered = 0.0
        svc.rule_cooldowns = {}
        svc.container_cooldowns = {}
        svc.trigger_history = {}
        svc._load_state()

        assert svc.global_last_triggered == 12345.6
        # And the new file format was rewritten
        on_disk = json.loads(state_file.read_text())
        assert "global_last_triggered" in on_disk
        assert "global_cooldown_last_triggered" not in on_disk

    def test_release_execution_lock_resets_on_failure(
        self, state_service: AutoActionStateService
    ):
        state_service.acquire_execution_lock("r1", "nginx", 30, 60)
        state_service.release_execution_lock("r1", "nginx", success=False)
        assert "nginx" not in state_service.container_cooldowns
        assert "r1" not in state_service.rule_cooldowns

    def test_release_execution_lock_keeps_on_success(
        self, state_service: AutoActionStateService
    ):
        state_service.acquire_execution_lock("r1", "nginx", 30, 60)
        state_service.release_execution_lock("r1", "nginx", success=True)
        assert "nginx" in state_service.container_cooldowns

    def test_trigger_event_to_dict(self):
        ev = TriggerEvent(
            timestamp=1.0, rule_id="r", rule_name="n", container="c",
            action="RESTART", result="SUCCESS", details="ok",
        )
        d = ev.to_dict()
        assert d["rule_name"] == "n"
        assert d["result"] == "SUCCESS"


# ===========================================================================
# automation_service.py
# ===========================================================================

class TestTriggerContext:

    def test_full_text_combines_lowercase(self):
        ctx = _ctx(content="Hello CRASH", embeds_text="Embed Detail")
        assert "hello crash" in ctx.full_text
        assert "embed detail" in ctx.full_text

    def test_message_link_format(self):
        ctx = _ctx(message_id="m1", channel_id="c1", guild_id="g1")
        assert ctx.message_link == "https://discord.com/channels/g1/c1/m1"


@pytest.mark.asyncio
class TestAutomationServiceMatching:

    async def test_global_disabled_returns_empty(
        self, automation: AutomationService, config_service
    ):
        config_service.update_global_settings({"enabled": False})
        result = await automation.process_message(_ctx(content="crash"))
        assert result == []

    async def test_no_rules_returns_empty(self, automation: AutomationService):
        result = await automation.process_message(_ctx(content="anything"))
        assert result == []

    async def test_pre_filter_excludes_disabled(
        self, automation: AutomationService, config_service
    ):
        payload = _valid_rule_payload()
        payload["enabled"] = False
        config_service.add_rule(payload)
        result = await automation.process_message(_ctx(content="crash"))
        assert result == []

    async def test_pre_filter_excludes_wrong_channel(
        self, automation: AutomationService, config_service
    ):
        config_service.add_rule(_valid_rule_payload())
        # Different channel id
        result = await automation.process_message(
            _ctx(channel_id="999999999999999999", content="crash")
        )
        assert result == []

    async def test_pre_filter_excludes_wrong_user(
        self, automation: AutomationService, config_service
    ):
        payload = _valid_rule_payload()
        payload["trigger"]["source_filter"] = {
            "allowed_user_ids": ["111111111111111111"],
            "allowed_usernames": [],
            "is_webhook": None,
        }
        config_service.add_rule(payload)
        result = await automation.process_message(
            _ctx(user_id="999", content="crash")
        )
        assert result == []

    async def test_pre_filter_allows_username_whitelist(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["trigger"]["source_filter"] = {
            "allowed_user_ids": ["111111111111111111"],  # uid mismatch
            "allowed_usernames": ["alice"],              # but username matches
            "is_webhook": None,
        }
        config_service.add_rule(payload)

        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        result = await automation.process_message(
            _ctx(user_id="999", username="alice", content="crash now")
        )
        assert result == ["Restart on Crash"]

    async def test_pre_filter_webhook_required(
        self, automation: AutomationService, config_service
    ):
        payload = _valid_rule_payload()
        payload["trigger"]["source_filter"] = {
            "allowed_user_ids": [],
            "allowed_usernames": [],
            "is_webhook": True,
        }
        config_service.add_rule(payload)
        # Non-webhook message: should not match
        result = await automation.process_message(_ctx(content="crash"))
        assert result == []

    async def test_match_via_keyword_executes(
        self, automation, config_service, monkeypatch
    ):
        config_service.add_rule(_valid_rule_payload())
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        action_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(auto_mod, "docker_action", action_mock)

        result = await automation.process_message(
            _ctx(content="System CRASH detected")
        )
        assert result == ["Restart on Crash"]
        action_mock.assert_awaited_once_with("nginx", "restart")

    async def test_ignore_keyword_blocks_match(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["trigger"]["ignore_keywords"] = ["test"]
        config_service.add_rule(payload)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        result = await automation.process_message(_ctx(content="crash test"))
        assert result == []

    async def test_required_keyword_must_be_present(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["trigger"]["keywords"] = []
        payload["trigger"]["required_keywords"] = ["fatal", "error"]
        config_service.add_rule(payload)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        # Missing one required keyword — no match
        assert await automation.process_message(_ctx(content="fatal only")) == []
        # Both present — match
        assert (
            await automation.process_message(_ctx(content="fatal error happened"))
            == ["Restart on Crash"]
        )

    async def test_match_mode_all_requires_every_keyword(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["trigger"]["keywords"] = ["a", "b"]
        payload["trigger"]["match_mode"] = "all"
        config_service.add_rule(payload)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        assert await automation.process_message(_ctx(content="only a")) == []
        assert (
            await automation.process_message(_ctx(content="a and b"))
            == ["Restart on Crash"]
        )

    async def test_regex_match_executes(
        self, automation, config_service, monkeypatch
    ):
        # Bypass add_rule's aggressive regex validator by writing directly
        # to the config file. We're testing the runtime regex matcher here.
        payload = _valid_rule_payload()
        payload["id"] = "rid-regex-1"
        payload["trigger"]["keywords"] = []
        payload["trigger"]["regex_pattern"] = r"err(or)?\s+\d+"
        on_disk = json.loads(config_service.config_file.read_text())
        on_disk["auto_actions"].append(payload)
        config_service.config_file.write_text(json.dumps(on_disk))

        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        result = await automation.process_message(_ctx(content="error 500"))
        assert result == ["Restart on Crash"]

    async def test_regex_no_match_no_keywords_returns_empty(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["id"] = "rid-regex-2"
        payload["trigger"]["keywords"] = []
        payload["trigger"]["regex_pattern"] = r"foobar\d+"
        on_disk = json.loads(config_service.config_file.read_text())
        on_disk["auto_actions"].append(payload)
        config_service.config_file.write_text(json.dumps(on_disk))

        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))

        result = await automation.process_message(_ctx(content="nothing here"))
        assert result == []



class TestSafeRegexSearch:
    """Sync tests for _safe_regex_search (no asyncio mark)."""

    def test_safe_regex_search_caps_input(self, automation: AutomationService):
        big = "a" * 50000 + "needle"
        # needle is dropped because text is truncated to 10k chars
        assert automation._safe_regex_search("needle", big) is False
        assert automation._safe_regex_search("a", big) is True

    def test_safe_regex_search_swallows_errors(self, automation: AutomationService):
        # Invalid pattern returns False
        assert automation._safe_regex_search("[unclosed", "text") is False


@pytest.mark.asyncio
class TestAutomationServiceExecution:

    async def test_protected_container_blocks_execution(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["action"]["containers"] = ["ddc"]  # protected by default
        config_service.add_rule(payload)

        action_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(auto_mod, "docker_action", action_mock)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))

        result = await automation.process_message(_ctx(content="crash"))
        assert result == []
        action_mock.assert_not_awaited()

    async def test_cooldown_blocks_second_execution(
        self, automation, config_service, monkeypatch
    ):
        config_service.add_rule(_valid_rule_payload())
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        first = await automation.process_message(_ctx(content="crash"))
        assert first == ["Restart on Crash"]

        # Same container, second message — should be blocked by cooldown
        second = await automation.process_message(_ctx(content="crash again"))
        assert second == []

    async def test_container_not_found_records_failure(
        self, automation, config_service, monkeypatch
    ):
        config_service.add_rule(_valid_rule_payload())
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=False))
        action_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(auto_mod, "docker_action", action_mock)

        bot = MagicMock()
        bot.get_channel.return_value = AsyncMock()
        bot.get_channel.return_value.send = AsyncMock()
        result = await automation.process_message(_ctx(content="crash"), bot)
        # No success → not in executed list
        assert result == []
        action_mock.assert_not_awaited()

    async def test_notify_action_succeeds_without_docker_call(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["action"]["type"] = "NOTIFY"
        payload["action"]["containers"] = ["nginx"]
        config_service.add_rule(payload)

        action_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(auto_mod, "docker_action", action_mock)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        bot.get_channel.return_value = channel
        bot.get_cog.return_value = None

        result = await automation.process_message(_ctx(content="crash"), bot)
        assert result == ["Restart on Crash"]
        action_mock.assert_not_awaited()  # NOTIFY does not call docker_action
        # Feedback message was sent
        assert channel.send.await_count >= 1

    async def test_recreate_maps_to_restart(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["action"]["type"] = "RECREATE"
        config_service.add_rule(payload)

        action_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", action_mock)

        bot = MagicMock()
        bot.get_channel.return_value = None
        bot.get_cog.return_value = None
        result = await automation.process_message(_ctx(content="crash"), bot)
        assert result == ["Restart on Crash"]
        action_mock.assert_awaited_once_with("nginx", "restart")

    async def test_silent_action_skips_feedback(
        self, automation, config_service, monkeypatch
    ):
        payload = _valid_rule_payload()
        payload["action"]["silent"] = True
        config_service.add_rule(payload)
        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        bot.get_channel.return_value = channel
        bot.get_cog.return_value = None

        result = await automation.process_message(_ctx(content="crash"), bot)
        assert result == ["Restart on Crash"]
        channel.send.assert_not_awaited()

    async def test_priority_sort_executes_higher_first(
        self, automation, config_service, monkeypatch
    ):
        # Two rules on same container, high-priority should execute first
        # and consume the cooldown slot.
        a = _valid_rule_payload()
        a["name"] = "Low"
        a["priority"] = 5

        b = _valid_rule_payload()
        b["name"] = "High"
        b["priority"] = 50

        config_service.add_rule(a)
        config_service.add_rule(b)

        order: List[str] = []

        async def docker_action_recorder(name, action):
            order.append(name)
            return True

        monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(auto_mod, "docker_action", docker_action_recorder)

        result = await automation.process_message(_ctx(content="crash"))
        # High runs first; Low gets blocked by cooldown
        assert result == ["High"]

    async def test_send_feedback_handles_missing_channel(
        self, automation: AutomationService
    ):
        bot = MagicMock()
        bot.get_channel.return_value = None
        # Should not raise
        await automation._send_feedback(bot, "1234", "hello")

    async def test_send_feedback_swallows_exceptions(
        self, automation: AutomationService
    ):
        bot = MagicMock()
        bot.get_channel.side_effect = RuntimeError("boom")
        await automation._send_feedback(bot, "1234", "hi")  # no raise

    async def test_trigger_status_refresh_uses_cog_when_present(
        self, automation: AutomationService
    ):
        bot = MagicMock()
        cog = MagicMock()
        cog.trigger_status_refresh = AsyncMock()
        bot.get_cog.return_value = cog
        await automation._trigger_status_refresh(bot, "nginx")
        cog.trigger_status_refresh.assert_awaited_once()

    async def test_trigger_status_refresh_no_cog_no_raise(
        self, automation: AutomationService
    ):
        bot = MagicMock()
        bot.get_cog.return_value = None
        await automation._trigger_status_refresh(bot, "nginx")  # no raise


# ===========================================================================
# Singleton factories — light coverage
# ===========================================================================

class TestSingletonFactories:

    def test_get_automation_service_returns_singleton(self, monkeypatch):
        # Reset module-level singleton
        monkeypatch.setattr(auto_mod, "_automation_service", None)
        # Stub the inner factories so __init__ doesn't reach the real fs
        monkeypatch.setattr(
            auto_mod,
            "get_auto_action_config_service",
            lambda: MagicMock(spec=AutoActionConfigService),
        )
        monkeypatch.setattr(
            auto_mod,
            "get_auto_action_state_service",
            lambda: MagicMock(spec=AutoActionStateService),
        )
        s1 = auto_mod.get_automation_service()
        s2 = auto_mod.get_automation_service()
        assert s1 is s2

    def test_get_state_service_singleton(self, monkeypatch, sandbox_config_dir):
        monkeypatch.setattr(state_mod, "_state_service", None)
        # Patch base path resolution by setting cwd-style attribute is not
        # possible; instead pre-create the config dir in cwd is also not
        # easy. We just exercise that calling twice returns same instance.
        # The constructor's filesystem touches go to the real /Volumes path
        # but state file may not exist — that's fine, _load_state guards it.
        # NOTE: To avoid permissions issues we patch the class to use sandbox.
        original_init = state_mod.AutoActionStateService.__init__

        def fake_init(self):
            from threading import Lock
            self.base_dir = sandbox_config_dir
            self.state_file = sandbox_config_dir / "config" / "auto_actions_state.json"
            self._lock = Lock()
            self.global_last_triggered = 0.0
            self.rule_cooldowns = {}
            self.container_cooldowns = {}
            self.trigger_history = {}

        monkeypatch.setattr(state_mod.AutoActionStateService, "__init__", fake_init)
        try:
            s1 = state_mod.get_auto_action_state_service()
            s2 = state_mod.get_auto_action_state_service()
            assert s1 is s2
        finally:
            monkeypatch.setattr(
                state_mod.AutoActionStateService, "__init__", original_init
            )

    def test_get_config_service_singleton(self, monkeypatch, sandbox_config_dir):
        monkeypatch.setattr(cfg_mod, "_service_instance", None)
        original_init = cfg_mod.AutoActionConfigService.__init__

        def fake_init(self):
            self.base_dir = sandbox_config_dir
            self.config_file = sandbox_config_dir / "config" / "auto_actions.json"
            self._ensure_config_exists()

        monkeypatch.setattr(cfg_mod.AutoActionConfigService, "__init__", fake_init)
        try:
            s1 = cfg_mod.get_auto_action_config_service()
            s2 = cfg_mod.get_auto_action_config_service()
            assert s1 is s2
        finally:
            monkeypatch.setattr(
                cfg_mod.AutoActionConfigService, "__init__", original_init
            )
