# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Coverage Push v3                                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Coverage Push v3 — close gaps in five modules without touching production
code or sys.modules:

* ``services.donation.notification_service``  (37 LOC, 0% → 90%+)
* ``services.docker_service.server_order``    (47 LOC, 30% → 85%+)
* ``services.automation.auto_action_config_service``
                                              (321 LOC; supplements
                                               test_automation_full.py)
* ``services.donation.donation_management_service``
                                              (232 LOC, 60% → 85%+)
* ``app.blueprints.automation_routes``         (140 LOC, 69% → 85%+)

Strategy
--------
Each module is exercised against a sandboxed filesystem (tmp_path) and the
relevant collaborators are mocked via ``monkeypatch`` so no Docker daemon,
no real Discord bot, and no real /Volumes/appdata config files are touched.

We *never* mutate ``sys.modules``.

Compatibility shim
------------------
Several modules pulled in via the donation/mech import chain use
``@dataclass(frozen=True, slots=True)`` which Python 3.9 rejects with
``TypeError`` at class-body execution. We patch ``dataclasses.dataclass``
once at module-load time to silently strip ``slots`` so collection works
on the local Python 3.9 interpreter as well as 3.10+. (test-only shim,
mirrors test_main_automation_security_routes.py).
"""

from __future__ import annotations

# --- Python 3.9 compatibility shim: strip slots= from dataclass --------------
import dataclasses as _dc

if not hasattr(_dc, "_DDC_SLOTS_PATCHED"):
    _orig_dataclass = _dc.dataclass

    def _patched_dataclass(*args, **kwargs):
        kwargs.pop("slots", None)
        return _orig_dataclass(*args, **kwargs)

    _dc.dataclass = _patched_dataclass  # type: ignore[assignment]
    _dc._DDC_SLOTS_PATCHED = True  # type: ignore[attr-defined]
# -----------------------------------------------------------------------------

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. services.donation.notification_service
# ===========================================================================

class TestDonationNotificationService:
    """Cover all branches of DonationNotificationService."""

    def _svc(self, path):
        from services.donation.notification_service import (
            DonationNotificationService,
        )
        return DonationNotificationService(notification_path=str(path))

    def test_no_file_returns_none(self, tmp_path):
        svc = self._svc(tmp_path / "missing.json")
        assert svc.check_and_retrieve_notification() is None

    def test_reads_and_deletes_notification(self, tmp_path):
        notif = tmp_path / "donation_notification.json"
        payload = {"donor": "Alice", "amount": 50}
        notif.write_text(json.dumps(payload), encoding="utf-8")

        svc = self._svc(notif)
        result = svc.check_and_retrieve_notification()

        assert result == payload
        # File deleted after read
        assert not notif.exists()

    def test_invalid_json_returns_none_and_deletes(self, tmp_path):
        notif = tmp_path / "broken.json"
        notif.write_text("{not valid json", encoding="utf-8")

        svc = self._svc(notif)
        result = svc.check_and_retrieve_notification()

        assert result is None
        # Corrupted file is best-effort removed
        assert not notif.exists()

    def test_unlink_failure_returns_none(self, tmp_path, monkeypatch):
        notif = tmp_path / "delete-fail.json"
        notif.write_text(json.dumps({"x": 1}), encoding="utf-8")

        svc = self._svc(notif)

        # Force unlink to fail. Patch the bound Path.unlink at instance level.
        original_unlink = type(svc.notification_file).unlink

        def _raise(self_path, *a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(type(svc.notification_file), "unlink", _raise)
        try:
            assert svc.check_and_retrieve_notification() is None
        finally:
            monkeypatch.setattr(
                type(svc.notification_file), "unlink", original_unlink
            )

    def test_singleton_factory_returns_same_instance(self, monkeypatch):
        from services.donation import notification_service as ns

        monkeypatch.setattr(ns, "_service", None)
        s1 = ns.get_donation_notification_service()
        s2 = ns.get_donation_notification_service()
        assert s1 is s2
        assert isinstance(s1, ns.DonationNotificationService)


# ===========================================================================
# 2. services.docker_service.server_order
# ===========================================================================

class TestServerOrder:
    """Cover save / load / update_from_config branches."""

    def _redirect(self, monkeypatch, target_file: Path):
        """Repoint the module-level ORDER_FILE to a sandboxed path."""
        from services.docker_service import server_order as so

        monkeypatch.setattr(so, "ORDER_FILE", target_file)
        return so

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        order_file = tmp_path / "order_dir" / "server_order.json"
        so = self._redirect(monkeypatch, order_file)

        order = ["alpha", "beta", "gamma"]
        assert so.save_server_order(order) is True
        assert order_file.exists()
        loaded = json.loads(order_file.read_text())
        assert loaded == {"server_order": order}

        # Round-trip through load_server_order
        assert so.load_server_order() == order

    def test_load_returns_empty_when_missing(self, tmp_path, monkeypatch):
        order_file = tmp_path / "no" / "server_order.json"
        so = self._redirect(monkeypatch, order_file)
        assert so.load_server_order() == []

    def test_load_returns_empty_on_corrupt(self, tmp_path, monkeypatch):
        order_file = tmp_path / "broken.json"
        order_file.write_text("not-json")
        so = self._redirect(monkeypatch, order_file)
        assert so.load_server_order() == []

    def test_save_failure_returns_false(self, tmp_path, monkeypatch):
        # Repoint to a path under a non-creatable parent (a file used as
        # parent dir => makedirs raises). We simulate by patching
        # ``os.makedirs`` to raise.
        order_file = tmp_path / "x" / "server_order.json"
        so = self._redirect(monkeypatch, order_file)

        def _raise(*a, **kw):
            raise OSError("read only fs")

        monkeypatch.setattr("services.docker_service.server_order.os.makedirs", _raise)
        assert so.save_server_order(["a"]) is False

    def test_update_from_config_with_explicit_order(self, tmp_path, monkeypatch):
        order_file = tmp_path / "server_order.json"
        so = self._redirect(monkeypatch, order_file)
        cfg = {"server_order": ["x", "y"]}
        assert so.update_server_order_from_config(cfg) is True
        assert json.loads(order_file.read_text()) == {"server_order": ["x", "y"]}

    def test_update_from_config_falls_back_to_servers(
        self, tmp_path, monkeypatch
    ):
        order_file = tmp_path / "server_order.json"
        so = self._redirect(monkeypatch, order_file)

        # Stub the server config service to provide servers
        fake_svc = MagicMock()
        fake_svc.get_all_servers.return_value = [
            {"docker_name": "nginx"},
            {"docker_name": "redis"},
            {"docker_name": ""},  # filtered out
            {},  # filtered out
        ]
        monkeypatch.setattr(
            "services.docker_service.server_order.get_server_config_service",
            lambda: fake_svc,
        )
        assert so.update_server_order_from_config({}) is True
        loaded = json.loads(order_file.read_text())
        assert loaded == {"server_order": ["nginx", "redis"]}

    def test_update_from_config_handles_exception(self, tmp_path, monkeypatch):
        so = self._redirect(monkeypatch, tmp_path / "order.json")

        def _boom():
            raise RuntimeError("svc down")

        monkeypatch.setattr(
            "services.docker_service.server_order.get_server_config_service",
            _boom,
        )
        # config without server_order triggers fallback branch
        assert so.update_server_order_from_config({}) is False


# ===========================================================================
# 3. services.automation.auto_action_config_service — supplemental coverage
# ===========================================================================
#
# test_automation_full.py already covers most of this module. We add a few
# tests around branches/edge cases that were not covered there:
#  * sanitize_string with very long oversized input
#  * validate_rule_data with too-many keywords / too-long keyword
#  * validate_rule_data with invalid notification_channel_id
#  * validate_rule_data with ALL containers required when action != NOTIFY
#  * validate_rule_data with bad allowed_user_ids
# These hit lines that are otherwise un-exercised.

from services.automation.auto_action_config_service import (  # noqa: E402
    sanitize_string,
    validate_rule_data,
    validate_discord_snowflake,
    validate_regex_pattern,
    AutoActionConfigService,
)


def _valid_rule_payload(**overrides):
    payload = {
        "name": "Restart on Crash",
        "enabled": True,
        "priority": 10,
        "trigger": {
            "channel_ids": ["123456789012345678"],
            "keywords": ["crash"],
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
    payload.update(overrides)
    return payload


class TestAutoActionConfigSupplemental:

    def test_sanitize_string_handles_oversized_input(self):
        # 5x the limit; ensures both the truncate and final clip branches
        out = sanitize_string("z" * 5000, max_length=50)
        assert len(out) <= 50

    def test_sanitize_string_strips_brackets_only(self):
        # Final length limit of 100 default is plenty
        out = sanitize_string("<script>x()</script>", max_length=100)
        assert "<" not in out and ">" not in out
        assert "script" in out

    def test_validate_too_many_keywords(self):
        payload = _valid_rule_payload()
        payload["trigger"]["keywords"] = [f"k{i}" for i in range(60)]
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "Too many keywords" in err

    def test_validate_keyword_too_long(self):
        payload = _valid_rule_payload()
        payload["trigger"]["keywords"] = ["x" * 200]
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "Keyword too long" in err

    def test_validate_invalid_notification_channel_id(self):
        payload = _valid_rule_payload()
        payload["action"]["notification_channel_id"] = "not-a-snowflake"
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "Notification Channel ID" in err

    def test_validate_action_requires_containers(self):
        payload = _valid_rule_payload()
        payload["action"]["containers"] = []  # empty
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "target container" in err.lower()

    def test_validate_notify_action_does_not_require_containers(self):
        payload = _valid_rule_payload()
        payload["action"]["type"] = "NOTIFY"
        payload["action"]["containers"] = []
        ok, err, _ = validate_rule_data(payload)
        assert ok is True, err

    def test_validate_invalid_user_id(self):
        payload = _valid_rule_payload()
        payload["trigger"]["source_filter"] = {
            "allowed_user_ids": ["12"],  # too short
            "allowed_usernames": [],
            "is_webhook": None,
        }
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "User ID" in err

    def test_validate_long_name_fails(self):
        payload = _valid_rule_payload()
        payload["name"] = "X" * 200
        ok, err, _ = validate_rule_data(payload)
        assert ok is False
        assert "name too long" in err.lower()

    def test_validate_regex_compile_error(self):
        # Use a pattern that doesn't match the dangerous-pattern heuristics
        # but fails to compile (unterminated character set).
        ok, err = validate_regex_pattern("[")
        assert ok is False
        assert "Invalid regex" in err

    def test_save_config_atomic_rename_failure(self, tmp_path, monkeypatch):
        """Trigger the exception branch in _save_config_file (line 383-389)."""
        svc = AutoActionConfigService.__new__(AutoActionConfigService)
        svc.base_dir = tmp_path
        svc.config_file = tmp_path / "config" / "auto_actions.json"
        svc.config_file.parent.mkdir(parents=True, exist_ok=True)
        svc.config_file.write_text("{}")

        # mkstemp succeeds but os.fsync raises -> hit exception branch
        original_fsync = __import__("os").fsync

        def _raise_fsync(*a, **kw):
            raise OSError("fsync failed")

        monkeypatch.setattr("services.automation.auto_action_config_service.os.fsync", _raise_fsync)
        ok = svc._save_config_file({"global_settings": {}, "auto_actions": []})
        assert ok is False


# ===========================================================================
# 4. services.donation.donation_management_service — uncovered branches
# ===========================================================================
#
# The existing test_donation_management_service.py covers the happy path
# and basic deletion. We add tests for the alternative event types,
# deletion-toggle restore semantics, the IOError/JSONDecodeError handlers,
# and the get_donation_stats deleted-toggle branch.

from services.donation.donation_management_service import (  # noqa: E402
    DonationManagementService,
    DonationStats,
)


def _write_event_log(path: Path, events):
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def _make_paths(event_log: Path):
    return SimpleNamespace(event_log=event_log)


def _mech_state_result(total_donated=0.0, level=1, success=True):
    return SimpleNamespace(
        success=success, total_donated=total_donated, level=level
    )


@pytest.fixture
def event_log_path(tmp_path):
    return tmp_path / "events.jsonl"


@pytest.fixture
def patch_progress_paths(event_log_path):
    with patch(
        "services.donation.donation_management_service.get_progress_paths",
        return_value=_make_paths(event_log_path),
    ) as mock:
        yield mock


@pytest.fixture
def patch_mech_service():
    with patch("services.mech.mech_service.get_mech_service") as mock:
        yield mock


class TestDonationHistoryAlternativeTypes:
    """Cover PowerGiftGranted / SystemDonationAdded / ExactHitBonusGranted
    branches in get_donation_history (lines 117-160)."""

    def test_power_gift_default_name(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "PowerGiftGranted",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"campaign_id": "winter-2025", "power_units": 5000},
            }
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_history()
        assert result.success is True
        d = result.data["donations"][0]
        assert d["donation_type"] == "power_gift"
        assert "Power Gift" in d["donor_name"]
        assert d["amount"] == 50.0

    def test_power_gift_startup_campaign_uses_welcome_label(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "PowerGiftGranted",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"campaign_id": "startup-bonus", "power_units": 1000},
            }
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_history()
        assert result.success is True
        d = result.data["donations"][0]
        assert "Welcome" in d["donor_name"]

    def test_system_donation_event_renders(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "SystemDonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"event_name": "Birthday Boost", "power_units": 7500},
            }
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_history()
        assert result.success is True
        d = result.data["donations"][0]
        assert d["donation_type"] == "system"
        assert "Birthday Boost" in d["donor_name"]
        assert d["amount"] == 75.0

    def test_exact_hit_bonus_renders_with_levels(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "ExactHitBonusGranted",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"from_level": 5, "to_level": 6, "power_units": 250},
            }
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_history()
        assert result.success is True
        d = result.data["donations"][0]
        assert d["donation_type"] == "exact_hit_bonus"
        assert "Level 5" in d["donor_name"] and "6" in d["donor_name"]

    def test_donation_with_deletion_marks_deleted(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            },
            {
                "seq": 2,
                "type": "DonationDeleted",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {
                    "deleted_seq": 1,
                    "donor": "Alice",
                    "units": 5000,
                    "reason": "user-request",
                },
            },
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_history()
        assert result.success is True
        donations = result.data["donations"]

        original = next(d for d in donations if d.get("seq") == 1)
        assert original["is_deleted"] is True
        # Deletion event should also appear flat in the list right after
        deletion_items = [d for d in donations if d.get("is_deletion")]
        assert len(deletion_items) == 1
        assert deletion_items[0]["deleted_seq"] == 1

    def test_donation_with_double_deletion_restores(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            },
            {
                "seq": 2,
                "type": "DonationDeleted",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"deleted_seq": 1, "donor": "Alice", "units": 5000},
            },
            {
                "seq": 3,
                "type": "DonationDeleted",
                "ts": "2025-01-01T12:00:00Z",
                "payload": {"deleted_seq": 1, "donor": "Alice", "units": 5000},
            },
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_history()
        assert result.success is True
        donations = result.data["donations"]

        original = next(d for d in donations if d.get("seq") == 1)
        # Two deletions toggle back to active
        assert original["is_deleted"] is False
        # Stats include the (still-active) donation
        assert result.data["stats"].total_power == pytest.approx(50.0)


class TestDeleteDonationBranches:

    def test_delete_donation_no_event_log(self, tmp_path, patch_progress_paths):
        # event_log fixture path does not exist
        result = DonationManagementService().delete_donation(0)
        assert result.success is False
        assert "Event log not found" in result.error

    def test_restore_via_delete_donation_on_deletion_event(
        self, patch_progress_paths, event_log_path
    ):
        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            },
            {
                "seq": 2,
                "type": "DonationDeleted",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"deleted_seq": 1, "donor": "Alice", "units": 5000},
            },
        ]
        _write_event_log(event_log_path, events)

        progress = MagicMock()
        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress,
        ):
            # display_list = [DonationAdded(1), DonationDeleted(2)]
            #   index 1 = the deletion; selecting it triggers a "restore"
            result = DonationManagementService().delete_donation(1)

        assert result.success is True
        assert result.data["action"] == "Restored"
        # The 'target_seq' should be the deleted_seq (the original donation)
        progress.delete_donation.assert_called_once_with(1)

    def test_delete_donation_runtime_error(
        self, patch_progress_paths, event_log_path
    ):
        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            }
        ]
        _write_event_log(event_log_path, events)

        progress = MagicMock()
        progress.delete_donation.side_effect = RuntimeError("backend down")
        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress,
        ):
            result = DonationManagementService().delete_donation(0)

        assert result.success is False
        assert "progress service" in result.error.lower()

    def test_delete_donation_negative_index(
        self, patch_progress_paths, event_log_path
    ):
        _write_event_log(event_log_path, [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "X", "units": 100},
            }
        ])
        result = DonationManagementService().delete_donation(-5)
        assert result.success is False
        assert "Invalid index" in result.error

    def test_delete_donation_corrupt_jsonl(
        self, patch_progress_paths, event_log_path
    ):
        # Write invalid JSON line so json.loads raises. ``json.JSONDecodeError``
        # subclasses ``ValueError``, so the production code's
        # ``except ValueError`` handler (line 339) catches it first.
        event_log_path.write_text("{not-json\n")
        result = DonationManagementService().delete_donation(0)
        assert result.success is False
        assert result.error is not None and len(result.error) > 0


class TestDonationStatsBranches:

    def test_stats_mech_failure_returns_failure(
        self, patch_mech_service, patch_progress_paths
    ):
        # Mech service returns success=False
        mech = MagicMock()
        mech.get_mech_state_service.return_value = SimpleNamespace(
            success=False, total_donated=0.0, level=1
        )
        patch_mech_service.return_value = mech

        result = DonationManagementService().get_donation_stats()
        assert result.success is False

    def test_stats_history_mech_failure_returns_failure(
        self, patch_mech_service, patch_progress_paths
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = SimpleNamespace(
            success=False, total_donated=0.0, level=1
        )
        patch_mech_service.return_value = mech

        result = DonationManagementService().get_donation_history()
        assert result.success is False

    def test_stats_with_power_gifts_and_deletion_toggle(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(75.0)
        patch_mech_service.return_value = mech

        events = [
            {
                "seq": 1,
                "type": "DonationAdded",
                "ts": "2025-01-01T10:00:00Z",
                "payload": {"donor": "Alice", "units": 5000},
            },
            {
                "seq": 2,
                "type": "PowerGiftGranted",
                "ts": "2025-01-01T11:00:00Z",
                "payload": {"campaign_id": "winter", "power_units": 2500},
            },
            {
                "seq": 3,
                "type": "DonationDeleted",
                "ts": "2025-01-01T12:00:00Z",
                "payload": {"deleted_seq": 1, "donor": "Alice", "units": 5000},
            },
        ]
        _write_event_log(event_log_path, events)

        result = DonationManagementService().get_donation_stats()
        assert result.success is True
        stats = result.data
        # Donation seq=1 was deleted (odd toggle) -> excluded from total
        # Only PowerGift (25.0) remains
        assert stats.total_power == pytest.approx(25.0)
        assert stats.total_donations == 1
        assert stats.average_donation == pytest.approx(25.0)

    def test_stats_corrupt_jsonl_returns_failure(
        self, patch_mech_service, patch_progress_paths, event_log_path
    ):
        mech = MagicMock()
        mech.get_mech_state_service.return_value = _mech_state_result(0.0)
        patch_mech_service.return_value = mech
        event_log_path.write_text("{not-json")
        result = DonationManagementService().get_donation_stats()
        assert result.success is False


class TestDonationManagementSingleton:

    def test_singleton_factory(self, monkeypatch):
        from services.donation import donation_management_service as dms

        monkeypatch.setattr(dms, "_donation_management_service", None)
        s1 = dms.get_donation_management_service()
        s2 = dms.get_donation_management_service()
        assert s1 is s2

    def test_donation_stats_from_data_classmethod_paths(self):
        # Already covered elsewhere but exercise both branches one more time
        s_empty = DonationStats.from_data([], 0.0)
        assert s_empty.average_donation == 0.0

        s_pop = DonationStats.from_data([{"amount": 10}], 10.0)
        assert s_pop.average_donation == 10.0


# ===========================================================================
# 5. app.blueprints.automation_routes — branches not covered by
#    test_main_automation_security_routes.py
# ===========================================================================

_AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(b"admin:test").decode(),
}


def _stub_auth(monkeypatch):
    from app import auth as auth_module
    from flask import jsonify as _jsonify

    def _verify(username, password):
        if username and password:
            return "admin"
        return None

    monkeypatch.setattr(auth_module.auth, "verify_password_callback", _verify)

    def _err(status):
        resp = _jsonify(message="Authentication Required")
        resp.status_code = status
        return resp

    monkeypatch.setattr(auth_module.auth, "auth_error_callback", _err)


@pytest.fixture
def automation_app(monkeypatch):
    """Minimal Flask app with the automation blueprint mounted."""
    _stub_auth(monkeypatch)

    from flask import Flask
    from app.blueprints.automation_routes import automation_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-coverage-push-v3"
    app.register_blueprint(automation_bp)
    return app


class TestAutomationRoutesExtras:

    def test_test_rule_returns_matches(self, automation_app, monkeypatch):
        """Cover the 200-response path of /api/automation/test."""
        # Build a fake rule object whose attributes the route uses
        rule = SimpleNamespace(
            id="r1",
            name="Test Rule",
            action=SimpleNamespace(type="RESTART", containers=["nginx"]),
        )
        cfg = MagicMock()
        cfg.get_rules.return_value = [rule]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )

        async def _check_match(rule, ctx):
            return True, "matched keyword"

        auto_svc = MagicMock()
        auto_svc._pre_filter_rules.return_value = [rule]
        auto_svc._check_match = _check_match
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_automation_service",
            lambda: auto_svc,
        )

        resp = automation_app.test_client().post(
            "/api/automation/test",
            json={
                "content": "system crash detected and restarting",
                "channel_id": "123",
                "user_id": "456",
            },
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["matches"][0]["matched"] is True
        assert body["matches"][0]["rule_name"] == "Test Rule"
        assert body["matches"][0]["would_execute"] == "RESTART"

    def test_test_rule_async_check_returns_no_match(
        self, automation_app, monkeypatch
    ):
        rule = SimpleNamespace(
            id="r1",
            name="Test Rule",
            action=SimpleNamespace(type="NOTIFY", containers=[]),
        )
        cfg = MagicMock()
        cfg.get_rules.return_value = [rule]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )

        async def _check_match(rule, ctx):
            return False, ""

        auto_svc = MagicMock()
        auto_svc._pre_filter_rules.return_value = [rule]
        auto_svc._check_match = _check_match
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_automation_service",
            lambda: auto_svc,
        )

        resp = automation_app.test_client().post(
            "/api/automation/test",
            json={"content": "irrelevant"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["matches"][0]["matched"] is False
        assert "Keywords/Regex" in body["matches"][0]["reason"]

    def test_test_rule_handles_exception(self, automation_app, monkeypatch):
        """Cover the generic-error 500 branch.

        The ``try/except`` in test_rule wraps the asyncio.run() block, not
        the synchronous setup. We trigger the failure inside _check_match
        (which runs inside asyncio.run) so the Exception lands in the
        500-error branch (line 204-207).
        """
        rule = SimpleNamespace(
            id="r1",
            name="Buggy Rule",
            action=SimpleNamespace(type="RESTART", containers=["nginx"]),
        )
        cfg = MagicMock()
        cfg.get_rules.return_value = [rule]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )

        async def _check_match(rule, ctx):
            raise ValueError("simulated check_match failure")

        auto_svc = MagicMock()
        auto_svc._pre_filter_rules.return_value = [rule]
        auto_svc._check_match = _check_match
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_automation_service",
            lambda: auto_svc,
        )

        resp = automation_app.test_client().post(
            "/api/automation/test",
            json={"content": "anything"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert "internal error" in resp.get_json()["error"].lower()

    def test_channels_returns_data_when_bot_has_guilds(
        self, automation_app, monkeypatch
    ):
        """Cover the channel-iteration branch of GET /api/automation/channels."""
        import discord

        # Two text channels + one non-text channel that should be filtered
        text_channel_a = MagicMock(spec=discord.TextChannel)
        text_channel_a.id = 111
        text_channel_a.name = "general"
        text_channel_a.permissions_for.return_value = SimpleNamespace(
            read_messages=True
        )

        text_channel_b = MagicMock(spec=discord.TextChannel)
        text_channel_b.id = 222
        text_channel_b.name = "logs"
        text_channel_b.permissions_for.return_value = SimpleNamespace(
            read_messages=False  # filtered out
        )

        # Some non-text channel — must not be a TextChannel instance
        non_text = MagicMock()  # not a TextChannel — isinstance check fails

        guild = MagicMock()
        guild.id = 999
        guild.name = "Guild A"
        guild.me = MagicMock()
        guild.channels = [text_channel_a, text_channel_b, non_text]

        bot = MagicMock()
        bot.guilds = [guild]

        monkeypatch.setattr(
            "services.scheduling.donation_message_service.get_bot_instance",
            lambda: bot,
        )

        resp = automation_app.test_client().get(
            "/api/automation/channels", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "channels" in body
        # Only the readable text channel survives
        assert len(body["channels"]) == 1
        assert body["channels"][0]["id"] == "111"
        assert body["channels"][0]["guild_id"] == "999"

    def test_channels_skips_guilds_with_no_me(
        self, automation_app, monkeypatch
    ):
        """guild.me is None → skip iteration (line 240-241)."""
        guild = MagicMock()
        guild.me = None
        guild.channels = []

        bot = MagicMock()
        bot.guilds = [guild]

        monkeypatch.setattr(
            "services.scheduling.donation_message_service.get_bot_instance",
            lambda: bot,
        )

        resp = automation_app.test_client().get(
            "/api/automation/channels", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json()["channels"] == []

    def test_channels_returns_error_on_exception(
        self, automation_app, monkeypatch
    ):
        """Cover the exception branch of get_channels (line 260-264)."""
        def _boom():
            raise RuntimeError("bot factory crashed")

        monkeypatch.setattr(
            "services.scheduling.donation_message_service.get_bot_instance",
            _boom,
        )

        resp = automation_app.test_client().get(
            "/api/automation/channels", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200  # returns empty + error key
        body = resp.get_json()
        assert body["channels"] == []
        assert "error" in body


# ===========================================================================
# 5b. automation_routes — basic CRUD coverage (when run without
#    test_main_automation_security_routes.py the user's verify command
#    only includes test_coverage_push_v3.py + the two service tests, so
#    we duplicate enough route coverage here to push the blueprint
#    above 85%.)
# ===========================================================================

class TestAutomationRoutesCRUD:
    """Cover the rule-management / settings / history routes."""

    def test_get_rules_unauth_401(self, automation_app):
        resp = automation_app.test_client().get("/api/automation/rules")
        assert resp.status_code == 401

    def test_get_rules_serializes(self, automation_app, monkeypatch):
        rule = MagicMock()
        rule.to_dict.return_value = {"id": "r1", "name": "Rule 1"}
        cfg = MagicMock()
        cfg.get_rules.return_value = [rule]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().get(
            "/api/automation/rules", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"rules": [{"id": "r1", "name": "Rule 1"}]}

    def test_create_rule_success(self, automation_app, monkeypatch):
        new_rule = MagicMock()
        new_rule.to_dict.return_value = {"id": "new", "name": "New"}
        cfg = MagicMock()
        cfg.add_rule.return_value = SimpleNamespace(
            success=True, data=new_rule, error=None
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules", json={"name": "New"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["rule"]["id"] == "new"

    def test_create_rule_validation_400(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.add_rule.return_value = SimpleNamespace(
            success=False, data=None, error="bad input"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules", json={"foo": "bar"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"success": False, "error": "bad input"}

    def test_update_rule_success(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_rule.return_value = SimpleNamespace(success=True, error=None)
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().put(
            "/api/automation/rules/r1", json={"x": 1}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 200

    def test_update_rule_failure(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_rule.return_value = SimpleNamespace(
            success=False, error="missing"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().put(
            "/api/automation/rules/r1", json={}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400

    def test_delete_rule_success(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.delete_rule.return_value = SimpleNamespace(success=True, error=None)
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().delete(
            "/api/automation/rules/r1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200

    def test_delete_rule_failure(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.delete_rule.return_value = SimpleNamespace(
            success=False, error="not found"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().delete(
            "/api/automation/rules/r1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


class TestAutomationRoutesToggle:

    def test_toggle_unknown_404(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.get_rule.return_value = None
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules/missing/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_toggle_flips_enabled(self, automation_app, monkeypatch):
        rule = MagicMock()
        rule.to_dict.return_value = {"id": "r1", "enabled": True}
        cfg = MagicMock()
        cfg.get_rule.return_value = rule
        cfg.update_rule.return_value = SimpleNamespace(success=True, error=None)
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules/r1/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["enabled"] is False  # flipped

    def test_toggle_update_failure_400(self, automation_app, monkeypatch):
        rule = MagicMock()
        rule.to_dict.return_value = {"id": "r1", "enabled": False}
        cfg = MagicMock()
        cfg.get_rule.return_value = rule
        cfg.update_rule.return_value = SimpleNamespace(
            success=False, error="db locked"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules/r1/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


class TestAutomationRoutesSettings:

    def test_get_settings(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.get_global_settings.return_value = {"enabled": True}
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().get(
            "/api/automation/settings", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"enabled": True}

    def test_update_settings_success(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_global_settings.return_value = SimpleNamespace(
            success=True, error=None
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/settings",
            json={"enabled": False},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200

    def test_update_settings_failure_400(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_global_settings.return_value = SimpleNamespace(
            success=False, error="bad"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/settings", json={}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


class TestAutomationRoutesHistory:

    def test_history_default_limit(self, automation_app, monkeypatch):
        state = MagicMock()
        state.get_history.return_value = [{"id": 1}]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_state_service",
            lambda: state,
        )
        resp = automation_app.test_client().get(
            "/api/automation/history", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"history": [{"id": 1}]}
        state.get_history.assert_called_once_with(None, 50)

    def test_history_invalid_limit_falls_back(self, automation_app, monkeypatch):
        state = MagicMock()
        state.get_history.return_value = []
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_state_service",
            lambda: state,
        )
        resp = automation_app.test_client().get(
            "/api/automation/history?limit=not-a-number&container=foo",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        state.get_history.assert_called_once_with("foo", 50)

    def test_history_clamps_high_limit(self, automation_app, monkeypatch):
        state = MagicMock()
        state.get_history.return_value = []
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_state_service",
            lambda: state,
        )
        resp = automation_app.test_client().get(
            "/api/automation/history?limit=10000", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        state.get_history.assert_called_once_with(None, 500)


class TestAutomationTestRouteEdgeCases:

    def test_test_rule_missing_body_400(self, automation_app):
        resp = automation_app.test_client().post(
            "/api/automation/test",
            data=b"",
            headers={**_AUTH_HEADER, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
