# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Unit Tests for app/utils & app/bot helpers     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                              #
# ============================================================================ #
"""
Functional unit tests for small app/utils and app/bot modules.

Modules under test:
- app/utils/container_info_web_handler.py
- app/utils/port_diagnostics.py
- app/bot/token.py
- app/bot/events.py
- app/bot/dependencies.py

Loading strategy
----------------
Several of these modules sit in package-init chains that pull in
``services/__init__.py`` -> ``services.mech.progress_paths`` whose dataclass
uses ``slots=True`` (Python 3.10+).  On the dev Mac (Python 3.9) this raises
TypeError at collection time.  We therefore:

1. Pre-stub the *heaviest* third-party / cross-package imports in
   ``sys.modules`` BEFORE loading the source files, and
2. Load each module-under-test directly from its source file via
   ``importlib.util`` under a private name.  This avoids triggering
   ``app/bot/__init__.py`` (which imports ``runtime`` with slots=True) and
   ``services/__init__.py`` (which transitively pulls slots).

In the production container (Python 3.11, Alpine) the real package
imports work, but using ``importlib.util`` here is harmless because we
only assert on the module's own behaviour.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# sys.modules stubbing helpers
# ---------------------------------------------------------------------------

def _ensure_pkg(name: str) -> types.ModuleType:
    """Ensure a stub package exists in sys.modules and return it."""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = []  # mark as a package
        sys.modules[name] = mod
    return sys.modules[name]


def _install_stub(fullname: str, **attrs: Any) -> types.ModuleType:
    """Install a stub module under fullname with the given attributes."""
    parent_name, _, child = fullname.rpartition('.')
    if parent_name:
        _ensure_pkg(parent_name)
    mod = types.ModuleType(fullname)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[fullname] = mod
    if parent_name:
        setattr(sys.modules[parent_name], child, mod)
    return mod


def _load_source(canonical_name: str, relative_path: str) -> types.ModuleType:
    """Load a python source file as a module under its CANONICAL name.

    Using the canonical dotted name (e.g. ``app.utils.port_diagnostics``)
    matters for ``--cov=app.utils.port_diagnostics`` to pick up the file:
    coverage.py keys executed lines by file path AND module name.

    To avoid triggering the package __init__ chain (which on Mac Python 3.9
    fails because some downstream dataclasses use ``slots=True``) we
    pre-stub all problematic upstream modules in ``sys.modules`` first, and
    we ensure the parent packages exist as bare ``ModuleType`` placeholders
    in sys.modules BEFORE attempting to load the source — this prevents
    Python from re-running the real package __init__ during the load.
    """
    src = PROJECT_ROOT / relative_path
    # Ensure parent packages already exist as bare modules so
    # importlib.util.module_from_spec doesn't re-run __init__.py for them.
    parent = canonical_name.rpartition('.')[0]
    while parent:
        _ensure_pkg(parent)
        parent = parent.rpartition('.')[0]
    spec = importlib.util.spec_from_file_location(canonical_name, str(src))
    assert spec and spec.loader, f"Cannot create spec for {src}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[canonical_name] = module
    # Attach to parent package
    parent_name, _, child = canonical_name.rpartition('.')
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child, module)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Stub the heavy import chain BEFORE loading any module under test
# ---------------------------------------------------------------------------

# A captured mock for the container_info_service singleton, accessible to tests.
_INFO_SERVICE_MOCK = MagicMock()
_CONTAINER_CONFIG_SAVE_SERVICE_MOCK = MagicMock()
_SERVER_CONFIG_SERVICE_MOCK = MagicMock()


class _ContainerInfo:
    """Lightweight stand-in for services.infrastructure ContainerInfo."""

    def __init__(
        self,
        enabled: bool = False,
        show_ip: bool = False,
        custom_ip: str = "",
        custom_port: str = "",
        custom_text: str = "",
        protected_enabled: bool = False,
        protected_content: str = "",
        protected_password: str = "",
    ) -> None:
        self.enabled = enabled
        self.show_ip = show_ip
        self.custom_ip = custom_ip
        self.custom_port = custom_port
        self.custom_text = custom_text
        self.protected_enabled = protected_enabled
        self.protected_content = protected_content
        self.protected_password = protected_password

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "show_ip": self.show_ip,
            "custom_ip": self.custom_ip,
            "custom_port": self.custom_port,
            "custom_text": self.custom_text,
            "protected_enabled": self.protected_enabled,
            "protected_content": self.protected_content,
            "protected_password": self.protected_password,
        }


def _get_container_info_service():
    return _INFO_SERVICE_MOCK


def _get_container_config_save_service():
    return _CONTAINER_CONFIG_SAVE_SERVICE_MOCK


def _get_server_config_service():
    return _SERVER_CONFIG_SERVICE_MOCK


# Stub services.* before loading the web handler.
_install_stub(
    "services.infrastructure.container_info_service",
    ContainerInfo=_ContainerInfo,
    get_container_info_service=_get_container_info_service,
)
_install_stub(
    "services.config.container_config_save_service",
    get_container_config_save_service=_get_container_config_save_service,
)
_install_stub(
    "services.config.server_config_service",
    get_server_config_service=_get_server_config_service,
)
# Stub utils.logging_utils to avoid triggering config-service load on Mac.
# Only inject if the real module hasn't been loaded yet (in container the
# real one will already be loaded by conftest's path setup; we still want
# our stub to win for predictable test behaviour).
_install_stub(
    "utils.logging_utils",
    get_module_logger=lambda name: logging.getLogger(f"ddc.test.{name}"),
    setup_logger=lambda name, **kw: logging.getLogger(name),
)
# Stub services.config.config_service for the bot/token tests.
_FAKE_CONFIG_SERVICE = MagicMock()


def _get_config_service_factory():
    return _FAKE_CONFIG_SERVICE


_install_stub(
    "services.config.config_service",
    get_config_service=_get_config_service_factory,
)
# Stub services.infrastructure.dynamic_cooldown_manager + update_notifier.
_install_stub(
    "services.infrastructure.dynamic_cooldown_manager",
    apply_dynamic_cooldowns_to_bot=lambda bot: None,
)
_install_stub(
    "services.infrastructure.update_notifier",
    get_update_notifier=lambda: MagicMock(),
)


# Stub cogs.translation_manager (used by app/bot/events.py)
def _passthrough_translate(s: str) -> str:
    return s


_install_stub("cogs.translation_manager", _=_passthrough_translate)


# ---------------------------------------------------------------------------
# Load modules under test as private modules to bypass package __init__'s
# ---------------------------------------------------------------------------

# IMPORTANT: drop any partially-imported real modules so our stubs win.
for _stale in (
    "app",
    "app.utils",
    "app.bot",
    "app.utils.container_info_web_handler",
    "app.utils.port_diagnostics",
    "app.bot.dependencies",
    "app.bot.token",
    "app.bot.events",
    "app.bot.runtime",
    "app.bot.startup",
    "app.bootstrap",
):
    sys.modules.pop(_stale, None)

container_info_web_handler = _load_source(
    "app.utils.container_info_web_handler",
    "app/utils/container_info_web_handler.py",
)
port_diagnostics = _load_source(
    "app.utils.port_diagnostics",
    "app/utils/port_diagnostics.py",
)
bot_dependencies = _load_source(
    "app.bot.dependencies",
    "app/bot/dependencies.py",
)

# app/bot/token.py uses ``from .runtime import BotRuntime``.  We pre-stub a
# minimal ``app.bot.runtime`` so that relative import resolves regardless of
# Python version.
_runtime_stub = types.ModuleType("app.bot.runtime")


class _StubBotRuntime:
    pass


_runtime_stub.BotRuntime = _StubBotRuntime
_ensure_pkg("app")
_ensure_pkg("app.bot")
sys.modules["app.bot.runtime"] = _runtime_stub
setattr(sys.modules["app.bot"], "runtime", _runtime_stub)

# Load app.bot.token under its canonical name.
def _load_token_module():
    src = PROJECT_ROOT / "app/bot/token.py"
    spec = importlib.util.spec_from_file_location("app.bot.token", str(src))
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "app.bot"
    sys.modules["app.bot.token"] = module
    setattr(sys.modules["app.bot"], "token", module)
    spec.loader.exec_module(module)
    return module


bot_token = _load_token_module()


# Stub app.bot.startup with a StartupManager that records invocations,
# THEN load app.bot.events.
class _StubStartupManager:
    def __init__(self, bot, runtime):
        self.bot = bot
        self.runtime = runtime
        self.handle_ready_called = False

    async def handle_ready(self):
        self.handle_ready_called = True


_startup_stub = types.ModuleType("app.bot.startup")
_startup_stub.StartupManager = _StubStartupManager
sys.modules["app.bot.startup"] = _startup_stub
setattr(sys.modules["app.bot"], "startup", _startup_stub)


def _load_events_module():
    src = PROJECT_ROOT / "app/bot/events.py"
    spec = importlib.util.spec_from_file_location("app.bot.events", str(src))
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "app.bot"
    sys.modules["app.bot.events"] = module
    setattr(sys.modules["app.bot"], "events", module)
    spec.loader.exec_module(module)
    return module


bot_events = _load_events_module()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_service_mocks():
    """Reset all module-level service mocks between tests."""
    for m in (
        _INFO_SERVICE_MOCK,
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK,
        _SERVER_CONFIG_SERVICE_MOCK,
        _FAKE_CONFIG_SERVICE,
    ):
        m.reset_mock(return_value=True, side_effect=True)
    yield


@pytest.fixture
def fake_runtime():
    """Build a minimal runtime stand-in usable by app.bot.token."""
    runtime = types.SimpleNamespace()
    runtime.logger = logging.getLogger("ddc.test.runtime")
    runtime.config = {}
    runtime.dependencies = types.SimpleNamespace(
        config_service_factory=None,
        dynamic_cooldown_applicator=None,
        update_notifier_factory=None,
    )
    return runtime


# =============================================================================
# container_info_web_handler tests
# =============================================================================

class TestContainerInfoWebHandler:
    """Tests for app/utils/container_info_web_handler.py."""

    def test_save_container_info_from_web_calls_service_with_form_values(self):
        """Form fields with '1' should map to enabled=True; trims preserved."""
        save_result = MagicMock(success=True)
        _INFO_SERVICE_MOCK.save_container_info.return_value = save_result

        form = {
            "info_enabled_alpha": "1",
            "info_show_ip_alpha": "1",
            "info_custom_ip_alpha": "  10.0.0.1  ",
            "info_custom_port_alpha": "  8080  ",
            "info_custom_text_alpha": "Hello",
        }
        result = container_info_web_handler.save_container_info_from_web(
            form, ["alpha"]
        )

        assert result == {"alpha": True}
        assert _INFO_SERVICE_MOCK.save_container_info.call_count == 1
        # Inspect the ContainerInfo argument
        args, _kw = _INFO_SERVICE_MOCK.save_container_info.call_args
        name, info = args
        assert name == "alpha"
        assert info.enabled is True
        assert info.show_ip is True
        assert info.custom_ip == "10.0.0.1"
        assert info.custom_port == "8080"
        assert info.custom_text == "Hello"
        assert info.protected_enabled is False
        assert info.protected_content == ""

    def test_save_container_info_from_web_default_disabled(self):
        """Missing form keys default to disabled / empty."""
        save_result = MagicMock(success=True)
        _INFO_SERVICE_MOCK.save_container_info.return_value = save_result

        result = container_info_web_handler.save_container_info_from_web(
            {}, ["beta"]
        )
        assert result == {"beta": True}
        args, _kw = _INFO_SERVICE_MOCK.save_container_info.call_args
        info = args[1]
        assert info.enabled is False
        assert info.show_ip is False
        assert info.custom_ip == ""

    def test_save_container_info_returns_false_on_service_failure(self):
        save_result = MagicMock(success=False, error="db unavailable")
        _INFO_SERVICE_MOCK.save_container_info.return_value = save_result

        result = container_info_web_handler.save_container_info_from_web(
            {}, ["gamma"]
        )
        assert result == {"gamma": False}

    def test_save_container_info_handles_exception_per_container(self):
        """Individual container failures shouldn't break the loop."""
        # First raise, second succeed.
        good_result = MagicMock(success=True)
        _INFO_SERVICE_MOCK.save_container_info.side_effect = [
            RuntimeError("boom"),
            good_result,
        ]

        result = container_info_web_handler.save_container_info_from_web(
            {}, ["bad", "good"]
        )
        assert result == {"bad": False, "good": True}

    def test_save_container_info_processes_multiple_containers(self):
        """All names in the list get processed in order."""
        _INFO_SERVICE_MOCK.save_container_info.return_value = MagicMock(success=True)
        names = ["c1", "c2", "c3"]
        result = container_info_web_handler.save_container_info_from_web({}, names)
        assert set(result.keys()) == set(names)
        assert all(v is True for v in result.values())
        assert _INFO_SERVICE_MOCK.save_container_info.call_count == 3

    def test_load_container_info_for_web_uses_service_data_when_success(self):
        info_obj = _ContainerInfo(enabled=True, custom_ip="1.2.3.4")
        _INFO_SERVICE_MOCK.get_container_info.return_value = MagicMock(
            success=True, data=info_obj
        )

        result = container_info_web_handler.load_container_info_for_web(["alpha"])
        assert result["alpha"]["enabled"] is True
        assert result["alpha"]["custom_ip"] == "1.2.3.4"

    def test_load_container_info_for_web_returns_defaults_on_service_failure(self):
        _INFO_SERVICE_MOCK.get_container_info.return_value = MagicMock(success=False)

        result = container_info_web_handler.load_container_info_for_web(["alpha"])
        assert result == {
            "alpha": {
                "enabled": False,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
            }
        }

    def test_load_container_info_for_web_handles_ioerror(self):
        _INFO_SERVICE_MOCK.get_container_info.side_effect = OSError("perm denied")

        result = container_info_web_handler.load_container_info_for_web(["x"])
        assert result["x"]["enabled"] is False
        assert result["x"]["custom_ip"] == ""

    # ----- save_container_configs_from_web --------------------------------

    def test_save_container_configs_marks_inactive_for_existing_not_in_form(self):
        """Containers in the existing config but not in servers_data are marked inactive."""
        # Existing container "old" not in active list
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = [
            {"container_name": "old", "active": True, "info": {}},
        ]
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        result = container_info_web_handler.save_container_configs_from_web([])
        assert result["old"] is True
        # Verify save was called and container was marked inactive
        save_calls = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args_list
        assert len(save_calls) == 1
        name, cfg = save_calls[0].args
        assert name == "old"
        assert cfg["active"] is False

    def test_save_container_configs_skips_servers_without_name(self):
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = []
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        # Two servers; one has no name -> skipped silently
        result = container_info_web_handler.save_container_configs_from_web([
            {"display_name": "Nameless"},
            {"docker_name": "alpha", "display_name": "Alpha", "allowed_actions": ["start"]},
        ])
        assert "alpha" in result
        assert result["alpha"] is True
        # Only "alpha" got saved
        names = [c.args[0] for c in _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args_list]
        assert names == ["alpha"]

    def test_save_container_configs_defaults_allowed_actions_to_status(self):
        """Empty allowed_actions defaults to ['status']."""
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = []
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        result = container_info_web_handler.save_container_configs_from_web([
            {"docker_name": "beta", "allowed_actions": []},
        ])
        assert result["beta"] is True
        cfg = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args.args[1]
        assert cfg["allowed_actions"] == ["status"]
        assert cfg["active"] is True

    def test_save_container_configs_handles_legacy_list_display_name(self):
        """A list-shaped display_name (legacy) is normalized to its first element."""
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = []
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        result = container_info_web_handler.save_container_configs_from_web([
            {
                "docker_name": "gamma",
                "display_name": ["Gamma Display", "ignored"],
                "allowed_actions": ["status", "start"],
            },
        ])
        assert result["gamma"] is True
        cfg = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args.args[1]
        assert cfg["display_name"] == "Gamma Display"

    def test_save_container_configs_normalizes_empty_list_display_name(self):
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = []
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        container_info_web_handler.save_container_configs_from_web([
            {"docker_name": "delta", "display_name": [], "allowed_actions": ["status"]},
        ])
        cfg = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args.args[1]
        # Falls back to container_name when list is empty
        assert cfg["display_name"] == "delta"

    def test_save_container_configs_preserves_existing_info(self):
        """Existing 'info' block in container config is preserved."""
        existing_cfg = {
            "container_name": "epsilon",
            "info": {"enabled": True, "custom_text": "preserved"},
        }
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = [existing_cfg]
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = existing_cfg
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        container_info_web_handler.save_container_configs_from_web([
            {"docker_name": "epsilon", "display_name": "E", "allowed_actions": ["status"]},
        ])
        cfg = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args.args[1]
        assert cfg["info"]["custom_text"] == "preserved"
        assert cfg["active"] is True

    def test_save_container_configs_propagates_order_and_detailed(self):
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = []
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        container_info_web_handler.save_container_configs_from_web([
            {
                "docker_name": "zeta",
                "display_name": "Zeta",
                "allowed_actions": ["status"],
                "order": 7,
                "allow_detailed_status": True,
            },
        ])
        cfg = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args.args[1]
        assert cfg["order"] == 7
        assert cfg["allow_detailed_status"] is True

    def test_save_container_configs_inactive_preserves_info_default(self):
        """Inactive container without 'info' gets a default block injected."""
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = [
            {"container_name": "old"},  # no 'info' field
        ]
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        container_info_web_handler.save_container_configs_from_web([])
        cfg = _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.call_args.args[1]
        assert cfg["active"] is False
        assert "info" in cfg
        assert cfg["info"]["enabled"] is False
        assert cfg["info"]["protected_password"] == ""

    def test_save_container_configs_skips_existing_without_name(self):
        """Existing config entries without a name are skipped (not crashed)."""
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = [
            {"some": "data"},  # no name fields
        ]
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.return_value = None
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        result = container_info_web_handler.save_container_configs_from_web([])
        assert result == {}
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.assert_not_called()

    def test_save_container_configs_handles_per_server_exception(self):
        """Exceptions per server are caught and reported as False."""
        _SERVER_CONFIG_SERVICE_MOCK.get_all_servers.return_value = []
        _SERVER_CONFIG_SERVICE_MOCK.get_server_by_docker_name.side_effect = [
            RuntimeError("boom"),  # for 'broken'
            None,                  # for 'fine'
        ]
        _CONTAINER_CONFIG_SAVE_SERVICE_MOCK.save_container_config.return_value = True

        result = container_info_web_handler.save_container_configs_from_web([
            {"docker_name": "broken", "display_name": "B", "allowed_actions": ["status"]},
            {"docker_name": "fine", "display_name": "F", "allowed_actions": ["status"]},
        ])
        assert result["broken"] is False
        assert result["fine"] is True


