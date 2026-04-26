# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Coverage gap-filler tests                       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Targeted edge-case tests filling remaining coverage gaps for:

* ``app/utils/web_helpers.py``      (mech-decay lifecycle, update_docker_cache
                                     timeout/raise branches, start_background
                                     connectivity-OK path, set_initial_password
                                     error branches)
* ``app/utils/port_diagnostics.py`` (_detect_platform os-release variants,
                                     _try_traceroute_ip / _try_docker_host_gateway
                                     success paths, _test_if_this_is_our_host
                                     positive path, check_port_binding mapping
                                     missing branch)
* ``utils/logging_utils.py``        (is_debug_mode_enabled config-error path,
                                     temp-debug expiry, refresh_debug_status
                                     fallback)
* ``utils/app_commands_helper.py``  (Strategy 3 — discord.ext.commands fallback)
* ``utils/common_helpers.py``       (format_uptime/memory/cpu invalid input,
                                     deep_merge_dicts, retry_on_exception sync,
                                     is_valid_ip, parse_boolean numeric)

NO ``sys.modules`` manipulation. Heavy collaborators are stubbed via
``monkeypatch.setattr``.
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

import logging
import socket
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest


# ===========================================================================
# app/utils/web_helpers.py — uncovered branches
# ===========================================================================


class TestUpdateDockerCacheBranches:
    """Cover update_docker_cache timeout & re-raise branches."""

    def test_update_cache_handles_unix_http_pool_timeout(self, monkeypatch):
        """Lines 272-274: 'UnixHTTPConnectionPool' substring triggers timeout path."""
        from app.utils import web_helpers as wh

        class _FakeContainers:
            def list(self, all=True):
                raise RuntimeError(
                    "UnixHTTPConnectionPool(host='localhost', port=2375): boom"
                )

        class _FakeClient:
            def __init__(self, *a, **k):
                self.containers = _FakeContainers()

            def close(self):
                pass

        monkeypatch.setattr(wh.docker, "from_env", lambda **k: _FakeClient())

        logger = MagicMock()
        # Should NOT raise - the timeout path swallows the error
        wh.update_docker_cache(logger)
        # cache 'error' stays None for timeout path (no DockerException raised)
        assert wh.docker_cache["error"] is None

    def test_update_cache_reraises_unexpected_runtime_error(self, monkeypatch):
        """Line 276: non-timeout exceptions get re-raised and caught by outer."""
        from app.utils import web_helpers as wh

        class _FakeContainers:
            def list(self, all=True):
                # Non-timeout RuntimeError gets re-raised (line 276) then
                # the outer exception block (line 362-374) catches it
                # because it matches (RuntimeError is not in that tuple,
                # so this should actually propagate up).
                raise ValueError("totally unrelated parser error")

        class _FakeClient:
            def __init__(self, *a, **k):
                self.containers = _FakeContainers()

            def close(self):
                pass

        monkeypatch.setattr(wh.docker, "from_env", lambda **k: _FakeClient())
        logger = MagicMock()
        # ValueError is in the (ValueError, TypeError, KeyError, AttributeError)
        # except block, so it's caught and stored in cache['error']
        wh.update_docker_cache(logger)
        assert wh.docker_cache["error"] is not None
        assert "DOCKER QUERY ERROR" in wh.docker_cache["error"]


class TestStartBackgroundRefreshSuccess:
    """Cover lines 522-530: connectivity check OK path."""

    def test_start_background_refresh_connectivity_ok(self, monkeypatch):
        from app.utils import web_helpers as wh

        # Snapshot & null out so we exercise the start branch
        prev_thread = wh.background_refresh_thread
        wh.background_refresh_thread = None

        # Ping returns OK
        class _FakeClient:
            def __init__(self, *a, **k):
                pass

            def ping(self):
                return True

            def close(self):
                pass

        monkeypatch.setattr(
            wh.docker, "DockerClient", lambda *a, **k: _FakeClient()
        )

        # Stub the actual thread creation/start
        started = {"flag": False}

        class _FakeThread:
            def __init__(self):
                self.daemon = True

            def start(self):
                started["flag"] = True

            def is_alive(self):
                return True

        monkeypatch.setattr(
            wh, "create_thread", lambda *a, **k: _FakeThread()
        )

        try:
            logger = MagicMock()
            wh.start_background_refresh(logger)
            # Either we hit start() or the gevent start_later() branch
            assert started["flag"] or wh.background_refresh_thread is not None
        finally:
            # Cleanup
            wh.stop_background_thread.set()
            wh.background_refresh_thread = prev_thread
            wh.stop_background_thread.clear()


