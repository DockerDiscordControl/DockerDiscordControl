# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - ConfigService Unit Tests                       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for ConfigService.

This test suite provides comprehensive coverage for configuration management:
- Configuration loading and caching
- Token encryption/decryption (PBKDF2 + Fernet, password_hash required)
- Configuration error handling
- Cache invalidation
- Container loading from modular structure (config/containers/*.json)

NOTE on the API:
    * ``ConfigService`` is a singleton (``__new__`` ignores constructor kwargs).
      Tests redirect the singleton to a temp dir by patching its instance
      attributes plus the loader service, mirroring the approach used by
      ``tests/performance/test_config_service_performance.py``.
    * ``encrypt_token``/``decrypt_token`` REQUIRE a ``password_hash`` argument.
    * Encrypted output is a Fernet token (no ``ENC:`` prefix).
    * Containers live in ``config/containers/<name>.json`` files; only entries
      with ``"active": true`` are returned in ``config["servers"]``.
"""

import pytest
import json
from pathlib import Path

from services.config.config_service import ConfigService, get_config_service
from services.config.config_loader_service import ConfigLoaderService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redirect_service(service: ConfigService, config_dir: Path) -> ConfigService:
    """Point the singleton ConfigService at ``config_dir`` and refresh the
    loader / cache services so the redirect actually takes effect.

    Mirrors ``tests/performance/test_config_service_performance.py``.
    """
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

    service._loader_service = ConfigLoaderService(
        service.config_dir,
        service.channels_dir,
        service.containers_dir,
        service.main_config_file,
        service.auth_config_file,
        service.heartbeat_config_file,
        service.web_ui_config_file,
        service.docker_settings_file,
        service.bot_config_file,
        service.docker_config_file,
        service.web_config_file,
        service.channels_config_file,
        service._load_json_file,
        service._validation_service,
    )

    # Clear caches so previous tests don't bleed into this one.
    service._cache_service.invalidate_cache()
    service._cache_service.clear_token_cache()

    return service


# ---------------------------------------------------------------------------
# Loading / caching
# ---------------------------------------------------------------------------

class TestConfigServiceLoading:
    """Tests for configuration loading and caching."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create temporary config directory with test files (modular layout)."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Main config file (config.json)
        (config_dir / "config.json").write_text(json.dumps({
            "language": "de",
            "timezone": "Europe/Berlin",
            "debug_mode": False,
        }))

        # Modular containers/ directory with one active container
        containers_dir = config_dir / "containers"
        containers_dir.mkdir()
        (containers_dir / "test_container.json").write_text(json.dumps({
            "container_name": "test_container",
            "active": True,
            "control_type": "basic",
        }))

        # Modular channels/ directory (empty default)
        channels_dir = config_dir / "channels"
        channels_dir.mkdir()

        return config_dir

    def test_config_service_initialization(self, temp_config_dir):
        """ConfigService can be redirected at a temp dir and exposes config_dir."""
        service = _redirect_service(get_config_service(), temp_config_dir)

        assert service is not None
        # config_dir is stored as a Path on the service instance.
        assert Path(service.config_dir) == temp_config_dir

    def test_load_config_success(self, temp_config_dir):
        """Configuration loads successfully from config.json."""
        service = _redirect_service(get_config_service(), temp_config_dir)
        config = service.get_config()

        assert config is not None
        assert config.get("language") == "de"
        assert config.get("timezone") == "Europe/Berlin"

    def test_config_caching(self, temp_config_dir):
        """Cached calls return equal data without hitting the loader.

        The cache service returns ``.copy()`` defensively, so identity (``is``)
        is intentionally NOT preserved. We instead assert equality and that
        the loader is not invoked on a cache hit.
        """
        service = _redirect_service(get_config_service(), temp_config_dir)

        config1 = service.get_config()

        # Spy on the loader: if the cache works, this is never called.
        original_load = service._loader_service.load_modular_config
        call_count = {"n": 0}

        def counting_load():
            call_count["n"] += 1
            return original_load()

        service._loader_service.load_modular_config = counting_load
        try:
            config2 = service.get_config()
        finally:
            service._loader_service.load_modular_config = original_load

        assert config1 == config2
        assert call_count["n"] == 0, "Loader should not be invoked on cache hit"

    def test_force_reload_bypasses_cache(self, temp_config_dir):
        """force_reload=True bypasses the cache and reloads from disk."""
        service = _redirect_service(get_config_service(), temp_config_dir)

        config1 = service.get_config()

        # Update the on-disk config so a real reload returns different content.
        (temp_config_dir / "config.json").write_text(json.dumps({
            "language": "en",
            "timezone": "Europe/Berlin",
            "debug_mode": False,
        }))

        config2 = service.get_config(force_reload=True)

        assert config1.get("language") == "de"
        assert config2.get("language") == "en"

    def test_load_missing_config_file(self, tmp_path):
        """Missing config dir is handled gracefully and returns a dict."""
        nonexistent_dir = tmp_path / "nonexistent"
        # Create the dir but leave it completely empty so loader has nothing
        # to read; ConfigService is tolerant of missing modular files.
        nonexistent_dir.mkdir()

        service = _redirect_service(get_config_service(), nonexistent_dir)
        config = service.get_config()

        # Loader returns an (essentially) empty config rather than raising.
        assert isinstance(config, dict)
        assert config.get("servers", []) == []

    def test_load_invalid_json(self, tmp_path):
        """Invalid JSON in main config does not crash get_config().

        ``_load_json_file`` swallows ``json.JSONDecodeError`` and returns the
        provided defaults, so the service stays usable even with a corrupt
        ``config.json``.
        """
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{invalid json}")

        service = _redirect_service(get_config_service(), config_dir)
        config = service.get_config()

        # No language key from the corrupt file, but no exception either.
        assert isinstance(config, dict)
        assert "language" not in config or config["language"] in ("", "en", "de")


# ---------------------------------------------------------------------------
# Token encryption / decryption
# ---------------------------------------------------------------------------

class TestConfigServiceEncryption:
    """Tests for token encryption / decryption.

    The real API requires ``password_hash`` for both ``encrypt_token`` and
    ``decrypt_token``. The encrypted output is a raw Fernet token (no ``ENC:``
    prefix).
    """

    @pytest.fixture
    def service(self):
        return get_config_service()

    @pytest.fixture
    def password_hash(self):
        # ``encrypt_token`` / ``decrypt_token`` only require a non-empty
        # string — they feed it into PBKDF2HMAC themselves. Using a plain
        # string here keeps the test independent of werkzeug's hash backend
        # (which depends on hashlib.scrypt, missing on some Python builds).
        return "pbkdf2:sha256:600000$abcdefgh$" + "0" * 64

    def test_encrypt_token(self, service, password_hash):
        """Encrypting a non-empty token yields a different, longer string."""
        plaintext = "my_secret_token_12345"
        encrypted = service.encrypt_token(plaintext, password_hash)

        assert encrypted is not None
        assert encrypted != plaintext
        assert len(encrypted) > len(plaintext)
        # Fernet tokens are URL-safe base64 starting with the version byte
        # ``gAAAAA`` (0x80 in the first byte).
        assert encrypted.startswith("gAAAAA")

    def test_decrypt_token(self, service, password_hash):
        """A token encrypted with a password hash decrypts back to the original."""
        plaintext = "my_secret_token_12345"
        encrypted = service.encrypt_token(plaintext, password_hash)
        decrypted = service.decrypt_token(encrypted, password_hash)

        assert decrypted == plaintext

    def test_encrypt_decrypt_roundtrip(self, service, password_hash):
        """encrypt -> decrypt preserves the original value and changes ciphertext."""
        original = "test_token_value_123"

        encrypted = service.encrypt_token(original, password_hash)
        decrypted = service.decrypt_token(encrypted, password_hash)

        assert decrypted == original
        assert encrypted != original

    def test_decrypt_non_encrypted_token_raises(self, service, password_hash):
        """Decrypting a non-Fernet token raises TokenEncryptionError.

        The ``decrypt_token`` API does NOT silently return the input on
        failure — it raises. ``_decrypt_token_if_needed`` is the layer that
        decides whether decryption should be attempted at all.
        """
        from services.exceptions import TokenEncryptionError

        with pytest.raises(TokenEncryptionError):
            service.decrypt_token("not_encrypted_token", password_hash)

    def test_encrypt_empty_string_returns_none(self, service, password_hash):
        """Encrypting an empty string returns None (guard clause in production)."""
        result = service.encrypt_token("", password_hash)
        assert result is None


# ---------------------------------------------------------------------------
# Cache invalidation / singleton
# ---------------------------------------------------------------------------

class TestConfigServiceCacheInvalidation:
    """Tests for cache invalidation."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "config.json").write_text(json.dumps({
            "language": "de",
            "debug_mode": False,
        }))

        # ``has_real_modular_structure`` requires at least one *.json file in
        # either channels/ or containers/. Drop a placeholder so the loader
        # picks the real-modular path (which reads config.json) instead of
        # the virtual-modular path (which expects bot_config.json etc.).
        containers_dir = config_dir / "containers"
        containers_dir.mkdir()
        (containers_dir / "_placeholder.json").write_text(json.dumps({
            "container_name": "_placeholder",
            "active": False,
        }))
        (config_dir / "channels").mkdir()
        return config_dir

    def test_cache_invalidation_on_update(self, temp_config_dir):
        """force_reload picks up edits to config.json."""
        service = _redirect_service(get_config_service(), temp_config_dir)

        config1 = service.get_config()
        assert config1["language"] == "de"

        (temp_config_dir / "config.json").write_text(json.dumps({
            "language": "en",
            "debug_mode": False,
        }))

        config2 = service.get_config(force_reload=True)
        assert config2["language"] == "en"

    def test_singleton_returns_same_instance(self):
        """get_config_service returns the same singleton instance."""
        service1 = get_config_service()
        service2 = get_config_service()
        assert service1 is service2


# ---------------------------------------------------------------------------
# Container loading
# ---------------------------------------------------------------------------

class TestConfigServiceContainers:
    """Tests for container configuration loading."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create a config dir with two containers in modular layout.

        Only ``active: true`` entries end up in ``config['servers']``.
        """
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "config.json").write_text(json.dumps({"language": "de"}))

        containers_dir = config_dir / "containers"
        containers_dir.mkdir()
        (containers_dir / "nginx.json").write_text(json.dumps({
            "container_name": "nginx",
            "active": True,
            "control_type": "basic",
            "channel_id": "123456789",
            "order": 1,
        }))
        (containers_dir / "mysql.json").write_text(json.dumps({
            "container_name": "mysql",
            "active": False,
            "control_type": "advanced",
            "order": 2,
        }))

        (config_dir / "channels").mkdir()
        return config_dir

    def test_load_containers(self, temp_config_dir):
        """Only active containers are surfaced under config['servers']."""
        service = _redirect_service(get_config_service(), temp_config_dir)
        config = service.get_config()

        assert "servers" in config
        servers = config["servers"]
        # Only the active container (nginx) is loaded.
        assert len(servers) == 1
        assert servers[0]["container_name"] == "nginx"
        assert servers[0]["active"] is True


# Summary: 14 tests covering ConfigService against the real (singleton) API:
# - Loading + caching (6)
# - Token encryption/decryption with password_hash (5)
# - Cache invalidation + singleton identity (2)
# - Modular container loading (1)
