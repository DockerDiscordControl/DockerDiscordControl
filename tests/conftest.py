# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Pytest Configuration & Fixtures               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Global pytest configuration and fixtures for all test suites.
"""

import os
import sys
import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock
from typing import Dict, Any, Generator

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Test environment setup
os.environ["TESTING"] = "true"
os.environ["DDC_LOG_LEVEL"] = "DEBUG"

# ----------------------------------------------------------------------
# Isolated config directory
# ----------------------------------------------------------------------
# Many modules import ConfigService at module-load time; on dev hosts where
# the production ``config/`` directory has restrictive permissions (Mac
# SMB mounts mirroring the Unraid container) collection then fails before
# the first test even runs.  Point the singleton at a fresh tempdir so the
# import chain works on any environment.
import tempfile  # noqa: E402  (placed here intentionally before any project import)
_TEST_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="ddc-test-config-"))
os.environ.setdefault("DDC_CONFIG_DIR", str(_TEST_CONFIG_DIR))
# Seed minimal config files so loaders find valid JSON.
for _name, _payload in (
    ("config.json", "{}"),
    ("servers_config.json", '{"servers": []}'),
    ("channels_config.json", "{}"),
    ("docker_config.json", "{}"),
):
    _path = _TEST_CONFIG_DIR / _name
    if not _path.exists():
        _path.write_text(_payload, encoding="utf-8")

# Also redirect modules with hardcoded relative paths so that import-time
# directory creation lands somewhere writable.
_TEST_PROGRESS_DIR = Path(tempfile.mkdtemp(prefix="ddc-test-progress-"))
os.environ.setdefault("DDC_PROGRESS_DATA_DIR", str(_TEST_PROGRESS_DIR))
_TEST_METRICS_DIR = Path(tempfile.mkdtemp(prefix="ddc-test-metrics-"))
os.environ.setdefault("DDC_METRICS_DIR", str(_TEST_METRICS_DIR))


# Note: the previous session-scoped ``event_loop`` fixture override has been
# removed. ``pytest-asyncio`` 1.x manages its own per-test event loops, and
# overriding ``event_loop`` causes hard-to-diagnose pollution when many async
# tests run in the same session (loops get reused across tests that expected
# fresh loops). Configure scopes via ``asyncio_mode`` in pytest.ini instead.


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for test configuration files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_docker_client():
    """Mock Docker client for testing without real Docker daemon."""
    mock_client = Mock()

    # Mock containers list
    mock_container = Mock()
    mock_container.name = "test_container"
    mock_container.status = "running"
    mock_container.attrs = {
        "State": {"Status": "running", "Running": True},
        "Config": {"Image": "nginx:latest"},
        "NetworkSettings": {"IPAddress": "172.17.0.2"}
    }

    mock_client.containers.list.return_value = [mock_container]
    mock_client.containers.get.return_value = mock_container

    return mock_client


@pytest.fixture
def mock_discord_ctx():
    """Mock Discord application context for testing Discord commands."""
    ctx = AsyncMock()
    ctx.guild_id = 123456789
    ctx.channel_id = 987654321
    ctx.user.id = 111222333
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    return ctx


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """Sample configuration data for testing."""
    return {
        "bot_token": "test_token_12345",
        "guild_id": "123456789",
        "language": "en",
        "timezone": "Europe/Berlin",
        "heartbeat": {
            "enabled": True,
            "interval": 300
        },
        "permissions": {
            "admin_roles": ["Admin"],
            "channels": {
                "control_channels": ["987654321"],
                "status_channels": ["111222333"]
            }
        }
    }


@pytest.fixture
def sample_mech_state():
    """Sample mech state for testing donation system."""
    return {
        "total_donated": 125.50,
        "level": 3,
        "fuel": 85.2,
        "last_update": "2025-01-01T12:00:00Z"
    }


@pytest.fixture
def mock_flask_app():
    """Mock Flask application for Web UI testing."""
    from flask import Flask

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        yield app


@pytest.fixture
def sample_container_info():
    """Sample container info for testing."""
    return {
        "enabled": True,
        "show_ip": True,
        "custom_ip": "192.168.1.100",
        "custom_port": "8080",
        "custom_text": "Test Container Info",
        "protected_enabled": False,
        "protected_content": "",
        "protected_password": ""
    }


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Automatic cleanup after each test."""
    yield
    # Cleanup any test artifacts, reset mocks, etc.
    # This runs after each test automatically


# Performance testing fixtures
@pytest.fixture
def performance_containers(request):
    """Generate mock containers for performance testing."""
    container_count = getattr(request, 'param', 50)
    containers = []

    for i in range(container_count):
        container = Mock()
        container.name = f"test_container_{i:03d}"
        container.status = "running" if i % 4 != 0 else "stopped"
        container.attrs = {
            "State": {
                "Status": container.status,
                "Running": container.status == "running"
            },
            "Config": {"Image": f"nginx:test_{i}"},
            "NetworkSettings": {"IPAddress": f"172.17.0.{i + 2}"}
        }
        containers.append(container)

    return containers


# Security testing fixtures
@pytest.fixture
def security_test_payloads():
    """Common security test payloads for input validation testing."""
    return {
        "xss_payloads": [
            "<script>alert('XSS')</script>",
            "javascript:alert('XSS')",
            "<img src=x onerror=alert('XSS')>",
        ],
        "sql_injection_payloads": [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "UNION SELECT * FROM users--",
        ],
        "command_injection_payloads": [
            "; ls -la",
            "| cat /etc/passwd",
            "&& rm -rf /",
        ],
        "path_traversal_payloads": [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2f",
        ]
    }


# Markers for test categorization
pytestmark = [
    pytest.mark.filterwarnings("ignore:.*unclosed.*:ResourceWarning"),
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]