class TestMechDecayLifecycle:
    """Cover start/stop_mech_decay_background helpers."""

    def test_start_mech_decay_creates_thread(self, monkeypatch):
        """Cover lines 681-705 of start_mech_decay_background."""
        from app.utils import web_helpers as wh

        prev = wh.mech_decay_thread
        wh.mech_decay_thread = None

        started = {"flag": False}

        class _FakeThread:
            def __init__(self):
                self.daemon = True

            def start(self):
                started["flag"] = True

            def is_alive(self):
                return True

            @property
            def dead(self):
                return False

            def start_later(self, delay):
                started["flag"] = True

        monkeypatch.setattr(
            wh, "create_thread", lambda *a, **k: _FakeThread()
        )

        try:
            logger = MagicMock()
            wh.start_mech_decay_background(logger)
            assert started["flag"]
        finally:
            wh.stop_mech_decay_thread.set()
            wh.mech_decay_thread = prev
            wh.stop_mech_decay_thread.clear()

    def test_start_mech_decay_skips_when_already_alive(self, monkeypatch):
        """Lines 683-686: existing live thread short-circuits."""
        from app.utils import web_helpers as wh

        prev = wh.mech_decay_thread

        class _AliveThread:
            @property
            def dead(self):
                return False

            def is_alive(self):
                return True

        wh.mech_decay_thread = _AliveThread()
        try:
            logger = MagicMock()
            wh.start_mech_decay_background(logger)
            # Logger was called with debug message
            logger.debug.assert_called()
        finally:
            wh.mech_decay_thread = prev

    def test_stop_mech_decay_joins_alive_thread(self, monkeypatch):
        """Lines 737-744: thread join with is_alive=True."""
        from app.utils import web_helpers as wh

        prev = wh.mech_decay_thread

        class _AliveThread:
            def __init__(self):
                self._alive = True

            def is_alive(self):
                return self._alive

            def join(self, timeout=None):
                self._alive = False

            @property
            def dead(self):
                return not self._alive

            def kill(self, block=False):
                self._alive = False

        wh.mech_decay_thread = _AliveThread()
        # Force HAS_GEVENT=False path
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        try:
            logger = MagicMock()
            wh.stop_mech_decay_background(logger)
            assert wh.mech_decay_thread is None
        finally:
            wh.mech_decay_thread = prev

    def test_stop_mech_decay_join_timeout_warning(self, monkeypatch):
        """Cover the 'thread did not terminate within timeout' warning."""
        from app.utils import web_helpers as wh

        prev = wh.mech_decay_thread

        class _StuckThread:
            def is_alive(self):
                return True  # always alive

            def join(self, timeout=None):
                pass  # ignore signal

            @property
            def dead(self):
                return False

            def kill(self, block=False):
                pass

        wh.mech_decay_thread = _StuckThread()
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        try:
            logger = MagicMock()
            wh.stop_mech_decay_background(logger)
            # Warning logged about timeout
            calls = [str(c) for c in logger.warning.call_args_list]
            assert any("did not terminate" in c for c in calls)
        finally:
            wh.mech_decay_thread = prev

    def test_stop_mech_decay_handles_join_exception(self, monkeypatch):
        """Cover RuntimeError handling during thread.join()."""
        from app.utils import web_helpers as wh

        prev = wh.mech_decay_thread

        class _BoomThread:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                raise RuntimeError("cannot join self")

            @property
            def dead(self):
                return False

            def kill(self, block=False):
                pass

        wh.mech_decay_thread = _BoomThread()
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        try:
            logger = MagicMock()
            wh.stop_mech_decay_background(logger)
            # error was logged
            logger.error.assert_called()
        finally:
            wh.mech_decay_thread = prev


class TestStopBackgroundRefreshAlive:
    """Cover stop_background_refresh join paths (lines 593-612)."""

    def test_stop_background_refresh_warning_when_thread_stuck(self, monkeypatch):
        from app.utils import web_helpers as wh

        prev = wh.background_refresh_thread

        class _Stuck:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                pass

            @property
            def dead(self):
                return False

            def kill(self, block=False):
                pass

        wh.background_refresh_thread = _Stuck()
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        try:
            logger = MagicMock()
            wh.stop_background_refresh(logger)
            calls = [str(c) for c in logger.warning.call_args_list]
            assert any("did not terminate" in c for c in calls)
        finally:
            wh.background_refresh_thread = prev


class TestSetInitialPasswordEdgeCases:
    """Cover lines 802-810 (ImportError, FileNotFoundError, generic error)."""

    def test_import_error_during_config_load(self, monkeypatch):
        from app.utils import web_helpers as wh

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "newpwd")

        # Force the dynamic import to fail
        real_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict
        ) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "services.config.config_service":
                raise ImportError("config service unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        # Should not raise
        wh.set_initial_password_from_env()

    def test_file_not_found_during_load_config(self, monkeypatch):
        from app.utils import web_helpers as wh

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "newpwd")

        def _boom_load():
            raise FileNotFoundError("config.json not found")

        def _save_noop(cfg):
            pass

        # Patch attribute on the actual module
        import services.config.config_service as cs_mod

        monkeypatch.setattr(cs_mod, "load_config", _boom_load)
        monkeypatch.setattr(cs_mod, "save_config", _save_noop)

        # Should not raise
        wh.set_initial_password_from_env()

    def test_generic_error_during_set_password(self, monkeypatch):
        from app.utils import web_helpers as wh

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "newpwd")

        def _boom_load():
            # ValueError -> falls into the (ValueError, TypeError, ...) except
            raise ValueError("bad config json")

        def _save_noop(cfg):
            pass

        import services.config.config_service as cs_mod

        monkeypatch.setattr(cs_mod, "load_config", _boom_load)
        monkeypatch.setattr(cs_mod, "save_config", _save_noop)

        # Should not raise — error path handled gracefully
        wh.set_initial_password_from_env()


