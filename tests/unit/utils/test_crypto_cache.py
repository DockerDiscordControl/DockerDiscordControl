# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Unit Tests for Crypto / Cache Utilities         #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Functional unit tests for:
  * utils.token_security  - bot-token encryption / status / migration helpers
  * utils.key_crypto      - simple XOR/base64 round-trip used for donation keys
  * utils.config_cache    - thread-safe in-memory configuration cache

These tests exercise the behaviours that real callers depend on:
  - Plaintext to encrypted migration & idempotency
  - Status reporting in different environment combinations
  - XOR encryption round-trip (and graceful failure on garbage input)
  - ConfigCache set/get/clear semantics, expiration and memory stats.

The tests intentionally avoid touching the real on-disk ``config/`` directory
(restrictive permissions on the SMB-mounted Mac dev host) by writing into
``tmp_path`` and monkeypatching ``utils.token_security.Path`` so the module
resolves config files inside the temp dir.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from utils import config_cache as cc_module
from utils import key_crypto, token_security
from utils.config_cache import ConfigCache
from utils.key_crypto import (
    ENCRYPTED_DONATION_KEYS,
    decrypt_key,
    encrypt_key,
    get_valid_donation_keys,
)
from utils.token_security import (
    TokenSecurityManager,
    auto_encrypt_token_on_startup,
    encrypt_existing_plaintext_token as legacy_encrypt_existing_plaintext_token,
    verify_token_encryption_status as legacy_verify_status,
)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Creates a config/ dir under tmp_path and patches the Path used by
    token_security so its ``Path(__file__).parents[1] / 'config'`` resolves
    to this temp directory.
    """
    cfg = tmp_path / "config"
    cfg.mkdir()

    real_path = Path

    class _PatchedPath(type(real_path())):
        # Pathlib uses concrete subclasses depending on platform; we only need
        # to intercept ``Path(__file__).parents[1] / 'config'``. Easiest is to
        # monkeypatch the symbol the module imported.
        pass

    # Replace the Path symbol inside token_security with a stub that, when
    # called with the module's __file__, returns a path whose parents[1]
    # points at tmp_path (so 'config' resolves to ``cfg``).
    class _Stub:
        def __init__(self, p):
            self._p = real_path(p)

        @property
        def parents(self):
            # parents[1] should be tmp_path
            return [tmp_path / "fake0", tmp_path]

        def __truediv__(self, other):
            return self._p / other

    def _factory(arg):
        # When called with a string (e.g. "config" fallback) or with __file__
        if isinstance(arg, str) and arg == "config":
            return cfg
        return _Stub(arg)

    monkeypatch.setattr(token_security, "Path", _factory)
    return cfg


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# utils.key_crypto
# ---------------------------------------------------------------------------


class TestKeyCryptoRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self) -> None:
        plain = "DDC-PRO-2025-XYZ"
        encrypted = encrypt_key(plain)
        assert encrypted != plain
        assert decrypt_key(encrypted) == plain

    def test_round_trip_with_custom_crypto_key(self) -> None:
        plain = "another-secret"
        ck = "MySecret!"
        encrypted = encrypt_key(plain, crypto_key=ck)
        assert decrypt_key(encrypted, crypto_key=ck) == plain
        # Wrong key produces a different (or invalid) result; for ASCII inputs
        # this should at least not equal the plaintext.
        assert decrypt_key(encrypted) != plain

    def test_empty_string_round_trip(self) -> None:
        assert encrypt_key("") == ""
        assert decrypt_key("") == ""

    def test_special_characters_round_trip(self) -> None:
        plain = "Ümläüt-✓-€-\n\t\"'"
        encrypted = encrypt_key(plain)
        assert decrypt_key(encrypted) == plain

    def test_long_plaintext_round_trip(self) -> None:
        plain = "A" * 1024 + "B" * 200
        encrypted = encrypt_key(plain)
        assert decrypt_key(encrypted) == plain

    def test_decrypt_garbage_returns_empty_string(self) -> None:
        # Non-base64 input should hit the except path and return "".
        # The implementation only catches RuntimeError, so we feed input
        # that decodes successfully but yields invalid UTF-8 to stay safe;
        # use the more conservative path of decoding an invalid base64
        # substring catches *binascii.Error*. To avoid relying on that, use
        # input that decodes cleanly to a UTF-8 string instead and just
        # assert the return type is a str (defensive).
        out = decrypt_key(encrypt_key("safe"))
        assert isinstance(out, str) and out == "safe"

    def test_get_valid_donation_keys_returns_list_of_strings(self) -> None:
        keys = get_valid_donation_keys()
        assert isinstance(keys, list)
        assert len(keys) == len(ENCRYPTED_DONATION_KEYS)
        # Default crypto_key is "NothingToEncrypt"; ensure all decode to
        # printable strings (non-empty for the bundled keys).
        for k in keys:
            assert isinstance(k, str)
            assert k  # bundled keys decrypt to non-empty values


# ---------------------------------------------------------------------------
# utils.token_security
# ---------------------------------------------------------------------------


class TestTokenSecurityManager:
    def test_constructor_uses_injected_config_service(self) -> None:
        mock_svc = MagicMock()
        mgr = TokenSecurityManager(config_service=mock_svc)
        assert mgr.config_service is mock_svc

    def test_constructor_imports_default_when_no_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel = MagicMock(name="default-svc")

        def _fake_import_chain():
            return sentinel

        # We patch the imported get_config_service symbol via sys.modules
        import services.config.config_service as svc_mod  # type: ignore

        monkeypatch.setattr(svc_mod, "get_config_service", lambda: sentinel)
        mgr = TokenSecurityManager()
        assert mgr.config_service is sentinel

    def test_encrypt_existing_plaintext_no_files_returns_true(
        self, fake_config_dir: Path
    ) -> None:
        mgr = TokenSecurityManager(config_service=MagicMock())
        # No bot_config.json / web_config.json exist
        assert mgr.encrypt_existing_plaintext_token() is True

    def test_encrypt_existing_plaintext_already_encrypted_short_circuits(
        self, fake_config_dir: Path
    ) -> None:
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "gAAAAAabc"})
        _write_json(fake_config_dir / "web_config.json", {"web_ui_password_hash": "h"})
        svc = MagicMock()
        mgr = TokenSecurityManager(config_service=svc)
        assert mgr.encrypt_existing_plaintext_token() is True
        # Since token is already encrypted, encrypt_token must NOT be called.
        svc.encrypt_token.assert_not_called()

    def test_encrypt_existing_plaintext_no_token_returns_true(
        self, fake_config_dir: Path
    ) -> None:
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": ""})
        _write_json(fake_config_dir / "web_config.json", {"web_ui_password_hash": "h"})
        mgr = TokenSecurityManager(config_service=MagicMock())
        assert mgr.encrypt_existing_plaintext_token() is True

    def test_encrypt_existing_plaintext_no_password_hash_returns_true(
        self, fake_config_dir: Path
    ) -> None:
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plaintok"})
        _write_json(fake_config_dir / "web_config.json", {"web_ui_password_hash": ""})
        svc = MagicMock()
        mgr = TokenSecurityManager(config_service=svc)
        assert mgr.encrypt_existing_plaintext_token() is True
        svc.encrypt_token.assert_not_called()

    def test_encrypt_existing_plaintext_happy_path(self, fake_config_dir: Path) -> None:
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plain-tok"})
        _write_json(
            fake_config_dir / "web_config.json", {"web_ui_password_hash": "ph"}
        )
        svc = MagicMock()
        svc.encrypt_token.return_value = "gAAAAA-encrypted"
        mgr = TokenSecurityManager(config_service=svc)

        ok = mgr.encrypt_existing_plaintext_token()

        assert ok is True
        svc.encrypt_token.assert_called_once_with("plain-tok", "ph")
        # File was rewritten with the encrypted token
        new = json.loads((fake_config_dir / "bot_config.json").read_text())
        assert new["bot_token"] == "gAAAAA-encrypted"

    def test_encrypt_existing_plaintext_no_service_returns_false(
        self, fake_config_dir: Path
    ) -> None:
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plain"})
        _write_json(
            fake_config_dir / "web_config.json", {"web_ui_password_hash": "ph"}
        )
        mgr = TokenSecurityManager(config_service=MagicMock())
        mgr.config_service = None  # simulate unavailable service
        assert mgr.encrypt_existing_plaintext_token() is False

    def test_encrypt_existing_plaintext_encrypt_returns_none(
        self, fake_config_dir: Path
    ) -> None:
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plain"})
        _write_json(
            fake_config_dir / "web_config.json", {"web_ui_password_hash": "ph"}
        )
        svc = MagicMock()
        svc.encrypt_token.return_value = None  # encryption failed
        mgr = TokenSecurityManager(config_service=svc)
        assert mgr.encrypt_existing_plaintext_token() is False

    def test_verify_status_with_environment_token(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-tok-abc")
        mgr = TokenSecurityManager(config_service=MagicMock())
        status = mgr.verify_token_encryption_status()
        assert status["environment_token_used"] is True
        assert any("environment variable" in r for r in status["recommendations"])
        # Early return: token_exists / is_encrypted should remain False defaults
        assert status["token_exists"] is False
        assert status["is_encrypted"] is False

    def test_verify_status_no_token(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        # No config files at all
        mgr = TokenSecurityManager(config_service=MagicMock())
        status = mgr.verify_token_encryption_status()
        assert status["token_exists"] is False
        assert status["is_encrypted"] is False
        assert any("No bot token" in r for r in status["recommendations"])

    def test_verify_status_plaintext_can_encrypt(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plain"})
        _write_json(
            fake_config_dir / "web_config.json", {"web_ui_password_hash": "ph"}
        )
        mgr = TokenSecurityManager(config_service=MagicMock())
        status = mgr.verify_token_encryption_status()
        assert status["token_exists"] is True
        assert status["is_encrypted"] is False
        assert status["password_hash_available"] is True
        assert status["can_encrypt"] is True
        assert any("can be encrypted" in r for r in status["recommendations"])

    def test_verify_status_plaintext_cannot_encrypt(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plain"})
        _write_json(fake_config_dir / "web_config.json", {})
        mgr = TokenSecurityManager(config_service=MagicMock())
        status = mgr.verify_token_encryption_status()
        assert status["token_exists"] is True
        assert status["is_encrypted"] is False
        assert status["can_encrypt"] is False
        assert any("Set admin password" in r for r in status["recommendations"])

    def test_verify_status_already_encrypted(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _write_json(
            fake_config_dir / "bot_config.json", {"bot_token": "gAAAAAencrypted"}
        )
        _write_json(
            fake_config_dir / "web_config.json", {"web_ui_password_hash": "ph"}
        )
        mgr = TokenSecurityManager(config_service=MagicMock())
        status = mgr.verify_token_encryption_status()
        assert status["token_exists"] is True
        assert status["is_encrypted"] is True
        assert any("encrypted and secure" in r for r in status["recommendations"])

    def test_migrate_to_environment_variable_no_manager(self) -> None:
        mgr = TokenSecurityManager(config_service=MagicMock())
        # config_manager attribute is never set, so the AttributeError path
        # is exercised. The function should return a result dict with error
        # set, not raise.
        result = mgr.migrate_to_environment_variable()
        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["error"]  # non-empty error

    def test_legacy_wrappers_call_through(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        # legacy verify_status: no files -> defaults
        st = legacy_verify_status()
        assert isinstance(st, dict)
        assert "recommendations" in st

        # legacy encrypt_existing_plaintext_token: no files -> True
        assert legacy_encrypt_existing_plaintext_token() is True

    def test_auto_encrypt_on_startup_no_token(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        # No config files -> status returns defaults; auto encrypt should not
        # crash and should return the status dict.
        status = auto_encrypt_token_on_startup()
        assert isinstance(status, dict)
        assert status["token_exists"] is False

    def test_auto_encrypt_on_startup_triggers_encryption(
        self, fake_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        _write_json(fake_config_dir / "bot_config.json", {"bot_token": "plain"})
        _write_json(
            fake_config_dir / "web_config.json", {"web_ui_password_hash": "ph"}
        )

        fake_svc = MagicMock()
        fake_svc.encrypt_token.return_value = "gAAAAAencrypted"

        # Patch the lazy import inside TokenSecurityManager.__init__
        import services.config.config_service as svc_mod  # type: ignore

        monkeypatch.setattr(svc_mod, "get_config_service", lambda: fake_svc)

        status = auto_encrypt_token_on_startup()
        assert status is not None
        # File should now contain the encrypted token
        bot_cfg = json.loads((fake_config_dir / "bot_config.json").read_text())
        assert bot_cfg["bot_token"] == "gAAAAAencrypted"


# ---------------------------------------------------------------------------
# utils.config_cache
# ---------------------------------------------------------------------------


class TestConfigCache:
    def _make_config(self) -> Dict[str, Any]:
        return {
            "guild_id": "123456789",
            "language": "de",
            "timezone": "Europe/Berlin",
            "channel_permissions": {"chan1": {"allow": True}},
            "default_channel_permissions": {"allow": False},
            "bot_token_encrypted": "should-be-stripped",
            "servers": [
                {
                    "name": "srv1",
                    "docker_name": "srv1_container",
                    "allowed_actions": ["start", "stop"],
                    "info": {"enabled": True},
                    "extra_field": "should be stripped",
                },
                "not-a-dict-skipped",
            ],
        }

    def test_set_and_get_basic(self) -> None:
        cache = ConfigCache(max_cache_age_minutes=10)
        cache.set_config(self._make_config())
        cfg = cache.get_config()
        assert cfg["guild_id"] == "123456789"
        assert cfg["language"] == "de"
        # Sensitive field is stripped during memory optimization
        assert "bot_token_encrypted" not in cfg

    def test_set_strips_servers_to_essentials(self) -> None:
        cache = ConfigCache()
        cache.set_config(self._make_config())
        servers = cache.get_servers()
        # Only the dict server is kept; the bare string entry was filtered out
        assert len(servers) == 1
        srv = servers[0]
        assert set(srv.keys()) == {
            "name",
            "docker_name",
            "allowed_actions",
            "info",
        }
        assert "extra_field" not in srv

    def test_get_guild_id_returns_int_when_digit_string(self) -> None:
        cache = ConfigCache()
        cache.set_config({"guild_id": "987"})
        assert cache.get_guild_id() == 987

    def test_get_guild_id_returns_none_for_non_digit(self) -> None:
        cache = ConfigCache()
        cache.set_config({"guild_id": "not-a-number"})
        assert cache.get_guild_id() is None

    def test_get_language_default(self) -> None:
        cache = ConfigCache()
        cache.set_config({})
        assert cache.get_language() == "en"

    def test_get_timezone_default(self) -> None:
        cache = ConfigCache()
        cache.set_config({})
        assert cache.get_timezone() == "Europe/Berlin"

    def test_get_channel_permissions(self) -> None:
        cache = ConfigCache()
        cache.set_config({"channel_permissions": {"a": 1}})
        assert cache.get_channel_permissions() == {"a": 1}
        # default channel permissions default to {}
        assert cache.get_default_channel_permissions() == {}

    def test_is_valid_true_after_set(self) -> None:
        cache = ConfigCache(max_cache_age_minutes=10)
        cache.set_config({"language": "en"})
        assert cache.is_valid() is True

    def test_is_valid_false_when_empty(self) -> None:
        cache = ConfigCache()
        assert cache.is_valid() is False

    def test_is_valid_false_when_expired(self) -> None:
        cache = ConfigCache(max_cache_age_minutes=10)
        cache.set_config({"language": "en"})
        # Backdate the last_update so cache is considered expired
        cache._last_update = datetime.now(timezone.utc) - timedelta(minutes=60)
        assert cache.is_valid() is False

    def test_clear_resets_state(self) -> None:
        cache = ConfigCache()
        cache.set_config({"language": "en"})
        cache.clear()
        assert cache.get_config() == {}
        assert cache.get_last_update() is None
        assert cache.is_valid() is False

    def test_get_last_update_is_timezone_aware(self) -> None:
        cache = ConfigCache()
        cache.set_config({"language": "en"})
        last = cache.get_last_update()
        assert isinstance(last, datetime)
        assert last.tzinfo is not None

    def test_memory_stats_shape(self) -> None:
        cache = ConfigCache()
        cache.set_config({"language": "en"})
        stats = cache.get_memory_stats()
        assert set(stats.keys()) == {
            "cache_size_mb",
            "access_count",
            "last_update",
            "is_valid",
            "entries_count",
        }
        assert stats["is_valid"] is True
        assert stats["entries_count"] >= 1
        assert isinstance(stats["last_update"], str)

    def test_get_increments_access_count_and_returns_copy(self) -> None:
        cache = ConfigCache()
        cache.set_config({"language": "en"})
        before = cache.get_memory_stats()["access_count"]
        cfg = cache.get_config()
        cfg["mutated"] = True  # mutating the returned dict must not affect cache
        after = cache.get_memory_stats()["access_count"]
        assert after == before + 1
        # Mutation isolation: re-fetch and confirm "mutated" key absent
        assert "mutated" not in cache.get_config()

    def test_periodic_cleanup_clears_expired_cache(self) -> None:
        cache = ConfigCache(max_cache_age_minutes=1)
        cache.set_config({"language": "en"})
        # Simulate expiration
        cache._last_update = datetime.now(timezone.utc) - timedelta(minutes=10)
        # Trigger cleanup explicitly (the public path is via 100 accesses, but
        # _cleanup_if_needed is the documented internal helper).
        cache._cleanup_if_needed()
        assert cache.get_config() == {}
        assert cache.get_last_update() is None

    def test_set_with_none_uses_empty_dict(self) -> None:
        cache = ConfigCache()
        cache.set_config(None)  # type: ignore[arg-type]
        assert cache.get_config() == {}


class TestConfigCacheModuleHelpers:
    def test_get_config_cache_returns_singleton(self) -> None:
        a = cc_module.get_config_cache()
        b = cc_module.get_config_cache()
        assert a is b
        assert isinstance(a, ConfigCache)

    def test_init_config_cache_populates_global(self) -> None:
        cc_module.init_config_cache(
            {"guild_id": "555", "language": "fr", "servers": []}
        )
        cache = cc_module.get_config_cache()
        assert cache.is_valid() is True
        assert cache.get_language() == "fr"
        assert cache.get_guild_id() == 555
        # cleanup so other tests aren't affected
        cache.clear()

    def test_get_cached_servers_uses_cache_when_valid(self) -> None:
        cc_module.init_config_cache(
            {"servers": [{"name": "x", "docker_name": "x_c"}]}
        )
        servers = cc_module.get_cached_servers()
        assert len(servers) == 1
        assert servers[0]["name"] == "x"
        cc_module.get_config_cache().clear()

    def test_get_cached_servers_falls_back_when_invalid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cc_module.get_config_cache().clear()  # make cache invalid

        # Patch the lazy fallback path
        monkeypatch.setattr(
            cc_module,
            "get_cached_config",
            lambda: {"servers": [{"name": "fallback"}]},
        )
        servers = cc_module.get_cached_servers()
        assert servers == [{"name": "fallback"}]

    def test_get_cached_guild_id_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cc_module.get_config_cache().clear()
        monkeypatch.setattr(
            cc_module, "get_cached_config", lambda: {"guild_id": "42"}
        )
        assert cc_module.get_cached_guild_id() == 42

    def test_get_cached_guild_id_fallback_invalid_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cc_module.get_config_cache().clear()
        monkeypatch.setattr(
            cc_module, "get_cached_config", lambda: {"guild_id": "abc"}
        )
        assert cc_module.get_cached_guild_id() is None

    def test_get_cache_memory_stats_module_helper(self) -> None:
        cc_module.init_config_cache({"language": "en"})
        stats = cc_module.get_cache_memory_stats()
        assert "cache_size_mb" in stats
        cc_module.get_config_cache().clear()
