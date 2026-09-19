# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package F - config/utils regressions.

F2  persistent Flask secret key file instead of predictable / per-start keys
F6  broken legacy config files never crash the token migration; atomic rewrite
F7  is_debug_mode_enabled() recursion guard is always cleared
F12 metrics exports: real exception types, json.dump, atomic write
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.web import config as web_config

HEX64 = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- #
# F2                                                                           #
# --------------------------------------------------------------------------- #

class TestF2SecretKey:
    def test_real_key_is_used_unchanged(self, tmp_path):
        key_file = tmp_path / ".flask_secret_key"
        assert web_config.resolve_secret_key({"FLASK_SECRET_KEY": "my-real-secret"}, key_file) == "my-real-secret"
        assert not key_file.exists()

    @pytest.mark.parametrize(
        "env",
        [
            {},
            {"FLASK_SECRET_KEY": ""},
            {"FLASK_SECRET_KEY": "   "},
            {"FLASK_SECRET_KEY": "fallback-secret-key-for-dev-if-not-set"},
            {"FLASK_SECRET_KEY": "temporary-dev-key-1726400000"},  # old rebuild.sh fallback
            {"FLASK_SECRET_KEY": "dev-only-1726400000"},  # old start.sh fallback
        ],
    )
    def test_insecure_values_use_persistent_file(self, tmp_path, env):
        key_file = tmp_path / ".flask_secret_key"
        first = web_config.resolve_secret_key(env, key_file)
        assert HEX64.match(first)
        assert key_file.read_text().strip() == first
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        # Same key after a "restart" -> sessions survive
        assert web_config.resolve_secret_key(env, key_file) == first
        assert [p.name for p in tmp_path.iterdir()] == [".flask_secret_key"]  # no temp leftovers

    def test_empty_file_is_regenerated(self, tmp_path):
        key_file = tmp_path / ".flask_secret_key"
        key_file.write_text("\n")
        key = web_config.resolve_secret_key({}, key_file)
        assert HEX64.match(key)
        assert key_file.read_text().strip() == key

    def test_unreadable_file_falls_back_to_random_key(self, tmp_path):
        key_file = tmp_path / ".flask_secret_key"
        key_file.mkdir()  # reading a directory raises IsADirectoryError (OSError)
        assert HEX64.match(web_config.resolve_secret_key({}, key_file))

    def test_unwritable_location_falls_back_to_random_key(self, tmp_path):
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("x")
        key = web_config.resolve_secret_key({}, blocker / ".flask_secret_key")
        assert HEX64.match(key)

    def test_without_key_file_returns_random_key(self):
        a = web_config.resolve_secret_key({})
        b = web_config.resolve_secret_key({})
        assert HEX64.match(a) and a != b

    def test_build_config_uses_ddc_config_dir(self, tmp_path):
        env = {"DDC_CONFIG_DIR": str(tmp_path)}
        cfg = web_config.build_config(env)
        assert cfg["SECRET_KEY"] == (tmp_path / ".flask_secret_key").read_text().strip()
        assert web_config.build_config(env)["SECRET_KEY"] == cfg["SECRET_KEY"]
        assert cfg["WTF_CSRF_TIME_LIMIT"] is None  # coordinator change kept

    def test_build_config_with_real_key_writes_no_file(self, tmp_path):
        cfg = web_config.build_config({"DDC_CONFIG_DIR": str(tmp_path), "FLASK_SECRET_KEY": "real-key"})
        assert cfg["SECRET_KEY"] == "real-key"
        assert not (tmp_path / ".flask_secret_key").exists()


# --------------------------------------------------------------------------- #
# F6                                                                           #
# --------------------------------------------------------------------------- #

@pytest.fixture
def ts_config_dir(tmp_path, monkeypatch):
    # token_security reads utils.config_paths.get_config_dir() (DDC_CONFIG_DIR);
    # this used to fake the module's __file__ when it derived the path itself.
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(cfg))
    return cfg