# ===========================================================================
# app/utils/port_diagnostics.py — uncovered branches
# ===========================================================================


class TestPortDiagnosticsPlatformBranches:
    """Cover _detect_platform variants (lines 188-203)."""

    def _make_diag(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_get_host_info", lambda self: {"is_unraid": False}
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        return PortDiagnostics()

    def test_detect_platform_unraid_via_unraid_version_file(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        diag = self._make_diag(monkeypatch)

        # /etc/unraid-version exists triggers immediate unraid return
        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/etc/unraid-version",
        )
        platform, is_unraid = diag._detect_platform()
        assert platform == "unraid"
        assert is_unraid is True

    def test_detect_platform_unraid_via_os_release_content(self, monkeypatch):
        diag = self._make_diag(monkeypatch)

        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/etc/os-release",
        )
        with patch("builtins.open", mock_open(read_data="ID=unraid\n")):
            platform, is_unraid = diag._detect_platform()
        assert platform == "unraid"
        assert is_unraid is True

    def test_detect_platform_ubuntu(self, monkeypatch):
        diag = self._make_diag(monkeypatch)

        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/etc/os-release",
        )
        with patch(
            "builtins.open",
            mock_open(read_data='NAME="Ubuntu"\nID=ubuntu\n'),
        ):
            platform, is_unraid = diag._detect_platform()
        assert platform == "ubuntu"
        assert is_unraid is False

    def test_detect_platform_debian(self, monkeypatch):
        diag = self._make_diag(monkeypatch)

        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/etc/os-release",
        )
        with patch("builtins.open", mock_open(read_data="ID=debian\n")):
            platform, is_unraid = diag._detect_platform()
        assert platform == "debian"

    def test_detect_platform_alpine(self, monkeypatch):
        diag = self._make_diag(monkeypatch)

        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/etc/os-release",
        )
        with patch("builtins.open", mock_open(read_data="ID=alpine\n")):
            platform, is_unraid = diag._detect_platform()
        assert platform == "alpine"

    def test_detect_platform_io_error_returns_unknown(self, monkeypatch):
        diag = self._make_diag(monkeypatch)

        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/etc/os-release",
        )

        def _raise(*a, **k):
            raise IOError("permission denied")

        monkeypatch.setattr("builtins.open", _raise)
        platform, is_unraid = diag._detect_platform()
        assert platform == "unknown"
        assert is_unraid is False