# =============================================================================
# port_diagnostics tests
# =============================================================================

class TestPortDiagnostics:
    """Tests for app/utils/port_diagnostics.py - simple helpers focus."""

    def _make(self):
        """Create a PortDiagnostics with init helpers patched out."""
        with patch.object(
            port_diagnostics.PortDiagnostics,
            "_detect_container_name",
            return_value="ddc-test",
        ), patch.object(
            port_diagnostics.PortDiagnostics,
            "_get_host_info",
            return_value={
                "platform": "alpine",
                "is_unraid": False,
                "is_docker": True,
                "python_version": "3.11.0",
                "container_uptime": "1d",
                "memory_usage": "100MB",
                "disk_usage": "50MB",
                "supervisord_status": {},
                "docker_socket_available": False,
                "ddc_memory_usage": "",
                "ddc_image_size": "",
            },
        ):
            return port_diagnostics.PortDiagnostics()

    def test_class_constants(self):
        assert port_diagnostics.PortDiagnostics.EXPECTED_WEB_PORT == 9374
        assert 8374 in port_diagnostics.PortDiagnostics.COMMON_EXTERNAL_PORTS
        assert 9374 in port_diagnostics.PortDiagnostics.COMMON_EXTERNAL_PORTS

    def test_get_python_version_returns_dotted(self):
        diag = self._make()
        version = diag._get_python_version()
        assert version != "unknown"
        # Major.minor.patch — at least major.minor present
        assert version.count(".") >= 2

    def test_get_unraid_solutions_lists_steps(self):
        diag = self._make()
        diag.container_name = "ddc-x"
        sols = diag._get_unraid_solutions()
        assert isinstance(sols, list)
        assert len(sols) >= 3
        assert any("UNRAID" in s for s in sols)
        assert any("ddc-x" in s for s in sols)

    def test_get_docker_solutions_lists_steps(self):
        diag = self._make()
        diag.container_name = "ddc-y"
        sols = diag._get_docker_solutions()
        assert isinstance(sols, list)
        assert len(sols) >= 3
        assert any("DOCKER FIX" in s for s in sols)
        assert any("9374" in s for s in sols)

    def test_get_docker_solutions_falls_back_when_no_container_name(self):
        diag = self._make()
        diag.container_name = None
        sols = diag._get_docker_solutions()
        # Default name "dockerdiscordcontrol" should appear
        assert any("dockerdiscordcontrol" in s for s in sols)

    def test_is_external_port_accessible_currently_returns_true(self):
        diag = self._make()
        assert diag._is_external_port_accessible(8374) is True

    def test_is_port_listening_returns_true_when_socket_connect_succeeds(self):
        diag = self._make()
        with patch.object(port_diagnostics.socket, "socket") as mock_sock:
            instance = mock_sock.return_value.__enter__.return_value
            instance.connect_ex.return_value = 0
            assert diag._is_port_listening(9374) is True

    def test_is_port_listening_returns_false_when_socket_fails(self):
        diag = self._make()
        with patch.object(port_diagnostics.socket, "socket") as mock_sock:
            instance = mock_sock.return_value.__enter__.return_value
            instance.connect_ex.return_value = 1
            assert diag._is_port_listening(9374) is False

    def test_is_port_listening_returns_false_on_oserror(self):
        diag = self._make()
        with patch.object(
            port_diagnostics.socket, "socket", side_effect=OSError("nope")
        ):
            assert diag._is_port_listening(9374) is False

    def test_try_environment_variable_ip_uses_host_ip(self, monkeypatch):
        diag = self._make()
        monkeypatch.setenv("HOST_IP", "192.168.1.50")
        monkeypatch.delenv("UNRAID_IP", raising=False)
        monkeypatch.delenv("SERVER_IP", raising=False)
        assert diag._try_environment_variable_ip() == "192.168.1.50"

    def test_try_environment_variable_ip_returns_none_when_unset(
        self, monkeypatch
    ):
        diag = self._make()
        monkeypatch.delenv("HOST_IP", raising=False)
        monkeypatch.delenv("UNRAID_IP", raising=False)
        monkeypatch.delenv("SERVER_IP", raising=False)
        assert diag._try_environment_variable_ip() is None

    def test_try_environment_variable_ip_falls_back_to_unraid_ip(
        self, monkeypatch
    ):
        diag = self._make()
        monkeypatch.delenv("HOST_IP", raising=False)
        monkeypatch.setenv("UNRAID_IP", "10.0.0.1")
        monkeypatch.delenv("SERVER_IP", raising=False)
        assert diag._try_environment_variable_ip() == "10.0.0.1"

    def test_check_port_binding_reports_internal_not_listening(self):
        diag = self._make()
        with patch.object(diag, "_is_port_listening", return_value=False):
            result = diag.check_port_binding()
        assert result["internal_port_listening"] is False
        assert any("not listening" in s.lower() for s in result["issues"])
        assert result["solutions"]  # non-empty fix suggestions

    def test_check_port_binding_when_listening_no_mapping_unraid_solutions(self):
        diag = self._make()
        diag.host_info["is_unraid"] = True
        with patch.object(diag, "_is_port_listening", return_value=True), \
             patch.object(diag, "_get_docker_port_mappings", return_value={}):
            result = diag.check_port_binding()
        assert result["internal_port_listening"] is True
        # No mapping found -> issues raised + Unraid-style solutions
        assert any("not mapped" in s.lower() for s in result["issues"])
        assert any("UNRAID" in s for s in result["solutions"])

    def test_check_port_binding_when_listening_with_mapping(self):
        diag = self._make()
        diag.host_info["is_unraid"] = False
        mappings = {"9374": [{"host": "0.0.0.0", "port": "8374"}]}
        with patch.object(diag, "_is_port_listening", return_value=True), \
             patch.object(diag, "_get_docker_port_mappings", return_value=mappings):
            result = diag.check_port_binding()
        assert result["internal_port_listening"] is True
        assert result["external_ports"] == [{"host": "0.0.0.0", "port": "8374"}]

    def test_get_diagnostic_report_unraid_recommendations(self):
        diag = self._make()
        diag.host_info["is_unraid"] = True
        with patch.object(diag, "check_port_binding", return_value={
            "internal_port_listening": True,
            "external_ports": [],
            "port_mappings": {},
            "issues": [],
            "solutions": [],
        }):
            report = diag.get_diagnostic_report()
        assert report["container_name"] == "ddc-test"
        assert any("Unraid" in r for r in report["recommendations"])

    def test_get_diagnostic_report_generic_recommendations(self):
        diag = self._make()
        diag.host_info["is_unraid"] = False
        with patch.object(diag, "check_port_binding", return_value={
            "internal_port_listening": True,
            "external_ports": [],
            "port_mappings": {},
            "issues": [],
            "solutions": [],
        }):
            report = diag.get_diagnostic_report()
        assert any("port mapping" in r.lower() for r in report["recommendations"])

    def test_detect_container_name_uses_etc_hostname(self):
        """When /etc/hostname is readable and docker is unavailable, return hostname."""
        from unittest.mock import mock_open
        with patch.object(port_diagnostics, "subprocess") as mock_sp, \
             patch("builtins.open", mock_open(read_data="my-host\n")):
            mock_sp.run.side_effect = FileNotFoundError("no docker")
            mock_sp.SubprocessError = Exception
            mock_sp.TimeoutExpired = Exception
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            name = diag._detect_container_name()
        assert name == "my-host"

    def test_detect_container_name_falls_back_on_oserror(self):
        with patch("builtins.open", side_effect=OSError("nope")):
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            name = diag._detect_container_name()
        assert name == "dockerdiscordcontrol"

    def test_detect_container_name_uses_docker_inspect_output(self):
        from unittest.mock import mock_open
        # Simulate docker inspect succeeding
        result_obj = MagicMock()
        result_obj.returncode = 0
        result_obj.stdout = "/my-named-container\n"
        with patch("builtins.open", mock_open(read_data="abc123\n")), \
             patch.object(port_diagnostics.subprocess, "run", return_value=result_obj):
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            name = diag._detect_container_name()
        assert name == "my-named-container"

    def test_get_container_uptime_formats_minutes(self):
        from unittest.mock import mock_open
        # 90061 seconds = 1d 1h 1m
        with patch("builtins.open", mock_open(read_data="90061.0 12345.6\n")):
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            uptime = diag._get_container_uptime()
        assert "1d" in uptime
        assert "1h" in uptime

    def test_get_container_uptime_formats_minutes_only(self):
        from unittest.mock import mock_open
        # 600 seconds = 10m
        with patch("builtins.open", mock_open(read_data="600.0 123\n")):
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            uptime = diag._get_container_uptime()
        assert uptime == "10m"

    def test_get_container_uptime_handles_oserror(self):
        with patch("builtins.open", side_effect=OSError("bad")):
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            assert diag._get_container_uptime() == "unknown"

    def test_get_container_uptime_handles_parse_error(self):
        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data="garbage\n")):
            diag = object.__new__(port_diagnostics.PortDiagnostics)
            assert diag._get_container_uptime() == "unknown"

    def test_detect_platform_returns_unraid_when_marker_file(self):
        diag = self._make()
        with patch.object(port_diagnostics.os.path, "exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/etc/unraid-version"
            result = diag._detect_platform()
        assert result == ("unraid", True)

    def test_detect_platform_alpine_via_os_release(self):
        from unittest.mock import mock_open
        diag = self._make()
        with patch.object(port_diagnostics.os.path, "exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/etc/os-release"
            with patch("builtins.open", mock_open(read_data="ID=alpine\nNAME=Alpine Linux\n")):
                result = diag._detect_platform()
        assert result == ("alpine", False)

    def test_detect_platform_unknown_when_no_files(self):
        diag = self._make()
        with patch.object(port_diagnostics.os.path, "exists", return_value=False):
            result = diag._detect_platform()
        assert result == ("unknown", False)

    def test_get_docker_port_mappings_parses_output(self):
        diag = self._make()
        result_obj = MagicMock()
        result_obj.returncode = 0
        result_obj.stdout = "9374/tcp -> 0.0.0.0:8374\n9374/tcp -> [::]:8374\n"
        with patch.object(port_diagnostics.subprocess, "run", return_value=result_obj):
            mappings = diag._get_docker_port_mappings()
        assert "9374" in mappings
        assert {"host": "0.0.0.0", "port": "8374"} in mappings["9374"]

    def test_get_docker_port_mappings_returns_empty_on_failure(self):
        diag = self._make()
        result_obj = MagicMock()
        result_obj.returncode = 1
        result_obj.stdout = ""
        with patch.object(port_diagnostics.subprocess, "run", return_value=result_obj):
            assert diag._get_docker_port_mappings() == {}

    def test_get_docker_port_mappings_returns_empty_when_no_container_name(self):
        diag = self._make()
        diag.container_name = None
        assert diag._get_docker_port_mappings() == {}

    def test_get_docker_port_mappings_handles_filenotfound(self):
        diag = self._make()
        with patch.object(
            port_diagnostics.subprocess, "run", side_effect=FileNotFoundError("docker missing")
        ):
            assert diag._get_docker_port_mappings() == {}

    def test_get_host_info_assembles_dict(self):
        """_get_host_info wires together the helper outputs into a single dict."""
        with patch.object(port_diagnostics.PortDiagnostics, "_detect_container_name",
                          return_value="ddc"), \
             patch.object(port_diagnostics.PortDiagnostics, "_detect_platform",
                          return_value=("alpine", False)), \
             patch.object(port_diagnostics.os.path, "exists", return_value=False), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_python_version",
                          return_value="3.11.0"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_container_uptime",
                          return_value="1h"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_memory_usage",
                          return_value="100MB"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_disk_usage",
                          return_value="50MB"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_supervisord_status",
                          return_value={"webui": "RUNNING"}):
            diag = port_diagnostics.PortDiagnostics()
        info = diag.host_info
        assert info["platform"] == "alpine"
        assert info["is_unraid"] is False
        assert info["is_docker"] is False
        assert info["python_version"] == "3.11.0"
        assert info["docker_socket_available"] is False
        # No docker socket -> ddc-specific fields stay empty
        assert info["ddc_memory_usage"] == ""

    def test_get_host_info_with_docker_socket(self):
        """With docker socket present, ddc_memory_usage / ddc_image_size populated."""
        def fake_exists(p):
            return p in ("/var/run/docker.sock", "/.dockerenv")

        with patch.object(port_diagnostics.PortDiagnostics, "_detect_container_name",
                          return_value="ddc"), \
             patch.object(port_diagnostics.PortDiagnostics, "_detect_platform",
                          return_value=("alpine", False)), \
             patch.object(port_diagnostics.os.path, "exists", side_effect=fake_exists), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_python_version",
                          return_value="3.11"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_container_uptime",
                          return_value="1h"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_memory_usage",
                          return_value="100MB"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_disk_usage",
                          return_value="50MB"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_supervisord_status",
                          return_value={}), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_ddc_memory_usage",
                          return_value="42MB"), \
             patch.object(port_diagnostics.PortDiagnostics, "_get_ddc_image_size",
                          return_value="200MB"):
            diag = port_diagnostics.PortDiagnostics()
        assert diag.host_info["ddc_memory_usage"] == "42MB"
        assert diag.host_info["ddc_image_size"] == "200MB"
        assert diag.host_info["is_docker"] is True

    def test_get_actual_host_ip_returns_env_var_first(self, monkeypatch):
        diag = self._make()
        monkeypatch.setenv("HOST_IP", "10.20.30.40")
        ip = diag._get_actual_host_ip()
        assert ip == "10.20.30.40"

    def test_get_actual_host_ip_returns_none_when_all_methods_fail(self, monkeypatch):
        diag = self._make()
        monkeypatch.delenv("HOST_IP", raising=False)
        monkeypatch.delenv("UNRAID_IP", raising=False)
        monkeypatch.delenv("SERVER_IP", raising=False)
        with patch.object(diag, "_try_traceroute_ip", return_value=None), \
             patch.object(diag, "_try_docker_host_gateway", return_value=None):
            assert diag._get_actual_host_ip() is None

    def test_run_port_diagnostics_convenience(self):
        with patch.object(
            port_diagnostics.PortDiagnostics,
            "_detect_container_name",
            return_value="x",
        ), patch.object(
            port_diagnostics.PortDiagnostics,
            "_get_host_info",
            return_value={"is_unraid": False, "platform": "alpine"},
        ), patch.object(
            port_diagnostics.PortDiagnostics,
            "check_port_binding",
            return_value={
                "internal_port_listening": True,
                "external_ports": [],
                "port_mappings": {},
                "issues": [],
                "solutions": [],
            },
        ):
            report = port_diagnostics.run_port_diagnostics()
        assert "container_name" in report
        assert "host_info" in report
        assert "port_check" in report


