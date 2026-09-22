# -*- coding: utf-8 -*-
# @covers Z9
# This file checked C2-1 ('decrypted bot token must never be written to
# config.json / .bak') before the quality programme. So the coverage for Z9
# existed - it just was not recorded anywhere. A second test of the same kind
# would have been duplication, not coverage. See SPEC.md Z9 and R2.
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Audit 2026-09, package C2 - ConfigService regression tests.

C2-1  decrypted bot token must never be written to config.json / .bak
C2-2  change_web_ui_password(): hash + bot token re-encryption contract
C2-3  legacy auth.json / web_ui.json / docker_settings.json must not override config.json
C2-8  config cache must be stamped with the mtime taken before loading
"""

import inspect
import json
import os

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import services.config.config_service as cs_mod
from services.config.config_cache_service import ConfigCacheService
from services.config.config_loader_service import LEGACY_FOLD_MARKER, ConfigLoaderService
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import (
    ConfigService, ConfigServiceResult, change_web_ui_password, get_config_service,
)
from services.exceptions import ConfigSaveError, TokenEncryptionError

# Shaped like a real Discord bot token (looks_like_discord_token() -> True)
TOKEN = "MTA" + "a" * 23 + "." + "b" * 6 + "." + "c" * 38
OLD_PASSWORD = "Old-Password-2026"
NEW_PASSWORD = "New-Password-2026!"


def _cheap_hash(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256:1000")


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    """Token key derivation with 600k PBKDF2 rounds is slow; the logic is identical."""
    monkeypatch.setattr(cs_mod, "_PBKDF2_ITERATIONS", 1000)


@pytest.fixture
def svc(tmp_path):
    """Point the ConfigService singleton at a temp dir (real modular layout) and restore it afterwards."""
    service = get_config_service()
    saved_state = dict(service.__dict__)

    config_dir = tmp_path / "config"
    (config_dir / "containers").mkdir(parents=True)
    (config_dir / "channels").mkdir()
    (config_dir / "containers" / "web.json").write_text(json.dumps({"docker_name": "web", "active": True}))

    service.config_dir = config_dir
    service.channels_dir = config_dir / "channels"
    service.containers_dir = config_dir / "containers"
    service.main_config_file = config_dir / "config.json"
    service.auth_config_file = config_dir / "auth.json"
    service.heartbeat_config_file = config_dir / "heartbeat.json"
    service.web_ui_config_file = config_dir / "web_ui.json"
    service.docker_settings_file = config_dir / "docker_settings.json"
    service.bot_config_file = config_dir / "bot_config.json"
    service.docker_config_file = config_dir / "docker_config.json"
    service.web_config_file = config_dir / "web_config.json"
    service.channels_config_file = config_dir / "channels_config.json"
    service._migration_service = ConfigMigrationService(config_dir, service.channels_dir, service.containers_dir)
    service._cache_service = ConfigCacheService()
    service._loader_service = ConfigLoaderService(
        config_dir, service.channels_dir, service.containers_dir,
        service.main_config_file, service.auth_config_file, service.heartbeat_config_file,
        service.web_ui_config_file, service.docker_settings_file, service.bot_config_file,
        service.docker_config_file, service.web_config_file, service.channels_config_file,
        service._load_json_file, service._validation_service,
    )
    yield service

    service.__dict__.clear()
    service.__dict__.update(saved_state)


def _write_config(service, data):
    service.main_config_file.write_text(json.dumps(data))


def _read_config(service):
    return json.loads(service.main_config_file.read_text())


# ---------------------------------------------------------------------------
# C2-1
# ---------------------------------------------------------------------------

class TestC21NoPlaintextTokenOnDisk:

    def test_get_config_then_save_never_writes_decrypted_token(self, svc):
        old_hash = _cheap_hash(OLD_PASSWORD)
        encrypted = svc.encrypt_token(TOKEN, old_hash)
        _write_config(svc, {"bot_token": encrypted, "web_ui_password_hash": old_hash, "language": "en"})

        config = svc.get_config(force_reload=True)
        assert config["bot_token_decrypted_for_usage"] == TOKEN  # runtime value still available

        # Web save / donation_config / reset_password pattern: load -> mutate -> save
        config["language"] = "de"
        svc.save_config(config)
        svc.save_config(svc.get_config(force_reload=True))  # .bak now holds the first save

        for path in (svc.main_config_file, svc.main_config_file.with_suffix(".json.bak")):
            text = path.read_text()
            assert TOKEN not in text
            assert "bot_token_decrypted_for_usage" not in text

        on_disk = _read_config(svc)
        assert on_disk["bot_token"] == encrypted
        assert on_disk["language"] == "de"
        assert svc.get_config(force_reload=True)["bot_token_decrypted_for_usage"] == TOKEN

    def test_save_never_replaces_encrypted_token_with_plaintext(self, svc):
        old_hash = _cheap_hash(OLD_PASSWORD)
        _write_config(svc, {"bot_token": svc.encrypt_token(TOKEN, old_hash), "web_ui_password_hash": old_hash})

        svc.save_config({"bot_token": TOKEN, "web_ui_password_hash": old_hash})

        assert TOKEN not in svc.main_config_file.read_text()
        assert svc.decrypt_token(_read_config(svc)["bot_token"], old_hash) == TOKEN


# ---------------------------------------------------------------------------
# C2-2
# ---------------------------------------------------------------------------

class TestC22ChangeWebUiPassword:

    def test_contract_signature(self):
        sig = inspect.signature(change_web_ui_password)
        assert list(sig.parameters) == ["new_password", "enforce_min_length"]
        # R2-1: the length check is only skipped on request (DDC_ADMIN_PASSWORD at startup)
        assert sig.parameters["enforce_min_length"].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["enforce_min_length"].default is True
        assert sig.return_annotation is None

    @pytest.mark.parametrize("bad", ["", "short", "x" * 11, None])
    def test_rejects_empty_or_short_password(self, svc, bad):
        _write_config(svc, {"web_ui_password_hash": "keep-me"})
        with pytest.raises(ValueError) as exc_info:
            change_web_ui_password(bad)
        assert str(exc_info.value)
        assert _read_config(svc)["web_ui_password_hash"] == "keep-me"

    def test_reencrypts_token_round_trip(self, svc):
        old_hash = _cheap_hash(OLD_PASSWORD)
        encrypted = svc.encrypt_token(TOKEN, old_hash)
        _write_config(svc, {"bot_token": encrypted, "web_ui_password_hash": old_hash, "guild_id": "42"})
        svc.get_config()  # warm the cache with the old hash

        change_web_ui_password(NEW_PASSWORD)

        on_disk = _read_config(svc)
        new_hash = on_disk["web_ui_password_hash"]
        assert check_password_hash(new_hash, NEW_PASSWORD)
        assert not check_password_hash(new_hash, OLD_PASSWORD)
        assert on_disk["guild_id"] == "42"
        assert on_disk["bot_token"] != encrypted
        assert svc.decrypt_token(on_disk["bot_token"], new_hash) == TOKEN
        with pytest.raises(TokenEncryptionError):
            svc.decrypt_token(on_disk["bot_token"], old_hash)

        # Effective immediately through the same path app/auth.py uses
        live = cs_mod.load_config()
        assert live["web_ui_password_hash"] == new_hash
        assert live["bot_token_decrypted_for_usage"] == TOKEN

        # Neither the plaintext password nor the plaintext token reach the disk
        for path in svc.config_dir.iterdir():
            if path.is_file():
                text = path.read_text()
                assert NEW_PASSWORD not in text
                assert TOKEN not in text

    def test_plaintext_token_is_left_unchanged(self, svc):
        _write_config(svc, {"bot_token": TOKEN, "web_ui_password_hash": _cheap_hash(OLD_PASSWORD)})
        change_web_ui_password(NEW_PASSWORD)
        on_disk = _read_config(svc)
        assert on_disk["bot_token"] == TOKEN
        assert check_password_hash(on_disk["web_ui_password_hash"], NEW_PASSWORD)

    def test_undecryptable_token_is_kept(self, svc):
        foreign = svc.encrypt_token(TOKEN, _cheap_hash("Some-Other-Pass-1"))
        _write_config(svc, {"bot_token": foreign, "web_ui_password_hash": _cheap_hash(OLD_PASSWORD)})
        change_web_ui_password(NEW_PASSWORD)
        on_disk = _read_config(svc)
        assert on_disk["bot_token"] == foreign
        assert check_password_hash(on_disk["web_ui_password_hash"], NEW_PASSWORD)

    def test_migrated_install_with_legacy_files(self, svc):
        """Token in auth.json, hash in web_ui.json (migration layout) - C2-2 together with C2-3,
        after the one-time fold ConfigService runs at startup (R1-2)."""
        old_hash = _cheap_hash(OLD_PASSWORD)
        (svc.config_dir / "auth.json").write_text(json.dumps(
            {"bot_token": svc.encrypt_token(TOKEN, old_hash), "encryption_enabled": True}))
        (svc.config_dir / "web_ui.json").write_text(json.dumps(
            {"web_ui_user": "admin", "web_ui_password_hash": old_hash}))
        _write_config(svc, {"language": "en"})
        assert svc._fold_legacy_settings_once() is True

        change_web_ui_password(NEW_PASSWORD)

        live = svc.get_config()
        assert check_password_hash(live["web_ui_password_hash"], NEW_PASSWORD)
        assert live["bot_token_decrypted_for_usage"] == TOKEN

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions")
    def test_persistence_failure_raises_config_save_error(self, svc):
        old_hash = _cheap_hash(OLD_PASSWORD)
        _write_config(svc, {"web_ui_password_hash": old_hash})
        os.chmod(svc.config_dir, 0o500)
        try:
            with pytest.raises(ConfigSaveError):
                change_web_ui_password(NEW_PASSWORD)
        finally:
            os.chmod(svc.config_dir, 0o700)
        assert _read_config(svc)["web_ui_password_hash"] == old_hash

    def test_failed_update_result_raises_config_save_error(self, svc, monkeypatch):
        _write_config(svc, {"web_ui_password_hash": _cheap_hash(OLD_PASSWORD)})
        monkeypatch.setattr(ConfigService, "update_config_fields",
                            lambda self, updates: ConfigServiceResult(success=False, message="read failed"))
        with pytest.raises(ConfigSaveError):
            change_web_ui_password(NEW_PASSWORD)


# ---------------------------------------------------------------------------
# C2-3
# ---------------------------------------------------------------------------

class TestC23LegacyFilesAreDefaultsOnly:
    """After the one-time fold (R1-2, marker present) leftover legacy files only fill gaps.
    Before it, the v2.3 precedence applies - see test_r2_g2_config_fold.py."""

    @pytest.fixture(autouse=True)
    def _folded(self, svc):
        (svc.config_dir / LEGACY_FOLD_MARKER).write_text("{}")

    def test_config_json_wins_over_legacy_files(self, svc):
        (svc.config_dir / "auth.json").write_text(json.dumps({"bot_token": "legacy-token"}))
        (svc.config_dir / "web_ui.json").write_text(json.dumps(
            {"web_ui_user": "admin", "web_ui_password_hash": "legacy-hash", "session_timeout": 1800}))
        (svc.config_dir / "docker_settings.json").write_text(json.dumps(
            {"docker_socket_path": "/legacy.sock", "docker_api_timeout": 45}))
        _write_config(svc, {"bot_token": "live-token", "web_ui_password_hash": "live-hash",
                            "docker_socket_path": "/live.sock"})

        config = svc.get_config(force_reload=True)

        assert config["bot_token"] == "live-token"
        assert config["web_ui_password_hash"] == "live-hash"
        assert config["docker_socket_path"] == "/live.sock"
        # Keys config.json lacks still come from the legacy files
        assert config["session_timeout"] == 1800
        assert config["docker_api_timeout"] == 45
        assert config["web_ui_user"] == "admin"

    def test_null_in_config_json_does_not_wipe_legacy_hash(self, svc):
        (svc.config_dir / "web_ui.json").write_text(json.dumps({"web_ui_password_hash": "legacy-hash"}))
        _write_config(svc, {"web_ui_password_hash": None, "language": "en"})
        assert svc.get_config(force_reload=True)["web_ui_password_hash"] == "legacy-hash"


# ---------------------------------------------------------------------------
# C2-9
# ---------------------------------------------------------------------------

class TestC29VirtualModeReadsConfigJson:
    """Without channels/*.json and containers/*.json the loader runs in virtual mode,
    which used to build the config from the v1 files only and ignore config.json."""

    def test_config_json_is_loaded_in_virtual_mode(self, svc):
        (svc.config_dir / "containers" / "web.json").unlink()
        (svc.config_dir / LEGACY_FOLD_MARKER).write_text("{}")  # after the one-time fold (R1-2)
        assert not svc._loader_service.has_real_modular_structure()

        (svc.config_dir / "web_config.json").write_text(json.dumps(
            {"web_ui_password_hash": "legacy-hash", "advanced_settings": {"A": "legacy", "B": "legacy"}}))
        _write_config(svc, {"web_ui_password_hash": "live-hash", "language": "de",
                            "advanced_settings": {"B": "live"}})

        config = svc.get_config(force_reload=True)

        assert config["web_ui_password_hash"] == "live-hash"
        assert config["language"] == "de"
        # Legacy advanced settings stay a fallback, config.json wins on collision
        assert config["advanced_settings"] == {"A": "legacy", "B": "live"}


# ---------------------------------------------------------------------------
# C2-8
# ---------------------------------------------------------------------------

class TestC28CacheStampedBeforeLoad:

    def test_set_cached_config_uses_given_mtime(self, tmp_path):
        cache = ConfigCacheService()
        before = cache.get_config_dir_mtime(tmp_path)
        os.utime(tmp_path, (before + 5, before + 5))

        cache.set_cached_config("k", {"a": 1}, tmp_path, mtime=before)
        assert cache.get_cached_config("k", tmp_path) is None

        cache.set_cached_config("k", {"a": 1}, tmp_path)  # default: current mtime
        assert cache.get_cached_config("k", tmp_path) == {"a": 1}

    def test_save_landing_mid_load_is_not_ignored(self, svc, monkeypatch):
        _write_config(svc, {"language": "en"})
        real_load = svc._loader_service.load_modular_config
        calls = []

        def load_with_concurrent_save():
            calls.append(1)
            result = real_load()
            if len(calls) == 1:
                # Another thread saves (atomic rename -> dir mtime bump) while this load runs
                _write_config(svc, {"language": "de"})
                future = os.path.getmtime(svc.config_dir) + 5
                os.utime(svc.config_dir, (future, future))
            return result

        monkeypatch.setattr(svc._loader_service, "load_modular_config", load_with_concurrent_save)

        assert svc.get_config()["language"] == "en"  # result of the racing load
        assert svc.get_config()["language"] == "de"  # must reload instead of serving the stale cache
        assert len(calls) == 2