class TestPortDiagnosticsHostIPSuccessPaths:
    """Exercise the positive branches in IP detection."""

    @pytest.fixture
    def diag(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_get_host_info", lambda self: {"is_unraid": False}
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        return PortDiagnostics()

    def test_get_actual_host_ip_uses_docker_gateway_fallback(self, diag, monkeypatch):
        """Cover lines 537-539 (Method 3 success)."""
        for var in ("HOST_IP", "UNRAID_IP", "SERVER_IP"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            type(diag), "_try_traceroute_ip", lambda self: None
        )
        monkeypatch.setattr(
            type(diag), "_try_docker_host_gateway", lambda self: "192.168.5.5"
        )
        assert diag._get_actual_host_ip() == "192.168.5.5"

    def test_get_actual_host_ip_outer_exception_returns_none(
        self, diag, monkeypatch
    ):
        """Cover lines 543-544 (outer except returning None)."""
        # Force the very first method to raise unexpectedly
        def _raise(self):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(
            type(diag), "_try_environment_variable_ip", _raise
        )
        result = diag._get_actual_host_ip()
        assert result is None

    def test_try_traceroute_ip_skips_docker_gateway_lines(self, diag, monkeypatch):
        """Hop 2 starting with 172.17. is skipped (line 460)."""
        result = SimpleNamespace(
            returncode=0,
            stdout="1  172.17.0.1\n2  172.17.0.5\n3  8.8.8.8\n",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        # No valid hop2 -> returns None
        assert diag._try_traceroute_ip() is None

    def test_try_traceroute_ip_falls_through_to_tracepath(self, diag, monkeypatch):
        """traceroute FileNotFoundError -> tracepath success (lines 466-477)."""
        calls = {"n": 0}

        def _run(args, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FileNotFoundError("traceroute missing")
            # tracepath output
            return SimpleNamespace(
                returncode=0,
                stdout="1:  gateway\n2:  192.168.7.7  10ms\n",
            )

        monkeypatch.setattr(subprocess, "run", _run)
        result = diag._try_traceroute_ip()
        assert result == "192.168.7.7"

    def test_try_traceroute_ip_tracepath_also_missing(self, diag, monkeypatch):
        """Both traceroute and tracepath unavailable (line 478-479)."""

        def _run(args, *a, **k):
            raise FileNotFoundError("none available")

        monkeypatch.setattr(subprocess, "run", _run)
        # Should return None gracefully
        assert diag._try_traceroute_ip() is None

    def test_try_traceroute_ip_outer_exception(self, diag, monkeypatch):
        """Cover lines 480-481 (outermost except)."""

        def _bad(*a, **k):
            raise RuntimeError("kaboom")

        # Patch the import that the function does inside its try-block
        monkeypatch.setattr(subprocess, "run", _bad)
        # FileNotFoundError isn't raised; instead a RuntimeError -> the
        # outer except catches it. Should return None.
        result = diag._try_traceroute_ip()
        assert result is None

    def test_try_docker_host_gateway_etc_hosts_success(self, diag, monkeypatch):
        """Cover lines 491-500 (positive /etc/hosts read)."""
        hosts_data = "192.168.10.20  host.docker.internal host-gateway\n"
        with patch("builtins.open", mock_open(read_data=hosts_data)):
            ip = diag._try_docker_host_gateway()
        assert ip == "192.168.10.20"

    def test_try_docker_host_gateway_etc_hosts_skips_loopback(
        self, diag, monkeypatch
    ):
        """Lines 496-498: loopback IP must be skipped, falls through to ip route."""
        hosts_data = "127.0.0.1  host.docker.internal\n"
        ip_route_result = SimpleNamespace(
            returncode=0,
            stdout="default via 192.168.99.1 dev eth0\n",
        )

        # /etc/hosts -> only 127.0.0.1 (skipped)
        # subprocess.run -> ip route
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: ip_route_result
        )
        with patch("builtins.open", mock_open(read_data=hosts_data)):
            ip = diag._try_docker_host_gateway()
        assert ip == "192.168.99.1"

    def test_try_docker_host_gateway_skips_default_docker_gw(
        self, diag, monkeypatch
    ):
        """Lines 514-516: 172.17.0.1 default gw is rejected."""
        hosts_data = "# nothing here\n"
        ip_route_result = SimpleNamespace(
            returncode=0,
            stdout="default via 172.17.0.1 dev docker0\n",
        )

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: ip_route_result
        )
        with patch("builtins.open", mock_open(read_data=hosts_data)):
            ip = diag._try_docker_host_gateway()
        assert ip is None

    def test_try_docker_host_gateway_etc_hosts_io_error(self, diag, monkeypatch):
        """Lines 501-502: IOError reading /etc/hosts logged but continues."""

        def _open_raise(*a, **k):
            raise IOError("permission")

        monkeypatch.setattr("builtins.open", _open_raise)
        # ip route still works
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(
                returncode=0, stdout="default via 192.168.5.55 dev eth0\n"
            ),
        )
        ip = diag._try_docker_host_gateway()
        assert ip == "192.168.5.55"

    def test_try_docker_host_gateway_outer_exception(self, diag, monkeypatch):
        """Lines 517-518: outer exception returns None."""

        def _open_raise(*a, **k):
            raise RuntimeError("totally broken")

        monkeypatch.setattr("builtins.open", _open_raise)
        result = diag._try_docker_host_gateway()
        assert result is None