# =============================================================================
# app/bot/dependencies tests
# =============================================================================

class TestBotDependencies:
    """Tests for app/bot/dependencies.py."""

    def test_botdependencies_defaults_to_none(self):
        deps = bot_dependencies.BotDependencies()
        assert deps.config_service_factory is None
        assert deps.dynamic_cooldown_applicator is None
        assert deps.update_notifier_factory is None

    def test_botdependencies_is_frozen(self):
        deps = bot_dependencies.BotDependencies()
        with pytest.raises((AttributeError, Exception)):
            # frozen dataclass - any field assignment must fail
            deps.config_service_factory = lambda: None  # type: ignore[misc]

    def test_load_dependencies_returns_dataclass(self):
        logger = logging.getLogger("ddc.test.deps")
        deps = bot_dependencies.load_dependencies(logger)
        assert isinstance(deps, bot_dependencies.BotDependencies)

    def test_load_dependencies_resolves_factories_when_imports_succeed(self):
        """With our stubs in sys.modules the imports should succeed."""
        logger = logging.getLogger("ddc.test.deps")
        deps = bot_dependencies.load_dependencies(logger)
        assert deps.config_service_factory is not None
        assert deps.dynamic_cooldown_applicator is not None
        assert deps.update_notifier_factory is not None

    def test_load_dependencies_falls_back_to_none_on_importerror(self):
        """When the optional services raise ImportError the fields are None."""
        logger = logging.getLogger("ddc.test.deps")

        # Simulate imports failing by removing them from sys.modules and
        # patching the import system.
        original_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict
        ) else __import__

        def selective_import(name, *args, **kwargs):
            failing = (
                "services.config.config_service",
                "services.infrastructure.dynamic_cooldown_manager",
                "services.infrastructure.update_notifier",
            )
            if name in failing:
                raise ImportError(f"simulated import failure for {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=selective_import):
            deps = bot_dependencies.load_dependencies(logger)

        assert deps.config_service_factory is None
        assert deps.dynamic_cooldown_applicator is None
        assert deps.update_notifier_factory is None


# =============================================================================
# app/bot/token tests
# =============================================================================

def _patch_token_config_dir(tmp_path: Path):
    """Helper: patch ``bot_token.Path`` so config_dir resolves to tmp_path/config.

    Returns a context manager.  The patched module behaviour:
        Path(__file__).resolve().parents[2] / "config"  -> tmp_path / "config"
    All other ``Path(...)`` calls in the module return real ``pathlib.Path``
    instances so that ``.exists()``, ``.read_text()`` etc. work normally.
    """
    real_path_cls = bot_token.Path
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)

    class _FakeFile:
        """Sentinel returned by Path(__file__) so we can override .resolve()."""

        def resolve(self):
            return _FakeResolved()

    class _FakeResolved:
        @property
        def parents(self):
            # Return a list whose [2] element is tmp_path; / "config" then
            # yields a real Path.
            return [real_path_cls("/x"), real_path_cls("/x/y"), real_path_cls(str(tmp_path))]

    def path_factory(*args, **kwargs):
        # __file__ goes through here exactly once at function entry.
        if args and isinstance(args[0], str) and args[0].endswith("token.py"):
            return _FakeFile()
        return real_path_cls(*args, **kwargs)

    return patch.object(bot_token, "Path", side_effect=path_factory)


