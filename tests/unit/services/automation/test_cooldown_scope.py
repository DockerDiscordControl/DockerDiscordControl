#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for the switchable auto-action cooldown scope (finding B9, v2.4.0).

Until v2.4.0 the state service wrote ``rule_cooldowns[rule_id]`` on every trigger
but never read it back, so the rule's "Cooldown (Minutes)" setting effectively
applied *per container*. A rule covering three containers could act on each of
them once per cooldown window.

Rather than silently changing that for every existing installation, the scope is
now explicit:

- ``container`` (default, and what every release before v2.4.0 did)
- ``rule``      (one trigger blocks the whole rule)

The default matters most here: a rule stored by an older version has no
``cooldown_scope`` key at all and must keep behaving exactly as before.
"""

import time
from threading import Lock

import pytest

from services.automation.auto_action_config_service import (
    COOLDOWN_SCOPES,
    AutoActionRule,
    validate_rule_data,
)
from services.automation.auto_action_state_service import AutoActionStateService


def _make_state_service():
    """Build the service without __init__, which would read/write a real state file."""
    svc = object.__new__(AutoActionStateService)
    svc._lock = Lock()
    svc.global_last_triggered = 0.0
    svc.rule_cooldowns = {}
    svc.container_cooldowns = {}
    svc.trigger_history = {}
    return svc


# No global cooldown in these tests: it is a separate mechanism and would mask the
# per-rule/per-container behaviour under test.
NO_GLOBAL = 0
ONE_DAY = 1440


# ---------------------------------------------------------------------------
# The rule model
# ---------------------------------------------------------------------------

class TestRuleModelDefault:
    def test_rule_without_scope_defaults_to_container(self):
        """Rules written before v2.4.0 carry no scope and must not change behaviour."""
        rule = AutoActionRule.from_dict({
            "id": "r1", "name": "old rule",
            "trigger": {}, "action": {},
            "safety": {"cooldown_minutes": 60},
        })
        assert rule.cooldown_scope == "container"

    def test_scope_survives_a_round_trip(self):
        rule = AutoActionRule.from_dict({
            "id": "r1", "name": "new rule",
            "trigger": {}, "action": {},
            "safety": {"cooldown_minutes": 60, "cooldown_scope": "rule"},
        })
        assert rule.cooldown_scope == "rule"
        assert rule.to_dict()["safety"]["cooldown_scope"] == "rule"

    def test_to_dict_always_writes_the_scope(self):
        """So a rule saved once carries the key explicitly from then on."""
        rule = AutoActionRule.from_dict({"id": "r1", "name": "x", "trigger": {}, "action": {}})
        assert rule.to_dict()["safety"]["cooldown_scope"] == "container"


# ---------------------------------------------------------------------------
# Scope "container" - the pre-v2.4.0 behaviour
# ---------------------------------------------------------------------------

class TestContainerScope:
    def test_second_container_is_not_blocked_by_the_first(self):
        """The core of B9: this is what users have today and must keep."""
        svc = _make_state_service()

        ok, _, _ = svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY)
        assert ok is True

        ok, reason, _ = svc.acquire_execution_locks("r1", ["beta"], NO_GLOBAL, ONE_DAY)
        assert ok is True, f"a different container must still run, got: {reason}"

    def test_same_container_is_blocked(self):
        svc = _make_state_service()
        assert svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY)[0] is True

        ok, reason, blocked = svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY)
        assert ok is False
        assert blocked == "alpha"
        assert "alpha" in reason

    def test_explicit_container_scope_behaves_like_the_default(self):
        svc = _make_state_service()
        svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "container")
        ok, _, _ = svc.acquire_execution_locks("r1", ["beta"], NO_GLOBAL, ONE_DAY, "container")
        assert ok is True


# ---------------------------------------------------------------------------
# Scope "rule" - the new, opt-in behaviour
# ---------------------------------------------------------------------------

class TestRuleScope:
    def test_second_container_is_blocked_by_the_rule(self):
        svc = _make_state_service()

        ok, _, _ = svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "rule")
        assert ok is True

        ok, reason, blocked = svc.acquire_execution_locks("r1", ["beta"], NO_GLOBAL, ONE_DAY, "rule")
        assert ok is False
        assert "Rule cooldown" in reason
        assert blocked == "beta"

    def test_a_different_rule_is_unaffected(self):
        """The rule cooldown is keyed by rule id, not global."""
        svc = _make_state_service()
        svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "rule")

        ok, _, _ = svc.acquire_execution_locks("r2", ["beta"], NO_GLOBAL, ONE_DAY, "rule")
        assert ok is True

    def test_expired_rule_cooldown_allows_the_next_run(self):
        svc = _make_state_service()
        svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "rule")

        # Pretend the cooldown elapsed (2 days ago for a 1 day window)
        svc.rule_cooldowns["r1"] = time.time() - (2 * ONE_DAY * 60)
        svc.container_cooldowns["alpha"] = time.time() - (2 * ONE_DAY * 60)

        ok, reason, _ = svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "rule")
        assert ok is True, reason

    def test_nothing_is_locked_when_the_rule_cooldown_blocks(self):
        """A refused run must not leave containers locked (the V2-B1 lesson)."""
        svc = _make_state_service()
        svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "rule")
        before = dict(svc.container_cooldowns)

        svc.acquire_execution_locks("r1", ["beta", "gamma"], NO_GLOBAL, ONE_DAY, "rule")
        assert svc.container_cooldowns == before, "a blocked rule must not lock its targets"


# ---------------------------------------------------------------------------
# check_cooldown (read-only twin) keeps the same semantics
# ---------------------------------------------------------------------------

class TestCheckCooldown:
    @pytest.mark.parametrize("scope, expect_blocked", [("container", False), ("rule", True)])
    def test_other_container_depends_on_scope(self, scope, expect_blocked):
        svc = _make_state_service()
        svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, scope)

        blocked, _ = svc.check_cooldown("r1", "beta", NO_GLOBAL, ONE_DAY, scope)
        assert blocked is expect_blocked

    def test_default_argument_is_container_scope(self):
        svc = _make_state_service()
        svc.acquire_execution_locks("r1", ["alpha"], NO_GLOBAL, ONE_DAY, "rule")

        blocked, _ = svc.check_cooldown("r1", "beta", NO_GLOBAL, ONE_DAY)
        assert blocked is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _rule_data(safety):
    """A rule payload; only the cooldown part matters for these assertions."""
    return {
        "id": "r1",
        "name": "Test rule",
        "enabled": True,
        "priority": 10,
        "trigger": {"type": "KEYWORD", "keywords": ["update"], "channel_id": "1"},
        "action": {"type": "RESTART", "containers": ["alpha"]},
        "safety": safety,
    }


class TestScopeValidation:
    """These assert on the cooldown message only, so they stay valid regardless of
    whatever else the validator may complain about in the sample payload."""

    @pytest.mark.parametrize("scope", sorted(COOLDOWN_SCOPES))
    def test_valid_scopes_produce_no_scope_error(self, scope):
        _, message, _ = validate_rule_data(_rule_data({"cooldown_minutes": 60,
                                                       "cooldown_scope": scope}))
        assert "Cooldown scope" not in message

    def test_missing_scope_is_accepted(self):
        """Rules from older versions have no scope key - that must not be an error."""
        _, message, _ = validate_rule_data(_rule_data({"cooldown_minutes": 60}))
        assert "Cooldown scope" not in message

    def test_unknown_scope_is_rejected(self):
        ok, message, _ = validate_rule_data(_rule_data({"cooldown_minutes": 60,
                                                        "cooldown_scope": "per_moon_phase"}))
        assert ok is False
        assert "Cooldown scope" in message
        # the message names the accepted values, so the API answer is actionable
        assert "container" in message and "rule" in message