class TestF6TokenMigration:
    @pytest.mark.parametrize("content", ["", "{", '{"bot_token": "abc"', "null", "[]"])
    def test_broken_legacy_file_does_not_raise(self, ts_config_dir, content):
        import utils.token_security as ts

        (ts_config_dir / "bot_config.json").write_text(content)
        (ts_config_dir / "web_config.json").write_text('{"web_ui_password_hash": "h"}')
        mgr = ts.TokenSecurityManager(config_service=MagicMock())
        assert mgr.encrypt_existing_plaintext_token() is False
        status = mgr.verify_token_encryption_status()
        assert any("Error checking token status" in r for r in status["recommendations"])

    def test_auto_encrypt_with_truncated_file_does_not_raise(self, ts_config_dir):
        import utils.token_security as ts

        (ts_config_dir / "bot_config.json").write_text('{"bot_token": "pla')
        (ts_config_dir / "web_config.json").write_text('{"web_ui_password_hash": "h"}')
        status = ts.auto_encrypt_token_on_startup()
        assert status is None or isinstance(status, dict)

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes")
    def test_unreadable_legacy_file_does_not_raise(self, ts_config_dir):
        import utils.token_security as ts

        bot_file = ts_config_dir / "bot_config.json"
        bot_file.write_text('{"bot_token": "plain"}')
        (ts_config_dir / "web_config.json").write_text('{"web_ui_password_hash": "h"}')
        bot_file.chmod(0)
        try:
            mgr = ts.TokenSecurityManager(config_service=MagicMock())
            assert mgr.encrypt_existing_plaintext_token() is False
            assert isinstance(mgr.verify_token_encryption_status(), dict)
        finally:
            bot_file.chmod(0o600)

    @pytest.mark.parametrize(
        "exc",
        [PermissionError("root-owned"), json.JSONDecodeError("bad", "", 0), ValueError("bad"), OSError("io")],
    )
    def test_ensure_token_security_survives(self, monkeypatch, exc):
        import utils.token_security as ts
        from app.bootstrap.runtime import ensure_token_security

        def _raise():
            raise exc

        monkeypatch.setattr(ts, "auto_encrypt_token_on_startup", _raise)
        assert ensure_token_security(MagicMock()) is False

    def test_rewrite_is_atomic_and_keeps_mode(self, ts_config_dir):
        import utils.token_security as ts

        bot_file = ts_config_dir / "bot_config.json"
        bot_file.write_text('{"bot_token": "plain-tok", "other": 1}')
        bot_file.chmod(0o640)
        (ts_config_dir / "web_config.json").write_text('{"web_ui_password_hash": "ph"}')
        svc = MagicMock()
        svc.encrypt_token.return_value = "gAAAAA-encrypted"

        assert ts.TokenSecurityManager(config_service=svc).encrypt_existing_plaintext_token() is True
        assert json.loads(bot_file.read_text()) == {"bot_token": "gAAAAA-encrypted", "other": 1}
        assert stat.S_IMODE(bot_file.stat().st_mode) == 0o640
        assert sorted(p.name for p in ts_config_dir.iterdir()) == ["bot_config.json", "web_config.json"]

    def test_failed_write_keeps_original_file(self, tmp_path):
        import utils.token_security as ts

        target = tmp_path / "bot_config.json"
        target.write_text('{"bot_token": "old"}')
        with pytest.raises(TypeError):
            ts._atomic_write_json(target, {"bot_token": object()})
        assert json.loads(target.read_text()) == {"bot_token": "old"}
        assert [p.name for p in tmp_path.iterdir()] == ["bot_config.json"]


# --------------------------------------------------------------------------- #
# F7                                                                           #
# --------------------------------------------------------------------------- #

class _FakeConfigService:
    def __init__(self, value):
        self.value = value
        self.error = None
        self._cache_service = SimpleNamespace(invalidate_cache=lambda: None)

    def get_config(self, force_reload=False):
        if self.error:
            raise self.error
        return {"scheduler_debug_mode": self.value}