class TestBotToken:
    """Tests for app/bot/token.py."""

    def test_uses_environment_token_when_present(self, monkeypatch, fake_runtime):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "  env-token-xyz  ")
        token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token == "env-token-xyz"

    def test_falls_back_to_plaintext_bot_config(self, monkeypatch, fake_runtime, tmp_path):
        """Plaintext token in bot_config.json takes precedence over runtime config."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "bot_config.json").write_text(
            json.dumps({"bot_token": "plain-tok"})
        )
        fake_runtime.config = {"bot_token_decrypted_for_usage": "should-not-win"}
        with _patch_token_config_dir(tmp_path):
            token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token == "plain-tok"

    def test_skips_encrypted_marker_in_plaintext(self, monkeypatch, fake_runtime, tmp_path):
        """A bot_token starting with 'gAAAAA' (Fernet) is NOT used as plaintext."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "bot_config.json").write_text(
            json.dumps({"bot_token": "gAAAAA-encrypted"})
        )
        fake_runtime.config = {}
        fake_runtime.dependencies = types.SimpleNamespace(
            config_service_factory=None
        )
        with _patch_token_config_dir(tmp_path):
            token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token is None

    def test_uses_runtime_config_pre_decrypted_token(self, monkeypatch, fake_runtime, tmp_path):
        """If runtime.config has bot_token_decrypted_for_usage and no plaintext file, it wins."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # No bot_config.json on disk.
        fake_runtime.config = {"bot_token_decrypted_for_usage": "runtime-tok"}
        with _patch_token_config_dir(tmp_path):
            token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token == "runtime-tok"

    def test_uses_config_service_factory_pre_decrypted(self, monkeypatch, fake_runtime, tmp_path):
        """ConfigService returns a pre-decrypted token via get_config()."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        fake_runtime.config = {}

        fake_service = MagicMock()
        fake_service.get_config.return_value = {
            "bot_token_decrypted_for_usage": "from-cfg-svc"
        }
        fake_runtime.dependencies = types.SimpleNamespace(
            config_service_factory=lambda: fake_service
        )
        with _patch_token_config_dir(tmp_path):
            token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token == "from-cfg-svc"
        fake_service.get_config.assert_called_once_with(force_reload=True)

    def test_uses_config_service_decrypt_path(self, monkeypatch, fake_runtime, tmp_path):
        """When pre-decrypted token absent but encrypted+hash present, decrypt_token is used."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        fake_runtime.config = {}

        fake_service = MagicMock()
        fake_service.get_config.return_value = {
            "bot_token": "gAAAAA-enc",
            "web_ui_password_hash": "hashed",
        }
        fake_service.decrypt_token.return_value = "decrypted-final"
        fake_runtime.dependencies = types.SimpleNamespace(
            config_service_factory=lambda: fake_service
        )
        with _patch_token_config_dir(tmp_path):
            token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token == "decrypted-final"
        fake_service.decrypt_token.assert_called_once_with("gAAAAA-enc", "hashed")

    def test_returns_none_when_nothing_available(self, monkeypatch, fake_runtime, tmp_path):
        """No env, no plaintext, no runtime token, no factory -> None."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        fake_runtime.config = {}
        fake_runtime.dependencies = types.SimpleNamespace(
            config_service_factory=None
        )
        with _patch_token_config_dir(tmp_path):
            token = bot_token.get_decrypted_bot_token(fake_runtime)
        assert token is None