class TestPortDiagnosticsCheckBindingExternalUnaccessible:
    """Cover lines 271-274: external port not accessible branch."""

    @pytest.fixture
    def diag(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_get_host_info", lambda self: {"is_unraid": False}
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        return PortDiagnostics()

    def test_check_port_binding_no_mapping_unraid_solutions(
        self, diag, monkeypatch
    ):
        """Cover lines 264-266: no mapping + unraid -> unraid solutions."""
        # Override host_info post-init to indicate unraid
        diag.host_info = {"is_unraid": True, "platform": "unraid"}
        monkeypatch.setattr(
            type(diag), "_is_port_listening", lambda self, p: True
        )
        monkeypatch.setattr(
            type(diag), "_get_docker_port_mappings", lambda self: {}
        )
        result = diag.check_port_binding()
        assert any("UNRAID" in s for s in result["solutions"])

    def test_check_port_binding_external_inaccessible(self, diag, monkeypatch):
        """Lines 271-274: mapping exists but external port not accessible."""
        monkeypatch.setattr(
            type(diag), "_is_port_listening", lambda self, p: True
        )
        monkeypatch.setattr(
            type(diag),
            "_get_docker_port_mappings",
            lambda self: {"9374": [{"host": "0.0.0.0", "port": "8374"}]},
        )
        # Force external_port_accessible to return False
        monkeypatch.setattr(
            type(diag), "_is_external_port_accessible", lambda self, p: False
        )
        result = diag.check_port_binding()
        assert any("not accessible" in i for i in result["issues"])
        assert any("firewall" in s for s in result["solutions"])


class TestTestIfThisIsOurHost:
    """Cover positive branches in _test_if_this_is_our_host."""

    @pytest.fixture
    def diag(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_get_host_info", lambda self: {"is_unraid": False}
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        return PortDiagnostics()

    def test_test_if_this_is_our_host_socket_succeeds(self, diag, monkeypatch):
        """Lines 558-560: connect_ex returns 0 -> True."""
        sock_mock = MagicMock()
        sock_mock.__enter__ = lambda self: self
        sock_mock.__exit__ = lambda self, *a: False
        sock_mock.connect_ex.return_value = 0  # Success!
        monkeypatch.setattr(socket, "socket", lambda *a, **k: sock_mock)
        assert diag._test_if_this_is_our_host("1.2.3.4") is True

    def test_test_if_this_is_our_host_nc_fallback_success(self, diag, monkeypatch):
        """Lines 569-572: nc subprocess returns 0 -> True."""
        sock_mock = MagicMock()
        sock_mock.__enter__ = lambda self: self
        sock_mock.__exit__ = lambda self, *a: False
        sock_mock.connect_ex.return_value = 1  # all sockets fail
        monkeypatch.setattr(socket, "socket", lambda *a, **k: sock_mock)
        # nc returns 0
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0),
        )
        assert diag._test_if_this_is_our_host("1.2.3.4") is True

    def test_test_if_this_is_our_host_nc_oserror(self, diag, monkeypatch):
        """Lines 576-578: OSError during nc subprocess."""
        sock_mock = MagicMock()
        sock_mock.__enter__ = lambda self: self
        sock_mock.__exit__ = lambda self, *a: False
        sock_mock.connect_ex.return_value = 1
        monkeypatch.setattr(socket, "socket", lambda *a, **k: sock_mock)

        def _run_oserror(*a, **k):
            raise OSError("network down")

        monkeypatch.setattr(subprocess, "run", _run_oserror)
        # OSError -> caught -> returns False
        assert diag._test_if_this_is_our_host("1.2.3.4") is False


class TestPortDiagnosticsLogStartupExternalPorts:
    """Cover lines 414-426 of log_startup_diagnostics for external_ports paths."""

    @pytest.fixture
    def diag(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False, "platform": "alpine"},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        return PortDiagnostics()

    def test_log_startup_diagnostics_with_dict_external_ports(
        self, diag, monkeypatch
    ):
        """external_ports is a list of dicts -> dict-handling branch."""
        monkeypatch.setattr(
            type(diag), "_is_port_listening", lambda self, p: True
        )
        monkeypatch.setattr(
            type(diag),
            "_get_docker_port_mappings",
            lambda self: {"9374": [{"host": "0.0.0.0", "port": "8374"}]},
        )
        monkeypatch.setattr(
            type(diag), "_get_actual_host_ip", lambda self: "192.168.1.50"
        )
        # call should not raise; returns a report
        report = diag.log_startup_diagnostics()
        assert "host_info" in report

    def test_log_startup_diagnostics_with_simple_port_list(
        self, diag, monkeypatch
    ):
        """external_ports is a non-dict list - covers lines 421-423."""
        monkeypatch.setattr(
            type(diag), "_is_port_listening", lambda self, p: True
        )

        # simulate non-dict items in external_ports
        def _check(self):
            return {
                "internal_port_listening": True,
                "external_ports": ["8374"],  # bare strings
                "port_mappings": {},
                "issues": [],
                "solutions": [],
            }

        monkeypatch.setattr(type(diag), "check_port_binding", _check)
        monkeypatch.setattr(
            type(diag), "_get_actual_host_ip", lambda self: None
        )
        report = diag.log_startup_diagnostics()
        assert "host_info" in report


# ===========================================================================
# utils/logging_utils.py — uncovered branches
# ===========================================================================


