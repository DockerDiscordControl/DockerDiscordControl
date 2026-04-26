# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Logging / Storage Bundle Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Bundle 1 + Bundle 2 logging/storage tests.

Covers:
    * Bundle 1 / L1 - rotating file handlers for ``discord.log`` /
      ``bot_error.log`` attached by ``ensure_log_files``.
    * Bundle 2 / L6 - text-rotation logic for ``user_actions.log`` in
      :class:`ActionLogService`.
    * Bundle 1 / L3 - DebugModeFilter behaviour and the new 5-minute
      default for ``enable_temporary_debug``.
    * Bundle 8a - ``DDC_CONFIG_DIR`` env-var override on ConfigService.
    * Bundle 1 / C3 - .gitignore patterns for cached_animations.
"""

from __future__ import annotations

import logging
import os
import time
from logging import FileHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Bundle 1 / L1 -- ensure_log_files()
# ---------------------------------------------------------------------------

class TestEnsureLogFilesRotatingHandlers:
    """Verify ensure_log_files attaches RotatingFileHandlers with the correct
    size limits and remains idempotent on repeated invocation."""

    def _fresh_logger(self, name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        # Strip any handlers carried over from previous tests so the
        # idempotency assertions are deterministic.
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
        return logger

    def test_attaches_rotating_handlers_for_both_logs(self, tmp_path: Path) -> None:
        from app.bootstrap.runtime import ensure_log_files

        logger = self._fresh_logger("ddc.test.bundle1.l1.attach")
        ensure_log_files(logger, tmp_path)

        rotating = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        # Both expected handlers must be RotatingFileHandler subclasses.
        assert len(rotating) >= 2

        base_files = {Path(getattr(h, "baseFilename", "")).name for h in rotating}
        assert "discord.log" in base_files
        assert "bot_error.log" in base_files

    def test_handlers_are_filehandler_subclass(self, tmp_path: Path) -> None:
        """RotatingFileHandler must be recognised by isinstance(FileHandler)."""

        from app.bootstrap.runtime import ensure_log_files

        logger = self._fresh_logger("ddc.test.bundle1.l1.subclass")
        ensure_log_files(logger, tmp_path)

        target_files = {
            str(tmp_path / "discord.log"),
            str(tmp_path / "bot_error.log"),
        }
        matched = [
            h for h in logger.handlers
            if isinstance(h, FileHandler)
            and getattr(h, "baseFilename", "") in target_files
        ]
        assert len(matched) == 2
        for handler in matched:
            assert isinstance(handler, RotatingFileHandler), (
                "ensure_log_files must use RotatingFileHandler, not plain FileHandler"
            )

    def test_discord_log_rotation_parameters(self, tmp_path: Path) -> None:
        from app.bootstrap.runtime import ensure_log_files

        logger = self._fresh_logger("ddc.test.bundle1.l1.discord_params")
        ensure_log_files(logger, tmp_path)

        discord_handler = next(
            h for h in logger.handlers
            if isinstance(h, RotatingFileHandler)
            and Path(h.baseFilename).name == "discord.log"
        )
        assert discord_handler.maxBytes == 10 * 1024 * 1024
        assert discord_handler.backupCount == 5

    def test_bot_error_log_rotation_parameters(self, tmp_path: Path) -> None:
        from app.bootstrap.runtime import ensure_log_files

        logger = self._fresh_logger("ddc.test.bundle1.l1.error_params")
        ensure_log_files(logger, tmp_path)

        error_handler = next(
            h for h in logger.handlers
            if isinstance(h, RotatingFileHandler)
            and Path(h.baseFilename).name == "bot_error.log"
        )
        assert error_handler.maxBytes == 5 * 1024 * 1024
        assert error_handler.backupCount == 3

    def test_idempotent_no_duplicate_handlers(self, tmp_path: Path) -> None:
        from app.bootstrap.runtime import ensure_log_files

        logger = self._fresh_logger("ddc.test.bundle1.l1.idempotent")
        ensure_log_files(logger, tmp_path)
        ensure_log_files(logger, tmp_path)

        rotating = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        # Exactly one handler per log file, no duplicates after a second call.
        assert len(rotating) == 2
        names = sorted(Path(h.baseFilename).name for h in rotating)
        assert names == ["bot_error.log", "discord.log"]


# ---------------------------------------------------------------------------
# Bundle 2 / L6 -- ActionLogService text-log rotation
# ---------------------------------------------------------------------------

class TestActionLogTextRotation:
    """Verify size-based rotation of ``user_actions.log``."""

    def _service(self, tmp_path: Path):
        from services.infrastructure.action_log_service import ActionLogService

        return ActionLogService(logs_dir=str(tmp_path))

    def _max_bytes(self) -> int:
        from services.infrastructure.action_log_service import _TEXT_LOG_MAX_BYTES

        return _TEXT_LOG_MAX_BYTES

    def _backup_count(self) -> int:
        from services.infrastructure.action_log_service import _TEXT_LOG_BACKUP_COUNT

        return _TEXT_LOG_BACKUP_COUNT

    def test_constants_match_specification(self) -> None:
        assert self._max_bytes() == 5 * 1024 * 1024
        assert self._backup_count() == 3

    def test_no_rotation_when_under_limit(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        service.text_log_file.write_text("small content\n", encoding="utf-8")

        service._rotate_text_log_if_needed()

        assert service.text_log_file.exists()
        assert not (tmp_path / "user_actions.log.1").exists()

    def test_rotates_to_dot_one_when_over_limit(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        # Just over the limit so rotation fires.
        big_payload = b"x" * (self._max_bytes() + 16)
        service.text_log_file.write_bytes(big_payload)

        service._rotate_text_log_if_needed()

        rotated = tmp_path / "user_actions.log.1"
        assert rotated.exists()
        # After rotation the original file no longer exists (it was renamed).
        assert not service.text_log_file.exists()
        assert rotated.stat().st_size == len(big_payload)

    def test_max_three_backups_oldest_dropped(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        max_bytes = self._max_bytes()

        # Trigger 4 rotations with distinguishable payloads so we can prove the
        # oldest content is discarded once we hit BACKUP_COUNT (3).
        for marker in (b"A", b"B", b"C", b"D"):
            service.text_log_file.write_bytes(marker + b"x" * max_bytes)
            service._rotate_text_log_if_needed()

        # Only .1, .2, .3 may exist; .4 must never appear.
        assert (tmp_path / "user_actions.log.1").exists()
        assert (tmp_path / "user_actions.log.2").exists()
        assert (tmp_path / "user_actions.log.3").exists()
        assert not (tmp_path / "user_actions.log.4").exists()

        # The newest write ("D") ends up in .1, oldest surviving ("B") in .3,
        # and the original "A" was dropped when .3 was overwritten by .2.
        assert (tmp_path / "user_actions.log.1").read_bytes().startswith(b"D")
        assert (tmp_path / "user_actions.log.2").read_bytes().startswith(b"C")
        assert (tmp_path / "user_actions.log.3").read_bytes().startswith(b"B")

    def test_unrelated_files_left_untouched(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        # Drop a sentinel cache file that must survive rotation.
        cache_file = tmp_path / "dummy.cache"
        cache_file.write_bytes(b"cache-payload")
        unrelated = tmp_path / "notes.txt"
        unrelated.write_text("keep me", encoding="utf-8")

        # Force a rotation.
        service.text_log_file.write_bytes(b"x" * (self._max_bytes() + 1))
        service._rotate_text_log_if_needed()

        assert cache_file.exists()
        assert cache_file.read_bytes() == b"cache-payload"
        assert unrelated.exists()
        assert unrelated.read_text(encoding="utf-8") == "keep me"


# ---------------------------------------------------------------------------
# Bundle 1 / L3 -- DebugModeFilter + enable_temporary_debug
# ---------------------------------------------------------------------------

class TestDebugModeFilter:
    """Validate the debug-filter behaviour and the new 5 minute default."""

    @pytest.fixture(autouse=True)
    def _reset_debug_state(self):
        # Snapshot then reset the module globals around each test so we can
        # assert deterministic behaviour without leaking into siblings.
        import utils.logging_utils as lu

        prev_temp = lu._temp_debug_mode_enabled
        prev_expiry = lu._temp_debug_expiry
        prev_perm = lu._debug_mode_enabled
        lu._temp_debug_mode_enabled = False
        lu._temp_debug_expiry = 0
        lu._debug_mode_enabled = False
        try:
            yield
        finally:
            lu._temp_debug_mode_enabled = prev_temp
            lu._temp_debug_expiry = prev_expiry
            lu._debug_mode_enabled = prev_perm

    def _make_record(self, level: int) -> logging.LogRecord:
        return logging.LogRecord(
            name="ddc.test",
            level=level,
            pathname=__file__,
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )

    def test_default_duration_is_five_minutes(self) -> None:
        from utils.logging_utils import enable_temporary_debug
        import utils.logging_utils as lu

        before = time.time()
        success, expiry = enable_temporary_debug()
        after = time.time()

        assert success is True
        # 5 min = 300s, allow a generous wall-clock tolerance.
        elapsed = expiry - before
        assert 299 <= elapsed <= 301 + (after - before)
        # Ensure it's NOT the previous 10-minute default.
        assert elapsed < 600
        assert lu._temp_debug_mode_enabled is True

    def test_custom_duration_two_minutes(self) -> None:
        from utils.logging_utils import enable_temporary_debug

        before = time.time()
        success, expiry = enable_temporary_debug(2)
        after = time.time()

        assert success is True
        elapsed = expiry - before
        # 2 min = 120s.
        assert 119 <= elapsed <= 121 + (after - before)

    def test_filter_blocks_debug_when_disabled(self) -> None:
        from utils.logging_utils import DebugModeFilter

        flt = DebugModeFilter()
        with patch("utils.logging_utils.is_debug_mode_enabled", return_value=False):
            assert flt.filter(self._make_record(logging.DEBUG)) is False

    def test_filter_allows_debug_when_temp_debug_active(self) -> None:
        from utils.logging_utils import DebugModeFilter, enable_temporary_debug

        enable_temporary_debug(1)
        flt = DebugModeFilter()
        # The active temp-debug window means is_debug_mode_enabled() is True
        # without needing to mock it.
        assert flt.filter(self._make_record(logging.DEBUG)) is True

    def test_filter_always_allows_info(self) -> None:
        from utils.logging_utils import DebugModeFilter

        flt = DebugModeFilter()
        with patch("utils.logging_utils.is_debug_mode_enabled", return_value=False):
            assert flt.filter(self._make_record(logging.INFO)) is True

    def test_filter_always_allows_warning(self) -> None:
        from utils.logging_utils import DebugModeFilter

        flt = DebugModeFilter()
        with patch("utils.logging_utils.is_debug_mode_enabled", return_value=False):
            assert flt.filter(self._make_record(logging.WARNING)) is True

    def test_filter_always_allows_error(self) -> None:
        from utils.logging_utils import DebugModeFilter

        flt = DebugModeFilter()
        with patch("utils.logging_utils.is_debug_mode_enabled", return_value=False):
            assert flt.filter(self._make_record(logging.ERROR)) is True


# ---------------------------------------------------------------------------
# Bundle 8a -- ConfigService env-var override
# ---------------------------------------------------------------------------

class TestConfigServiceEnvOverride:
    """The DDC_CONFIG_DIR env var must redirect ConfigService.config_dir."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self, monkeypatch):
        # ConfigService is a singleton; reset before AND after so we don't
        # poison other test modules.
        from services.config import config_service as cs_mod

        prev_instance = cs_mod.ConfigService._instance
        prev_module_singleton = cs_mod._config_service_instance
        cs_mod.ConfigService._instance = None
        cs_mod._config_service_instance = None
        try:
            yield monkeypatch
        finally:
            cs_mod.ConfigService._instance = prev_instance
            cs_mod._config_service_instance = prev_module_singleton

    def test_env_override_uses_custom_dir(self, tmp_path: Path, _reset_singleton):
        _reset_singleton.setenv("DDC_CONFIG_DIR", str(tmp_path))
        from services.config.config_service import ConfigService

        service = ConfigService()
        assert service.config_dir == tmp_path

    def test_no_env_falls_back_to_project_root_config(self, _reset_singleton):
        _reset_singleton.delenv("DDC_CONFIG_DIR", raising=False)
        from services.config.config_service import ConfigService

        service = ConfigService()
        expected_root = Path(
            __import__("services.config.config_service", fromlist=["__file__"]).__file__
        ).parent.parent.parent
        assert service.config_dir == expected_root / "config"

    def test_readonly_directory_does_not_crash(self, tmp_path: Path, _reset_singleton):
        # Point at a path whose parent is read-only so mkdir would fail; the
        # try/except PermissionError swallow must keep __init__ alive.
        readonly_parent = tmp_path / "ro_parent"
        readonly_parent.mkdir()
        target = readonly_parent / "config"
        _reset_singleton.setenv("DDC_CONFIG_DIR", str(target))

        original_mkdir = Path.mkdir

        def fake_mkdir(self, *args, **kwargs):
            if self == target:
                raise PermissionError("simulated read-only mount")
            return original_mkdir(self, *args, **kwargs)

        _reset_singleton.setattr(Path, "mkdir", fake_mkdir)

        from services.config.config_service import ConfigService

        # Must NOT raise even though the directory cannot be created.
        service = ConfigService()
        assert service.config_dir == target


# ---------------------------------------------------------------------------
# Bundle 1 / C3 -- .gitignore covers cached_animations artefacts
# ---------------------------------------------------------------------------

class TestGitignoreCachedAnimationsPatterns:
    """Generated mech animations must never be committed."""

    def _gitignore_path(self) -> Path:
        # tests/unit/storage/<file>  ->  project root
        return Path(__file__).resolve().parents[3] / ".gitignore"

    def test_gitignore_exists(self) -> None:
        assert self._gitignore_path().is_file(), (
            f".gitignore not found at {self._gitignore_path()}"
        )

    def test_gitignore_excludes_cache_files(self) -> None:
        content = self._gitignore_path().read_text(encoding="utf-8")
        assert "cached_animations/*.cache" in content

    def test_gitignore_excludes_webp_files(self) -> None:
        content = self._gitignore_path().read_text(encoding="utf-8")
        assert "cached_animations/*.webp" in content