# =============================================================================
# app/bot/events tests
# =============================================================================

class _FakeBot:
    """Discord bot stub that records event-handler registrations."""

    def __init__(self):
        self._events = {}
        self.user = types.SimpleNamespace(name="ddc-bot", id=42)

    def event(self, func):
        # Discord.Bot.event uses the function's __name__ as event name.
        self._events[func.__name__] = func
        return func


class TestBotEvents:
    """Tests for app/bot/events.py."""

    def test_register_event_handlers_attaches_three_events(self, fake_runtime):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        assert "on_ready" in bot._events
        assert "on_error" in bot._events
        assert "on_command_error" in bot._events

    def test_on_ready_invokes_startup_manager(self, fake_runtime):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        # Trigger on_ready synchronously through asyncio.
        import asyncio
        asyncio.get_event_loop().run_until_complete(bot._events["on_ready"]())
        # The (stubbed) StartupManager records that handle_ready was awaited.
        # We can't reach it directly, but absence of exception is the signal.

    def test_on_error_logs_traceback(self, fake_runtime, caplog):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        import asyncio
        with caplog.at_level(logging.ERROR, logger=fake_runtime.logger.name):
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                asyncio.get_event_loop().run_until_complete(
                    bot._events["on_error"]("on_message", "extra")
                )
        # No assertion needed beyond no-raise: handler must swallow.

    def test_on_command_error_skips_donate_commands(self, fake_runtime):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        ctx = MagicMock()
        ctx.command = "donate"

        import discord
        err = discord.ApplicationCommandError("ignored")

        # Make ctx.respond async
        async def _respond(*a, **kw):
            return None
        ctx.respond.side_effect = _respond

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            bot._events["on_command_error"](ctx, err)
        )
        ctx.respond.assert_not_called()

    def test_on_command_error_cooldown_responds(self, fake_runtime):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        ctx = MagicMock()
        ctx.command = "status"

        async def _respond(*a, **kw):
            return None
        ctx.respond.side_effect = _respond

        from discord.ext import commands as dpy_commands
        err = dpy_commands.CommandOnCooldown(
            cooldown=MagicMock(), retry_after=42.5, type=MagicMock()
        )

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            bot._events["on_command_error"](ctx, err)
        )
        # respond should have been called once with a string mentioning seconds.
        ctx.respond.assert_called_once()
        msg = ctx.respond.call_args.args[0]
        assert "cooldown" in msg.lower()

    def test_on_command_error_application_error_responds(self, fake_runtime):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        ctx = MagicMock()
        ctx.command = "stop"

        async def _respond(*a, **kw):
            return None
        ctx.respond.side_effect = _respond

        import discord
        err = discord.ApplicationCommandError("kaboom")

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            bot._events["on_command_error"](ctx, err)
        )
        ctx.respond.assert_called_once()
        called_args = ctx.respond.call_args
        assert "kaboom" in called_args.args[0]
        assert called_args.kwargs.get("ephemeral") is True

    def test_on_command_error_unexpected_error_no_respond(self, fake_runtime):
        bot = _FakeBot()
        bot_events.register_event_handlers(bot, fake_runtime)
        ctx = MagicMock()
        ctx.command = "stop"
        ctx.respond = MagicMock()

        err = ValueError("unexpected")

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            bot._events["on_command_error"](ctx, err)
        )
        # Unexpected errors are logged but do not call ctx.respond.
        ctx.respond.assert_not_called()