@pytest.fixture
def lu(monkeypatch):
    import utils.logging_utils as lu

    saved = (lu._temp_debug_mode_enabled, lu._temp_debug_expiry, lu._debug_mode_enabled, lu._last_debug_status_log)
    if hasattr(lu.is_debug_mode_enabled, "_loading"):
        delattr(lu.is_debug_mode_enabled, "_loading")
    svc = _FakeConfigService(False)
    monkeypatch.setattr("services.config.config_service.get_config_service", lambda: svc)
    lu._fake_svc = svc
    try:
        yield lu
    finally:
        (lu._temp_debug_mode_enabled, lu._temp_debug_expiry, lu._debug_mode_enabled, lu._last_debug_status_log) = saved
        if hasattr(lu.is_debug_mode_enabled, "_loading"):
            delattr(lu.is_debug_mode_enabled, "_loading")
        del lu._fake_svc


class TestF7DebugGuard:
    def test_guard_cleared_after_temp_debug_return(self, lu):
        lu._temp_debug_mode_enabled = True
        lu._temp_debug_expiry = time.time() + 60
        assert lu.is_debug_mode_enabled() is True
        assert not hasattr(lu.is_debug_mode_enabled, "_loading")

    def test_toggle_after_temp_debug_is_picked_up(self, lu):
        lu._temp_debug_mode_enabled = True
        lu._temp_debug_expiry = time.time() + 60
        assert lu.is_debug_mode_enabled() is True
        lu.disable_temporary_debug()

        lu._fake_svc.value = True
        assert lu.refresh_debug_status() is True
        assert lu.is_debug_mode_enabled() is True

        lu._fake_svc.value = False
        assert lu.refresh_debug_status() is False
        assert lu.is_debug_mode_enabled() is False

    def test_guard_cleared_after_uncaught_exception(self, lu):
        lu._fake_svc.error = OSError("disk gone")
        with pytest.raises(OSError):
            lu.is_debug_mode_enabled()
        assert not hasattr(lu.is_debug_mode_enabled, "_loading")
        lu._fake_svc.error = None
        lu._fake_svc.value = True
        assert lu.is_debug_mode_enabled() is True


# --------------------------------------------------------------------------- #
# F12                                                                          #
# --------------------------------------------------------------------------- #

class TestF12MetricsExport:
    def test_write_metric_unserializable_is_logged_not_raised(self, tmp_path):
        from utils.performance_metrics import PerformanceMetrics

        fake_self = SimpleNamespace(metrics_file=tmp_path / "m.jsonl")
        entry = SimpleNamespace(to_dict=lambda: {"bad": object()})
        PerformanceMetrics._write_metric(fake_self, entry)  # used to raise AttributeError

    def test_export_to_json_unserializable_returns_false(self, tmp_path):
        from utils.performance_metrics import PerformanceMetrics

        stats = {"op": SimpleNamespace(to_dict=lambda: {"bad": object()})}
        fake_self = SimpleNamespace(get_stats=lambda operation=None: stats)
        assert PerformanceMetrics.export_to_json(fake_self, tmp_path / "out.json") is False

    def test_export_to_json_ok(self, tmp_path):
        from utils.performance_metrics import PerformanceMetrics

        stats = {"op": SimpleNamespace(to_dict=lambda: {"count": 1})}
        fake_self = SimpleNamespace(get_stats=lambda operation=None: stats)
        out = tmp_path / "out.json"
        assert PerformanceMetrics.export_to_json(fake_self, out) is True
        assert json.loads(out.read_text())["statistics"] == {"op": {"count": 1}}

    def test_observability_export_json_writes_json(self, tmp_path):
        from utils import observability as obs

        mc = obs.MetricsCollector()
        mc.increment("donations.total")
        out = tmp_path / "metrics.json"
        mc.export_json(out)
        data = json.loads(out.read_text())
        assert "timestamp" in data
        assert [p.name for p in tmp_path.iterdir()] == ["metrics.json"]

    def test_observability_export_failure_keeps_previous_file(self, tmp_path, monkeypatch):
        from utils import observability as obs

        mc = obs.MetricsCollector()
        out = tmp_path / "metrics.json"
        out.write_text('{"previous": true}')
        monkeypatch.setattr(mc, "get_stats", lambda: {"bad": object()})
        with pytest.raises(TypeError):
            mc.export_json(out)
        assert json.loads(out.read_text()) == {"previous": True}
        assert [p.name for p in tmp_path.iterdir()] == ["metrics.json"]
