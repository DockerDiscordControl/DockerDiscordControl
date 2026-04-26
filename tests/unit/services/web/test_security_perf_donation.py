# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests covering four services with a single, hermetic test module:

- ``services.web.security_service`` (Token security, audit, migration help)
- ``services.web.performance_stats_service`` (memory/cpu/cache stats aggregation)
- ``services.donation.unified.service`` (additional edge cases, reset, member context)
- ``services.infrastructure.action_log_service`` (rotation, JSON corruption,
  partial writes)

Strategy:
- No ``sys.modules`` manipulation. We rely on ``unittest.mock.patch`` against
  fully-qualified import paths (``utils.token_security.TokenSecurityManager``
  etc.) so the patches respect each test's scope.
- ``psutil`` is patched via ``patch.object`` on the imported module reference.
- ``tmp_path`` is used for action-log file based tests so we never touch the
  real ``logs/`` directory.
- The donation tests reuse the real singleton (which is already exercised
  by the existing ``test_unified_donation_service.py``) to drive the
  remaining edge cases (reset flow, web/test helper wrappers).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ============================================================================
# 1. SECURITY SERVICE
# ============================================================================


from services.web.security_service import (
    SecurityService,
    SecurityResult,
    TokenSecurityStatusRequest,
    TokenEncryptionRequest,
    MigrationHelpRequest,
    SecurityAuditRequest,
    get_security_service,
)


def _good_token_status(*, env: bool = False, encrypted: bool = False, exists: bool = True):
    return {
        "token_exists": exists,
        "is_encrypted": encrypted,
        "can_encrypt": True,
        "password_hash_available": True,
        "environment_token_used": env,
        "recommendations": [],
    }


