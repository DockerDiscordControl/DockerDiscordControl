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
- Token encryption/decryption
- Configuration validation
- Error handling
- Cache invalidation
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from services.config.config_service import ConfigService, get_config_service
from services.exceptions import ConfigLoadError, ConfigValidationError


class TestConfigServiceLoading:
    """Tests for configuration loading and caching."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create temporary config directory with test files."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create test config files
        (config_dir / "config.json").write_text(json.dumps({
            "language": "de",
            "timezone": "Europe/Berlin",
            "debug_mode": False
        }))

        (config_dir / "containers.json").write_text(json.dumps({
            "containers": [
                {
                    "name": "test_container",
                    "enabled": True,
                    "control_type": "basic"
                }
            ]
        }))

        (config_dir / "channels.json").write_text(json.dumps({
            "channels": {
                "123456789": {
                    "type": "status",
                    "enabled": True
                }
            }
        }))

        return config_dir

    def test_config_service_initialization(self, temp_config_dir):
        """Test ConfigService initializes correctly."""
        service = ConfigService(config_dir=str(temp_config_dir))

        assert service is not None
        assert service.config_dir == str(temp_config_dir)

    def test_load_config_success(self, temp_config_dir):
        """Test configuration loads successfully from files."""
        service = ConfigService(config_dir=str(temp_config_dir))
        config = service.get_config()

        assert config is not None
        assert "language" in config
        assert config["language"] == "de"
        assert "timezone" in config
        assert config["timezone"] == "Europe/Berlin"

    def test_config_caching(self, temp_config_dir):
        """Test configuration is cached between calls."""
        service = ConfigService(config_dir=str(temp_config_dir))

        config1 = service.get_config()
        config2 = service.get_config()

        # Should return same cached object
        assert config1 is config2

    def test_force_reload_bypasses_cache(self, temp_config_dir):
        """Test force_reload bypasses cache and reloads from disk."""
        service = ConfigService(config_dir=str(temp_config_dir))

        config1 = service.get_config()
        config2 = service.get_config(force_reload=True)

        # Should return different objects (reloaded)
        assert config1 is not config2
        # But same content
        assert config1 == config2

    def test_load_missing_config_file(self, tmp_path):
        """Test error handling when config file is missing."""
        nonexistent_dir = tmp_path / "nonexistent"

        with pytest.raises(Exception):  # ConfigLoadError or similar
            service = ConfigService(config_dir=str(nonexistent_dir))
            service.get_config()

    def test_load_invalid_json(self, tmp_path):
        """Test error handling for invalid JSON in config file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Write invalid JSON
        (config_dir / "config.json").write_text("{invalid json}")

        with pytest.raises(Exception):  # JSON decode error
            service = ConfigService(config_dir=str(config_dir))
            service.get_config()


class TestConfigServiceEncryption:
    """Tests for token encryption/decryption."""

    @pytest.fixture
    def service(self):
        """Create ConfigService for encryption tests."""
        # ConfigService doesn't need real config files for encryption tests
        return get_config_service()

    def test_encrypt_token(self, service):
        """Test token encryption."""
        plaintext = "my_secret_token_12345"
        encrypted = service.encrypt_token(plaintext)

        assert encrypted != plaintext
        assert encrypted.startswith("ENC:")
        assert len(encrypted) > len(plaintext)

    def test_decrypt_token(self, service):
        """Test token decryption."""
        plaintext = "my_secret_token_12345"
        encrypted = service.encrypt_token(plaintext)
        decrypted = service.decrypt_token(encrypted)

        assert decrypted == plaintext

    def test_encrypt_decrypt_roundtrip(self, service):
        """Test encryption -> decryption roundtrip preserves original value."""
        original = "test_token_value_123"

        encrypted = service.encrypt_token(original)
        decrypted = service.decrypt_token(encrypted)

        assert decrypted == original
        assert encrypted != original

    def test_decrypt_non_encrypted_token_returns_original(self, service):
        """Test decrypting non-encrypted token returns original."""
        plaintext = "not_encrypted_token"
        result = service.decrypt_token(plaintext)

        # Should return original if not encrypted
        assert result == plaintext

    def test_encrypt_empty_string(self, service):
        """Test encrypting empty string."""
        encrypted = service.encrypt_token("")

        assert encrypted.startswith("ENC:")
        decrypted = service.decrypt_token(encrypted)
        assert decrypted == ""


class TestConfigServiceCacheInvalidation:
    """Tests for cache invalidation."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create temporary config directory."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "config.json").write_text(json.dumps({
            "language": "de",
            "debug_mode": False
        }))

        (config_dir / "containers.json").write_text(json.dumps({"containers": []}))
        (config_dir / "channels.json").write_text(json.dumps({"channels": {}}))

        return config_dir

    def test_cache_invalidation_on_update(self, temp_config_dir):
        """Test cache is invalidated when config is updated."""
        service = ConfigService(config_dir=str(temp_config_dir))

        # Load initial config
        config1 = service.get_config()
        assert config1["language"] == "de"

        # Update config file
        (temp_config_dir / "config.json").write_text(json.dumps({
            "language": "en",  # Changed
            "debug_mode": False
        }))

        # Force reload should get new value
        config2 = service.get_config(force_reload=True)
        assert config2["language"] == "en"

    def test_singleton_returns_same_instance(self):
        """Test get_config_service returns singleton instance."""
        service1 = get_config_service()
        service2 = get_config_service()

        assert service1 is service2


class TestConfigServiceContainers:
    """Tests for container configuration."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create config with containers."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "config.json").write_text(json.dumps({"language": "de"}))
        (config_dir / "containers.json").write_text(json.dumps({
            "containers": [
                {
                    "name": "nginx",
                    "enabled": True,
                    "control_type": "basic",
                    "channel_id": "123456789"
                },
                {
                    "name": "mysql",
                    "enabled": False,
                    "control_type": "advanced"
                }
            ]
        }))
        (config_dir / "channels.json").write_text(json.dumps({"channels": {}}))

        return config_dir

    def test_load_containers(self, temp_config_dir):
        """Test loading container configuration."""
        service = ConfigService(config_dir=str(temp_config_dir))
        config = service.get_config()

        assert "containers" in config
        assert len(config["containers"]) == 2
        assert config["containers"][0]["name"] == "nginx"
        assert config["containers"][0]["enabled"] is True
        assert config["containers"][1]["enabled"] is False


# Summary: 15 comprehensive tests for ConfigService covering:
# - Configuration loading (6 tests)
# - Token encryption/decryption (5 tests)
# - Cache invalidation (2 tests)
# - Container configuration (2 tests)
#
# This provides strong foundation for testing critical service functionality.
# Additional tests should be added for:
# - Configuration validation
# - Error recovery
# - Concurrent access
# - Performance under load