class TestLoggingUtilsExtra:
    """Cover edge branches in logging_utils."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        import utils.logging_utils as lu

        prev_temp = lu._temp_debug_mode_enabled
        prev_expiry = lu._temp_debug_expiry
        prev_perm = lu._debug_mode_enabled
        lu._temp_debug_mode_enabled = False
        lu._temp_debug_expiry = 0
        lu._debug_mode_enabled = False
        # Also clear loading guard if leaked
        if hasattr(lu.is_debug_mode_enabled, "_loading"):
            delattr(lu.is_debug_mode_enabled, "_loading")
        try:
            yield
        finally:
            lu._temp_debug_mode_enabled = prev_temp
            lu._temp_debug_expiry = prev_expiry
            lu._debug_mode_enabled = prev_perm
            if hasattr(lu.is_debug_mode_enabled, "_loading"):
                delattr(lu.is_debug_mode_enabled, "_loading")

    def test_is_debug_mode_enabled_temp_active(self, monkeypatch):
        """Lines 56-61: temp debug active branch."""
        import utils.logging_utils as lu

        lu._temp_debug_mode_enabled = True
        lu._temp_debug_expiry = time.time() + 60
        # Enabled returns True from temp branch
        assert lu.is_debug_mode_enabled() is True

    def test_is_debug_mode_enabled_temp_expired_resets(self, monkeypatch):
        """Lines 62-65: temp debug expired path resets and falls through."""
        import utils.logging_utils as lu

        lu._temp_debug_mode_enabled = True
        lu._temp_debug_expiry = time.time() - 60  # expired

        # Stub out config service call so we don't blow up
        class _FakeSvc:
            def get_config(self, force_reload=False):
                return {"scheduler_debug_mode": False}

        monkeypatch.setattr(
            "services.config.config_service.get_config_service",
            lambda: _FakeSvc(),
        )
        result = lu.is_debug_mode_enabled()
        # Expired -> reset -> returns False
        assert result is False
        assert lu._temp_debug_mode_enabled is False

    def test_is_debug_mode_enabled_config_import_error(self, monkeypatch):
        """Lines 76-81: config service fails -> returns safe default."""
        import utils.logging_utils as lu

        def _broken():
            raise ImportError("config gone")

        monkeypatch.setattr(
            "services.config.config_service.get_config_service",
            _broken,
        )
        # Force into the config-error branch by ensuring temp debug is OFF
        lu._temp_debug_mode_enabled = False
        result = lu.is_debug_mode_enabled()
        assert result is False

    def test_is_debug_mode_enabled_returns_cached_during_recursion(
        self, monkeypatch
    ):
        """Lines 50-51: recursion guard short-circuit."""
        import utils.logging_utils as lu

        # Set the loading sentinel so the function returns the cached value
        lu.is_debug_mode_enabled._loading = True
        lu._debug_mode_enabled = True
        try:
            assert lu.is_debug_mode_enabled() is True
        finally:
            if hasattr(lu.is_debug_mode_enabled, "_loading"):
                delattr(lu.is_debug_mode_enabled, "_loading")

    def test_enable_temporary_debug_handles_logger_error(self, monkeypatch):
        """Lines 319-320: AttributeError in regular logger setup."""
        from utils.logging_utils import enable_temporary_debug
        import utils.logging_utils as lu

        # Spy on getLogger to make ddc.config getLogger raise on info() call
        real_get = logging.getLogger

        class _BadLogger:
            handlers = []

            def setLevel(self, *a):
                pass

            def info(self, *a, **k):
                raise AttributeError("logger broken")

            def addHandler(self, h):
                pass

        def _gl(name=None):
            if name == "ddc.config":
                return _BadLogger()
            return real_get(name)

        # Carefully patch the lookup used inside enable_temporary_debug
        monkeypatch.setattr(logging, "getLogger", _gl)
        success, expiry = enable_temporary_debug(1)
        assert success is True
        assert expiry > time.time()

    def test_disable_temporary_debug_swallows_runtime_error(self, monkeypatch):
        """Lines 357-359: error path in disable_temporary_debug."""
        import utils.logging_utils as lu

        # Force getLogger to raise RuntimeError when 'ddc.config' is requested
        real_get = logging.getLogger

        class _BadLogger:
            def info(self, *a, **k):
                raise RuntimeError("oops")

        def _gl(name=None):
            if name == "ddc.config":
                return _BadLogger()
            return real_get(name)

        monkeypatch.setattr(logging, "getLogger", _gl)
        # Should not raise — error caught and returns False
        result = lu.disable_temporary_debug()
        assert result is False

    def test_refresh_debug_status_handles_invalidate_error(self, monkeypatch):
        """Lines 257-258: ImportError on cache invalidation."""
        import utils.logging_utils as lu

        def _broken():
            raise AttributeError("cache service missing")

        monkeypatch.setattr(
            "services.config.config_service.get_config_service",
            _broken,
        )
        # Should return a bool without raising
        result = lu.refresh_debug_status()
        assert isinstance(result, bool)

    def test_get_logger_with_explicit_level(self):
        """Cover lines 426-428 (level argument provided)."""
        from utils.logging_utils import get_logger

        logger = get_logger("ddc.test.explicit_level", level=logging.WARNING)
        assert logger.level == logging.WARNING


# ===========================================================================
# utils/app_commands_helper.py — Strategy 3 fallback
# ===========================================================================


class TestAppCommandsHelperStrategy3:
    """Force the discord.ext.commands branch (lines 64-72)."""

    def test_strategy_3_falls_back_to_ext_commands(self, monkeypatch):
        from utils import app_commands_helper as ach

        # Snapshot
        prev_ac = ach.app_commands
        prev_opt = ach.DiscordOption
        prev_avail = ach.app_commands_available
        try:
            ach.app_commands = None
            ach.DiscordOption = None
            ach.app_commands_available = False

            # Setup builtins.__import__ to fail strategy 1 & 2 but pass 3
            real_import = (
                __builtins__["__import__"]
                if isinstance(__builtins__, dict)
                else __builtins__.__import__
            )

            class _FakeAppCommandsExt:
                pass

            class _FakeExtCommands:
                app_commands = _FakeAppCommandsExt()

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "discord" and "Option" in (fromlist or ()):
                    raise ImportError("no Option")
                if name == "discord" and "app_commands" in (fromlist or ()):
                    raise ImportError("no app_commands top-level")
                if name == "discord.ext.commands" and "app_commands" in (
                    fromlist or ()
                ):
                    return _FakeExtCommands()
                return real_import(name, globals, locals, fromlist, level)

            monkeypatch.setattr("builtins.__import__", fake_import)
            ac, opt, avail = ach.initialize_app_commands()
            # Strategy 3 worked
            assert avail is True
            # Option should be the ActualMockOption fallback
            assert opt is not None
        finally:
            ach.app_commands = prev_ac
            ach.DiscordOption = prev_opt
            ach.app_commands_available = prev_avail

    def test_all_strategies_fail_creates_full_mock(self, monkeypatch):
        """When ALL imports fail, we get the AppCommandsMock + ActualMockOption."""
        from utils import app_commands_helper as ach

        prev_ac = ach.app_commands
        prev_opt = ach.DiscordOption
        prev_avail = ach.app_commands_available
        try:
            ach.app_commands = None
            ach.DiscordOption = None
            ach.app_commands_available = False

            real_import = (
                __builtins__["__import__"]
                if isinstance(__builtins__, dict)
                else __builtins__.__import__
            )

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "discord" or name.startswith("discord."):
                    raise ImportError("nothing")
                return real_import(name, globals, locals, fromlist, level)

            monkeypatch.setattr("builtins.__import__", fake_import)
            ac, opt, avail = ach.initialize_app_commands()
            assert avail is False
            # Mock app_commands has these attrs
            assert hasattr(ac, "command")
            assert hasattr(ac, "describe")
            assert hasattr(ac, "autocomplete")
            assert hasattr(ac, "Choice")
            # Choice can be instantiated
            c = ac.Choice("name", 5)
            assert c.name == "name"
            assert c.value == 5
            # ActualMockOption
            inst = opt(int, description="desc")
            assert inst.description == "desc"
        finally:
            ach.app_commands = prev_ac
            ach.DiscordOption = prev_opt
            ach.app_commands_available = prev_avail


# ===========================================================================
# utils/common_helpers.py — uncovered edges
# ===========================================================================


class TestCommonHelpersEdges:
    """Cover small remaining edge cases."""

    def test_format_uptime_value_error_returns_unknown(self):
        from utils.common_helpers import format_uptime

        # Pass a value that survives the < 0 check but fails arithmetic
        class _Bad:
            def __lt__(self, other):
                return False

            def __floordiv__(self, other):
                raise ValueError("nope")

        # _Bad() < 0 returns False (OK), but // raises ValueError -> Unknown
        result = format_uptime(_Bad())
        assert result == "Unknown"

    def test_format_memory_invalid_input_returns_unknown(self):
        from utils.common_helpers import format_memory

        class _Bad:
            def __lt__(self, other):
                return False

            def __float__(self):
                raise ValueError("nope")

        assert format_memory(_Bad()) == "Unknown"

    def test_format_memory_kb_branch(self):
        from utils.common_helpers import format_memory

        # 1500 bytes = 1.5 KB
        assert "KB" in format_memory(1500)

    def test_format_memory_mb_branch(self):
        from utils.common_helpers import format_memory

        # 1.5 * 1024**2 = 1.5 MB
        assert "MB" in format_memory(int(1.5 * 1024 * 1024))

    def test_format_memory_gb_branch(self):
        from utils.common_helpers import format_memory

        assert "GB" in format_memory(int(2 * 1024 * 1024 * 1024))

    def test_format_cpu_percentage_invalid_returns_unknown(self):
        from utils.common_helpers import format_cpu_percentage

        # passing a string that can't be float-converted
        assert format_cpu_percentage("abc") == "Unknown"

    def test_format_cpu_percentage_none_returns_unknown(self):
        from utils.common_helpers import format_cpu_percentage

        assert format_cpu_percentage(None) == "Unknown"

    def test_format_cpu_percentage_valid(self):
        from utils.common_helpers import format_cpu_percentage

        assert format_cpu_percentage(45.5) == "45.5%"

    def test_truncate_string_non_string_input(self):
        from utils.common_helpers import truncate_string

        # int gets converted to "12345" (5 chars) -> no truncation
        assert truncate_string(12345, max_length=10) == "12345"

    def test_truncate_string_truncates_long_input(self):
        from utils.common_helpers import truncate_string

        text = "a" * 200
        result = truncate_string(text, max_length=20, suffix="...")
        assert len(result) == 20
        assert result.endswith("...")

    def test_validate_container_name_empty(self):
        from utils.common_helpers import validate_container_name

        assert validate_container_name("") is False
        assert validate_container_name(None) is False  # type: ignore

    def test_validate_container_name_too_long(self):
        from utils.common_helpers import validate_container_name

        assert validate_container_name("a" * 64) is False

    def test_validate_container_name_dot_start(self):
        from utils.common_helpers import validate_container_name

        # Pattern requires alphanumeric first char so '.foo' fails the regex
        # but our extra check on line 191 also rejects it
        assert validate_container_name(".foo") is False

    def test_parse_boolean_int_zero(self):
        from utils.common_helpers import parse_boolean

        assert parse_boolean(0) is False
        assert parse_boolean(1) is True

    def test_parse_boolean_unknown_returns_default(self):
        from utils.common_helpers import parse_boolean

        assert parse_boolean(object(), default=True) is True

    def test_sanitize_log_message_token_pattern(self):
        from utils.common_helpers import sanitize_log_message

        out = sanitize_log_message("token=abc123secrettoken")
        assert "***" in out
        assert "abc123secrettoken" not in out

    def test_sanitize_log_message_non_string_input(self):
        from utils.common_helpers import sanitize_log_message

        # Non-string converted via str()
        out = sanitize_log_message(12345)
        assert isinstance(out, str)

    def test_is_valid_ip_invalid(self):
        from utils.common_helpers import is_valid_ip

        assert is_valid_ip("not.an.ip") is False
        assert is_valid_ip("999.999.999.999") is False

    def test_is_valid_ip_valid(self):
        from utils.common_helpers import is_valid_ip

        assert is_valid_ip("192.168.1.1") is True

    def test_validate_ip_format_empty_returns_true(self):
        from utils.common_helpers import validate_ip_format

        # Empty input is valid (treated as "unset")
        assert validate_ip_format("") is True

    def test_validate_ip_format_with_port(self):
        from utils.common_helpers import validate_ip_format

        assert validate_ip_format("192.168.1.1:8080") is True
        assert validate_ip_format("example.com:443") is True

    def test_validate_ip_format_invalid(self):
        from utils.common_helpers import validate_ip_format

        assert validate_ip_format("invalid spaces") is False

    def test_batch_process_empty_list(self):
        from utils.common_helpers import batch_process

        assert batch_process([], 5) == []

    def test_batch_process_zero_batch_size(self):
        from utils.common_helpers import batch_process

        assert batch_process([1, 2, 3], 0) == []

    def test_batch_process_normal(self):
        from utils.common_helpers import batch_process

        assert batch_process([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_deep_merge_dicts_simple(self):
        from utils.common_helpers import deep_merge_dicts

        assert deep_merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_deep_merge_dicts_nested(self):
        from utils.common_helpers import deep_merge_dicts

        result = deep_merge_dicts(
            {"x": {"a": 1, "b": 2}},
            {"x": {"b": 99, "c": 3}},
        )
        assert result == {"x": {"a": 1, "b": 99, "c": 3}}

    def test_deep_merge_dicts_overwrites_non_dict(self):
        from utils.common_helpers import deep_merge_dicts

        assert deep_merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}

    def test_retry_on_exception_eventually_succeeds(self):
        from utils.common_helpers import retry_on_exception

        calls = {"n": 0}

        @retry_on_exception(max_retries=2, delay=0.001, backoff=1.0)
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("transient")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 2

    def test_retry_on_exception_raises_after_max(self):
        from utils.common_helpers import retry_on_exception

        @retry_on_exception(max_retries=1, delay=0.001, backoff=1.0)
        def always_fails():
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            always_fails()

    def test_get_current_timestamp_iso(self):
        from utils.common_helpers import get_current_timestamp

        ts = get_current_timestamp()
        # ISO format with timezone (+00:00 or Z)
        assert "T" in ts
        assert "+" in ts or "Z" in ts


# ===========================================================================
# Smoke test — run convenience entry points
# ===========================================================================


class TestSmoke:
    """Quick coverage smokes for top-level convenience functions."""

    def test_log_port_diagnostics_runs(self, monkeypatch):
        from app.utils import port_diagnostics as pd

        monkeypatch.setattr(
            pd.PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False, "platform": "alpine"},
        )
        monkeypatch.setattr(
            pd.PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            pd.PortDiagnostics, "_is_port_listening", lambda self, p: True
        )
        monkeypatch.setattr(
            pd.PortDiagnostics, "_get_docker_port_mappings", lambda self: {}
        )
        monkeypatch.setattr(
            pd.PortDiagnostics, "_get_actual_host_ip", lambda self: None
        )
        report = pd.log_port_diagnostics()
        assert "host_info" in report