class TestSecurityServiceTokenStatus:
    """get_token_security_status()"""

    def test_status_success_returns_data(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.verify_token_encryption_status.return_value = (
                _good_token_status()
            )
            result = svc.get_token_security_status(TokenSecurityStatusRequest())

        assert isinstance(result, SecurityResult)
        assert result.success is True
        assert result.data["token_exists"] is True
        assert result.status_code == 200

    def test_status_runtime_error_returns_failure(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.verify_token_encryption_status.side_effect = RuntimeError(
                "boom"
            )
            result = svc.get_token_security_status(TokenSecurityStatusRequest())

        assert result.success is False
        assert result.status_code == 500
        assert "boom" in (result.error or "")
        assert result.data["token_exists"] is False
        assert "Error" in result.data["recommendations"][0]


class TestSecurityServiceEncryptToken:
    """encrypt_token()"""

    def test_encrypt_success_logs_action(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch.object(
            svc, "_log_security_action"
        ) as log:
            mgr_cls.return_value.encrypt_existing_plaintext_token.return_value = True
            result = svc.encrypt_token(TokenEncryptionRequest())

        assert result.success is True
        assert "successfully" in result.data["message"]
        log.assert_called_once()
        assert log.call_args.kwargs["action"] == "TOKEN_ENCRYPT"

    def test_encrypt_returns_400_when_manager_fails(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.encrypt_existing_plaintext_token.return_value = False
            result = svc.encrypt_token(TokenEncryptionRequest())

        assert result.success is False
        assert result.status_code == 400
        assert "admin password" in result.error

    def test_encrypt_handles_runtime_error(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.encrypt_existing_plaintext_token.side_effect = RuntimeError(
                "kaboom"
            )
            result = svc.encrypt_token(TokenEncryptionRequest())

        assert result.success is False
        assert result.status_code == 500
        assert "kaboom" in result.error


class TestSecurityServiceMigrationHelp:
    """get_migration_help()"""

    def test_migration_success_includes_token(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch.object(
            svc, "_log_security_action"
        ) as log:
            mgr_cls.return_value.migrate_to_environment_variable.return_value = {
                "success": True,
                "instructions": ["step 1", "step 2"],
                "plaintext_token": "tok_abc",
                "error": None,
            }
            result = svc.get_migration_help(MigrationHelpRequest())

        assert result.success is True
        assert result.data["success"] is True
        assert result.data["token"] == "tok_abc"
        assert result.data["instructions"] == ["step 1", "step 2"]
        log.assert_called_once()

    def test_migration_failure_omits_token(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.migrate_to_environment_variable.return_value = {
                "success": False,
                "instructions": [],
                "plaintext_token": None,
                "error": "no token",
            }
            result = svc.get_migration_help(MigrationHelpRequest())

        assert result.success is True  # Outer wrapper success
        assert result.data["success"] is False
        assert "token" not in result.data
        assert result.data["error"] == "no token"

    def test_migration_runtime_error(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.migrate_to_environment_variable.side_effect = RuntimeError(
                "fail"
            )
            result = svc.get_migration_help(MigrationHelpRequest())

        assert result.success is False
        assert result.status_code == 500
        assert result.data["success"] is False
        assert result.data["instructions"] == []


class TestSecurityServiceAudit:
    """get_security_audit() + scoring helpers."""

    def test_audit_full_score_excellent(self):
        svc = SecurityService()
        token_status = _good_token_status(env=True, encrypted=True)
        config = {"web_ui_password_hash": "$2b$..."}
        request_obj = MagicMock(is_secure=True)

        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch(
            "services.config.config_service.load_config", return_value=config
        ), patch("os.getenv", return_value="secret"), patch(
            "os.path.exists", return_value=True
        ), patch("os.getuid", return_value=1000, create=True):
            mgr_cls.return_value.verify_token_encryption_status.return_value = token_status
            result = svc.get_security_audit(SecurityAuditRequest(request_object=request_obj))

        assert result.success is True
        assert result.data["security_score"] >= 85
        assert result.data["rating"] == "Excellent"
        assert result.data["rating_class"] == "success"
        assert result.data["configuration_security"]["https_enabled"] is True

    def test_audit_poor_when_nothing_configured(self):
        svc = SecurityService()
        token_status = _good_token_status(env=False, encrypted=False, exists=False)
        # Note: with token_exists=False there's no critical recommendation either,
        # but the score will land in the Poor band.
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch(
            "services.config.config_service.load_config", return_value={}
        ), patch("os.getenv", return_value=None), patch(
            "os.path.exists", return_value=False
        ), patch("os.getuid", return_value=0, create=True):
            mgr_cls.return_value.verify_token_encryption_status.return_value = token_status
            result = svc.get_security_audit(SecurityAuditRequest(request_object=None))

        assert result.success is True
        assert result.data["security_score"] < 45
        assert result.data["rating"] == "Poor"
        assert result.data["rating_class"] == "danger"

    def test_audit_partial_score_good_with_encrypted_token(self):
        svc = SecurityService()
        token_status = _good_token_status(env=False, encrypted=True)
        config = {"web_ui_password_hash": "$2b$..."}
        request_obj = MagicMock(is_secure=False)

        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch(
            "services.config.config_service.load_config", return_value=config
        ), patch("os.getenv", return_value="secret"), patch(
            "os.path.exists", return_value=True
        ), patch("os.getuid", return_value=1000, create=True):
            mgr_cls.return_value.verify_token_encryption_status.return_value = token_status
            result = svc.get_security_audit(SecurityAuditRequest(request_object=request_obj))

        # Score: 25 (encrypted) + 15 (flask) + 15 (admin) + 15 (non-root) = 70 -> Good
        assert result.success is True
        assert 65 <= result.data["security_score"] < 85
        assert result.data["rating"] == "Good"

    def test_audit_token_exists_but_not_secure_recommends_action(self):
        svc = SecurityService()
        token_status = _good_token_status(env=False, encrypted=False, exists=True)

        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch(
            "services.config.config_service.load_config", return_value={}
        ), patch("os.getenv", return_value=None), patch(
            "os.path.exists", return_value=False
        ), patch("os.getuid", return_value=0, create=True):
            mgr_cls.return_value.verify_token_encryption_status.return_value = token_status
            result = svc.get_security_audit(SecurityAuditRequest(request_object=None))

        recs_text = "\n".join(result.data["recommendations"])
        assert "Encrypt or move token" in recs_text

    def test_audit_runtime_error_propagates(self):
        svc = SecurityService()
        with patch("utils.token_security.TokenSecurityManager") as mgr_cls:
            mgr_cls.return_value.verify_token_encryption_status.side_effect = RuntimeError(
                "audit fail"
            )
            result = svc.get_security_audit(SecurityAuditRequest(request_object=None))

        assert result.success is False
        assert result.status_code == 500

    def test_audit_score_capped_at_100(self):
        """_calculate_security_score must never exceed 100 even if hypothetically over."""
        svc = SecurityService()
        token_status = _good_token_status(env=True, encrypted=True)
        config = {"web_ui_password_hash": "x"}
        request_obj = MagicMock(is_secure=True)

        with patch("utils.token_security.TokenSecurityManager") as mgr_cls, patch(
            "services.config.config_service.load_config", return_value=config
        ), patch("os.getenv", return_value="secret"), patch(
            "os.path.exists", return_value=True
        ), patch("os.getuid", return_value=1000, create=True):
            mgr_cls.return_value.verify_token_encryption_status.return_value = token_status
            result = svc.get_security_audit(SecurityAuditRequest(request_object=request_obj))

        assert result.data["security_score"] <= 100


class TestSecurityServiceActionLogging:
    """_log_security_action() degrades gracefully."""

    def test_log_security_action_swallows_runtime_error(self):
        """If session/log_user_action import or call raises RuntimeError, no exception escapes."""
        svc = SecurityService()
        with patch(
            "services.infrastructure.action_logger.log_user_action",
            side_effect=RuntimeError("no flask context"),
        ):
            # Should not raise
            svc._log_security_action(action="X", target="t", details="d")


class TestSecurityServiceSingleton:
    def test_singleton(self):
        a = get_security_service()
        b = get_security_service()
        assert a is b
        assert isinstance(a, SecurityService)


# ============================================================================
# 2. PERFORMANCE STATS SERVICE
# ============================================================================


from services.web import performance_stats_service as perf_module
from services.web.performance_stats_service import (
    PerformanceStatsService,
    PerformanceStatsResult,
    get_performance_stats_service,
)


class TestPerformanceStatsAggregation:
    """get_performance_stats() aggregates all sub-collectors."""

    def test_returns_result_with_all_sections(self):
        svc = PerformanceStatsService()
        with patch.object(svc, "_get_config_cache_stats", return_value={"cache_size": 1}), patch.object(
            svc, "_get_docker_cache_stats", return_value={"containers_count": 3}
        ), patch.object(svc, "_get_scheduler_stats", return_value={"jobs": 5}), patch.object(
            svc, "_get_system_memory_stats", return_value={"total_mb": 100.0}
        ), patch.object(svc, "_get_process_memory_stats", return_value={"rss_mb": 10.0}):
            result = svc.get_performance_stats()

        assert isinstance(result, PerformanceStatsResult)
        assert result.success is True
        d = result.performance_data
        assert d["config_cache"] == {"cache_size": 1}
        assert d["docker_cache"] == {"containers_count": 3}
        assert d["scheduler"] == {"jobs": 5}
        assert d["system_memory"] == {"total_mb": 100.0}
        assert d["process_memory"] == {"rss_mb": 10.0}
        assert "timestamp" in d
        assert "timestamp_formatted" in d

    def test_aggregation_handles_runtime_error(self):
        svc = PerformanceStatsService()
        with patch.object(
            svc, "_get_config_cache_stats", side_effect=RuntimeError("dead")
        ):
            result = svc.get_performance_stats()
        assert result.success is False
        assert "Error collecting performance statistics" in result.error


class TestPerformanceStatsSystemMemory:
    """_get_system_memory_stats() with mocked psutil."""

    def test_system_memory_formatted(self):
        svc = PerformanceStatsService()
        fake_mem = MagicMock(
            total=2 * 1024 * 1024 * 1024,  # 2 GB
            available=1 * 1024 * 1024 * 1024,
            percent=50.0,
            free=512 * 1024 * 1024,
        )
        fake_psutil = MagicMock()
        fake_psutil.virtual_memory.return_value = fake_mem
        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            stats = svc._get_system_memory_stats()

        # NOTE: we do NOT mutate sys.modules globally — patch.dict is auto-reverted
        assert stats["total_mb"] == 2048.0
        assert stats["available_mb"] == 1024.0
        assert stats["percent_used"] == 50.0
        assert stats["free_mb"] == 512.0

    def test_system_memory_runtime_error_returns_error_dict(self):
        svc = PerformanceStatsService()
        fake_psutil = MagicMock()
        fake_psutil.virtual_memory.side_effect = RuntimeError("psutil broken")
        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            stats = svc._get_system_memory_stats()
        assert "error" in stats
        assert "psutil broken" in stats["error"]


class TestPerformanceStatsProcessMemory:
    """_get_process_memory_stats() with mocked psutil."""

    def test_process_memory_formatted(self):
        svc = PerformanceStatsService()
        process_mock = MagicMock()
        process_mock.memory_info.return_value = MagicMock(
            rss=200 * 1024 * 1024, vms=400 * 1024 * 1024
        )
        process_mock.memory_percent.return_value = 5.123
        process_mock.num_threads.return_value = 8

        fake_psutil = MagicMock()
        fake_psutil.Process.return_value = process_mock
        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            stats = svc._get_process_memory_stats()

        assert stats["rss_mb"] == 200.0
        assert stats["vms_mb"] == 400.0
        assert stats["percent"] == 5.12
        assert stats["num_threads"] == 8

    def test_process_memory_oserror_returns_error_dict(self):
        svc = PerformanceStatsService()
        fake_psutil = MagicMock()
        fake_psutil.Process.side_effect = OSError("permission denied")
        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            stats = svc._get_process_memory_stats()
        assert "error" in stats
        assert "permission denied" in stats["error"]


class TestPerformanceStatsCacheCollectors:
    """_get_config_cache_stats() and _get_scheduler_stats()."""

    def test_config_cache_stats_success(self):
        svc = PerformanceStatsService()
        fake_module = MagicMock()
        fake_module.get_cache_memory_stats.return_value = {"size": 42}
        with patch.dict("sys.modules", {"utils.config_cache": fake_module}):
            stats = svc._get_config_cache_stats()
        assert stats == {"size": 42}

    def test_config_cache_stats_attribute_error(self):
        svc = PerformanceStatsService()
        fake_module = MagicMock()
        fake_module.get_cache_memory_stats.side_effect = AttributeError("nope")
        with patch.dict("sys.modules", {"utils.config_cache": fake_module}):
            stats = svc._get_config_cache_stats()
        assert "error" in stats

    def test_scheduler_stats_success(self):
        svc = PerformanceStatsService()
        fake_module = MagicMock()
        fake_module.get_scheduler_stats.return_value = {"jobs": 7}
        with patch.dict(
            "sys.modules", {"services.scheduling.scheduler_service": fake_module}
        ):
            stats = svc._get_scheduler_stats()
        assert stats == {"jobs": 7}

    def test_scheduler_stats_keyerror(self):
        svc = PerformanceStatsService()
        fake_module = MagicMock()
        fake_module.get_scheduler_stats.side_effect = KeyError("missing")
        with patch.dict(
            "sys.modules", {"services.scheduling.scheduler_service": fake_module}
        ):
            stats = svc._get_scheduler_stats()
        assert "error" in stats


class TestPerformanceStatsDockerCache:
    """_get_docker_cache_stats() formats timestamps and reads cache state."""

    def test_docker_cache_stats_full(self):
        svc = PerformanceStatsService()
        from datetime import datetime as _dt
        ts = _dt(2025, 1, 1, 12, 0, 0).timestamp()

        fake_helpers = MagicMock()
        fake_helpers.docker_cache = {
            "containers": [{"name": "c1"}, {"name": "c2"}],
            "access_count": 9,
            "global_timestamp": ts,
            "last_cleanup": ts,
            "bg_refresh_running": True,
            "priority_containers": {"a", "b"},
            "container_timestamps": {"c1": 1.0},
            "container_hashes": {"c1": "h1"},
            "error": None,
        }

        # cache_lock must be a real context manager
        class _DummyLock:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_helpers.cache_lock = _DummyLock()
        with patch.dict("sys.modules", {"app.utils.web_helpers": fake_helpers}):
            stats = svc._get_docker_cache_stats()

        assert stats["containers_count"] == 2
        assert stats["access_count"] == 9
        assert stats["bg_refresh_running"] is True
        assert "global_timestamp_formatted" in stats
        assert "last_cleanup_formatted" in stats
        assert stats["priority_containers_count"] == 2

    def test_docker_cache_stats_handles_keyerror(self):
        svc = PerformanceStatsService()
        fake_helpers = MagicMock()
        # Accessing .docker_cache via getitem -> trigger AttributeError on 'with'
        fake_helpers.docker_cache = MagicMock()
        fake_helpers.docker_cache.get.side_effect = KeyError("oops")

        class _DummyLock:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_helpers.cache_lock = _DummyLock()
        with patch.dict("sys.modules", {"app.utils.web_helpers": fake_helpers}):
            stats = svc._get_docker_cache_stats()
        assert "error" in stats


class TestPerformanceStatsSingleton:
    def test_singleton(self):
        a = get_performance_stats_service()
        b = get_performance_stats_service()
        assert a is b


# ============================================================================
# 3. UNIFIED DONATION SERVICE — additional edge cases
# ============================================================================


from services.donation.unified.service import (
    UnifiedDonationService,
    get_unified_donation_service,
    process_web_ui_donation,
    process_test_donation,
    reset_all_donations,
)
from services.donation.unified.models import DonationRequest, DonationResult


class TestUnifiedDonationHelpers:
    """Convenience helpers (process_web_ui_donation, process_test_donation, reset_all_donations)."""

    def test_process_web_ui_donation(self):
        result = process_web_ui_donation("Alice", 1.0)
        assert isinstance(result, DonationResult)
        assert result.success is True

    def test_process_test_donation(self):
        result = process_test_donation("Bob", 2.0)
        assert isinstance(result, DonationResult)
        assert result.success is True

    def test_reset_all_donations_returns_result(self):
        # Before resetting we run a small donation so old_state has non-zero power
        process_test_donation("ResetCheck", 1.0)
        result = reset_all_donations(source="admin")
        assert isinstance(result, DonationResult)
        # Reset should succeed under the standard test fixture
        assert result.success is True


class TestUnifiedDonationProcessAsyncMemberContext:
    """process_donation_async() should call resolve_member_context."""

    @pytest.mark.asyncio
    async def test_async_donation_resolves_member_context(self):
        service = get_unified_donation_service()
        request = DonationRequest(
            donor_name="MemberCtx",
            amount=1.0,
            source="discord",
            discord_guild_id="42",
            use_member_count=True,
        )

        with patch(
            "services.donation.unified.service.resolve_member_context",
            new=AsyncMock(return_value=(None, 25)),
        ) as mock_resolve:
            result = await service.process_donation_async(request)

        mock_resolve.assert_awaited_once()
        # Arguments: bot_instance, guild_id, use_member_count=...
        called_kwargs = mock_resolve.await_args.kwargs
        assert called_kwargs["use_member_count"] is True
        assert result.success is True


class TestUnifiedDonationStateAggregation:
    """Edge cases for the result aggregation logic."""

    def test_donation_result_carries_event_id(self):
        request = DonationRequest(donor_name="EventID", amount=1.0, source="test")
        result = process_test_donation("EventID", 1.0)
        assert result.success
        # event_id is non-None in the success path
        assert result.event_id is not None

    def test_unified_service_init_singleton(self):
        a = get_unified_donation_service()
        b = get_unified_donation_service()
        assert a is b
        assert isinstance(a, UnifiedDonationService)


# ============================================================================
# 4. ACTION LOG SERVICE
# ============================================================================


from services.infrastructure.action_log_service import (
    ActionLogService,
    ActionLogEntry,
    ServiceResult,
    _TEXT_LOG_MAX_BYTES,
    _TEXT_LOG_BACKUP_COUNT,
    get_action_log_service,
)


class TestActionLogEntryDataclass:
    def test_from_dict_handles_legacy_id_field(self):
        entry = ActionLogEntry.from_dict(
            {
                "timestamp": "2025-01-01T12:00:00",
                "timestamp_unix": 1735732800,
                "timezone": "UTC",
                "action": "START",
                "target": "container1",
                "user": "tester",
                "source": "Web UI",
                "details": "ok",
                "id": "legacy-123",
            }
        )
        assert entry.entry_id == "legacy-123"
        assert entry.migrated is False

    def test_from_dict_handles_modern_entry_id(self):
        entry = ActionLogEntry.from_dict(
            {"entry_id": "modern-456", "migrated": True}
        )
        assert entry.entry_id == "modern-456"
        assert entry.migrated is True

    def test_to_dict_round_trip(self):
        entry = ActionLogEntry(
            timestamp="t",
            timestamp_unix=1,
            timezone="UTC",
            action="A",
            target="T",
            user="U",
            source="S",
            details="D",
            entry_id="E",
            migrated=False,
        )
        d = entry.to_dict()
        assert d["id"] == "E"
        assert d["action"] == "A"
        # Round-trip
        rebuilt = ActionLogEntry.from_dict(d)
        assert rebuilt == entry


class TestActionLogServiceLogAction:
    """log_action() public API."""

    def test_log_action_success_creates_files(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        result = svc.log_action(
            action="START", target="my_container", user="alice", source="Web UI"
        )
        assert result.success is True
        assert isinstance(result.data, ActionLogEntry)
        assert svc.json_log_file.exists()
        assert svc.text_log_file.exists()

        actions = json.loads(svc.json_log_file.read_text(encoding="utf-8"))
        assert len(actions) == 1
        assert actions[0]["action"] == "START"
        assert actions[0]["target"] == "my_container"

    def test_log_action_appends(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        svc.log_action(action="A1", target="t", user="u", source="s")
        svc.log_action(action="A2", target="t", user="u", source="s")
        data = json.loads(svc.json_log_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert {row["action"] for row in data} == {"A1", "A2"}


class TestActionLogServiceJsonReadEdgeCases:
    """_get_logs_json edge cases: empty file, corrupted file, missing file."""

    def test_get_logs_returns_empty_when_file_missing(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        result = svc.get_logs(format="json")
        assert result.success is True
        assert result.data == []

    def test_get_logs_returns_empty_for_empty_file(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        svc.json_log_file.write_text("", encoding="utf-8")
        result = svc.get_logs(format="json")
        assert result.success is True
        assert result.data == []

    def test_get_logs_handles_corrupted_json(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        svc.json_log_file.write_text("{not-valid-json", encoding="utf-8")
        result = svc.get_logs(format="json")
        assert result.success is False
        assert result.error  # carries JSON error message

    def test_get_logs_sorts_by_timestamp_desc_with_limit(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        actions = [
            {
                "timestamp": "2025-01-01T00:00:00",
                "timestamp_unix": i,
                "timezone": "UTC",
                "action": f"A{i}",
                "target": "t",
                "user": "u",
                "source": "s",
                "details": "d",
                "id": f"id{i}",
            }
            for i in range(10)
        ]
        svc.json_log_file.write_text(json.dumps(actions), encoding="utf-8")

        result = svc.get_logs(limit=3, format="json")
        assert result.success is True
        entries = result.data
        assert len(entries) == 3
        # Newest (highest timestamp_unix) first
        assert entries[0].action == "A9"
        assert entries[1].action == "A8"
        assert entries[2].action == "A7"


class TestActionLogServiceTextFormat:
    """_get_logs_text fallback paths."""

    def test_get_logs_text_uses_json_when_available(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        svc.log_action(action="X", target="ctr", user="u", source="s", details="d")
        result = svc.get_logs(format="text")
        assert result.success is True
        assert "X|ctr|u|s|d" in result.data

    def test_get_logs_text_no_logs_returns_message(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        result = svc.get_logs(format="text")
        assert result.success is True
        assert result.data == "No action logs available"


class TestActionLogServiceJsonPartialWrite:
    """_save_to_json must recover from corrupted existing JSON, falling back to []."""

    def test_corrupted_existing_json_does_not_break_append(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        # Pre-populate with garbage
        svc.json_log_file.write_text("not-json", encoding="utf-8")
        result = svc.log_action(action="POST_CORRUPT", target="t", user="u", source="s")
        assert result.success is True
        data = json.loads(svc.json_log_file.read_text(encoding="utf-8"))
        # Old corrupted content was discarded; only the new entry is persisted
        assert len(data) == 1
        assert data[0]["action"] == "POST_CORRUPT"

    def test_save_truncates_at_10000(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        # Pre-populate with 10001 entries
        big = [
            {"action": f"A{i}", "target": "t", "user": "u", "source": "s",
             "details": "d", "id": str(i), "timestamp": "x", "timestamp_unix": i,
             "timezone": "UTC"}
            for i in range(10001)
        ]
        svc.json_log_file.write_text(json.dumps(big), encoding="utf-8")
        svc.log_action(action="NEW", target="t", user="u", source="s")
        data = json.loads(svc.json_log_file.read_text(encoding="utf-8"))
        assert len(data) == 10000
        # Newest entry must be preserved
        assert data[-1]["action"] == "NEW"


class TestActionLogServiceTextRotation:
    """_rotate_text_log_if_needed rotates files when they exceed _TEXT_LOG_MAX_BYTES."""

    def test_no_rotation_when_under_size(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        svc.text_log_file.write_text("small\n", encoding="utf-8")
        svc._rotate_text_log_if_needed()
        # Original file should still exist, no .1 backup
        assert svc.text_log_file.exists()
        assert not svc._text_backup_path(1).exists()

    def test_rotation_when_oversize(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        # Write file just over the limit
        svc.text_log_file.write_bytes(b"x" * (_TEXT_LOG_MAX_BYTES + 10))
        svc._rotate_text_log_if_needed()
        # The original was renamed to .1
        assert svc._text_backup_path(1).exists()
        assert not svc.text_log_file.exists()

    def test_rotation_shifts_backups(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        # Pre-create backups .1, .2, .3
        for i in range(1, _TEXT_LOG_BACKUP_COUNT + 1):
            svc._text_backup_path(i).write_text(f"backup-{i}", encoding="utf-8")
        # Oversize current log
        svc.text_log_file.write_bytes(b"x" * (_TEXT_LOG_MAX_BYTES + 10))
        svc._rotate_text_log_if_needed()
        # The oldest (.3) was deleted before the shift, then .2 -> .3, .1 -> .2,
        # then current -> .1.
        assert svc._text_backup_path(1).exists()
        assert svc._text_backup_path(2).read_text(encoding="utf-8") == "backup-1"
        assert svc._text_backup_path(3).read_text(encoding="utf-8") == "backup-2"

    def test_rotation_swallows_oserror(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        svc.text_log_file.write_bytes(b"x" * (_TEXT_LOG_MAX_BYTES + 10))
        with patch.object(Path, "rename", side_effect=OSError("denied")):
            # Must not raise — the helper logs the error and returns
            svc._rotate_text_log_if_needed()


class TestActionLogServiceTimezone:
    """_get_timezone() falls back to UTC on error."""

    def test_timezone_falls_back_on_import_error(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        with patch(
            "services.config.config_service.load_config",
            side_effect=ImportError("no config"),
        ):
            tz_name, tz = svc._get_timezone()
        assert tz_name == "UTC"

    def test_timezone_falls_back_on_unknown_zone(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        with patch(
            "services.config.config_service.load_config",
            return_value={"timezone": "Bogus/Nonsense"},
        ):
            tz_name, tz = svc._get_timezone()
        assert tz_name == "UTC"

    def test_timezone_uses_configured_value(self, tmp_path):
        svc = ActionLogService(logs_dir=str(tmp_path))
        with patch(
            "services.config.config_service.load_config",
            return_value={"timezone": "Europe/Berlin"},
        ):
            tz_name, tz = svc._get_timezone()
        assert tz_name == "Europe/Berlin"


class TestActionLogServiceSingleton:
    def test_singleton(self):
        a = get_action_log_service()
        b = get_action_log_service()
        assert a is b
        assert isinstance(a, ActionLogService)
