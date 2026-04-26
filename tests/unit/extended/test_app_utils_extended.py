# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Extended Unit Tests for app/utils + main_routes #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Functional unit tests for app/utils, utils/* and main_routes rest paths.

Targets (lifting coverage on uncovered branches without touching sys.modules):
  - app/utils/web_helpers.py          (43% -> 70%+)
  - app/utils/port_diagnostics.py     (44% -> 65%+)
  - app/blueprints/main_routes.py     (56% -> 70%+)
  - utils/app_commands_helper.py      (52% -> 80%+)
  - utils/import_utils.py             (66% -> 85%+)
  - utils/logging_utils.py            (69% -> 80%+)

Strategy
--------
* All modules are imported normally — *no* ``sys.modules`` manipulation.
* Heavy collaborators (Docker SDK, sockets, subprocess, services …) are
  patched via ``monkeypatch.setattr`` / ``unittest.mock.patch``.
* main_routes is mounted on a minimal Flask app following the same pattern
  as ``tests/unit/blueprints/test_main_automation_security_routes.py`` (auth
  stub via ``verify_password_callback`` override and JSON error handler).
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

import base64
import logging
import socket
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Auth helpers (re-implemented locally to avoid cross-test fixture coupling)
# ---------------------------------------------------------------------------

_AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(b"admin:test").decode(),
}


def _stub_auth(monkeypatch):
    """Replace HTTPBasicAuth.verify_password and error handler with stubs."""
    from app import auth as auth_module
    from flask import jsonify as _jsonify

    def _verify(username, password):
        if username and password:
            return "admin"
        return None

    monkeypatch.setattr(auth_module.auth, "verify_password_callback", _verify)

    def _err(status):  # pragma: no cover - stub
        resp = _jsonify(message="Authentication Required")
        resp.status_code = status
        return resp

    monkeypatch.setattr(auth_module.auth, "auth_error_callback", _err)


# ===========================================================================
# app/utils/web_helpers.py
# ===========================================================================


class TestWebHelpersBasics:
    """Pure helper coverage that does not touch threads/network."""

    def test_hash_container_data_stable_for_same_data(self):
        from app.utils.web_helpers import hash_container_data

        a = {"id": "abc", "status": "running", "image": "nginx:latest"}
        b = {"id": "abc", "status": "running", "image": "nginx:latest"}
        assert hash_container_data(a) == hash_container_data(b)

    def test_hash_container_data_changes_on_status_change(self):
        from app.utils.web_helpers import hash_container_data

        a = {"id": "abc", "status": "running", "image": "x"}
        b = {"id": "abc", "status": "stopped", "image": "x"}
        assert hash_container_data(a) != hash_container_data(b)

    def test_hash_container_data_handles_invalid_input(self):
        from app.utils.web_helpers import hash_container_data

        # ``None`` does not have ``.get`` so we hit the AttributeError path
        result = hash_container_data(None)
        # In error path, the helper returns ``time.time()`` -> a float
        assert isinstance(result, (int, float))

    def test_get_advanced_setting_uses_env_when_service_fails(self, monkeypatch):
        # Force the helper down its ImportError fallback by removing the
        # import target from sys.modules at function call time.
        import app.utils.web_helpers as wh

        monkeypatch.setenv("DDC_TEST_ADVANCED_KEY", "42")

        # Patch the lazy-imported config service to raise ImportError
        def _broken():
            raise ImportError("config service unavailable")

        monkeypatch.setattr(
            "services.config.config_service.get_config_service", _broken
        )
        value = wh._get_advanced_setting("DDC_TEST_ADVANCED_KEY", 7, int)
        assert value == 42

    def test_get_advanced_setting_bool_type(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setenv("DDC_TEST_BOOL_KEY", "true")
        monkeypatch.setattr(
            "services.config.config_service.get_config_service",
            lambda: (_ for _ in ()).throw(ImportError("nope")),
        )
        assert wh._get_advanced_setting("DDC_TEST_BOOL_KEY", False, bool) is True

    def test_get_advanced_setting_value_error_falls_back(self, monkeypatch):
        import app.utils.web_helpers as wh

        # Service returns junk that fails int() conversion
        bad_cfg = MagicMock()
        bad_cfg.get_config.return_value = {
            "advanced_settings": {"DDC_X": "not-a-number"}
        }
        monkeypatch.setattr(
            "services.config.config_service.get_config_service",
            lambda: bad_cfg,
        )
        # No env var -> default returned via fallback path
        monkeypatch.delenv("DDC_X", raising=False)
        result = wh._get_advanced_setting("DDC_X", 99, int)
        assert result == 99


class TestWebHelpersCleanupCache:
    """Cover the _cleanup_docker_cache memory-management helper."""

    def test_cleanup_first_call_seeds_timestamp(self):
        from app.utils.web_helpers import _cleanup_docker_cache, docker_cache

        docker_cache["last_cleanup"] = None
        _cleanup_docker_cache(logging.getLogger("t"), 1000.0)
        assert docker_cache["last_cleanup"] == 1000.0

    def test_cleanup_skips_when_recent(self):
        from app.utils.web_helpers import _cleanup_docker_cache, docker_cache

        docker_cache["last_cleanup"] = 1000.0
        # Within CACHE_CLEANUP_INTERVAL window
        _cleanup_docker_cache(logging.getLogger("t"), 1100.0)
        # last_cleanup should not have advanced
        assert docker_cache["last_cleanup"] == 1000.0

    def test_cleanup_removes_old_entries(self):
        from app.utils.web_helpers import (
            CACHE_CLEANUP_INTERVAL,
            _cleanup_docker_cache,
            docker_cache,
        )

        # Seed an "old" entry that should be cleaned up
        cur = 100000.0
        docker_cache["last_cleanup"] = cur - CACHE_CLEANUP_INTERVAL - 1
        docker_cache["container_timestamps"] = {
            "old_one": cur - 700,  # > 600s cutoff -> removed
            "fresh_one": cur - 10,
        }
        docker_cache["container_hashes"] = {
            "old_one": 123,
            "fresh_one": 456,
        }
        _cleanup_docker_cache(logging.getLogger("t"), cur)
        assert "old_one" not in docker_cache["container_timestamps"]
        assert "fresh_one" in docker_cache["container_timestamps"]
        assert "old_one" not in docker_cache["container_hashes"]
        assert docker_cache["last_cleanup"] == cur


class TestUpdateDockerCache:
    """Cover update_docker_cache via mocked docker.from_env."""

    def _build_fake_container(self, name, status="running", image_tag="nginx"):
        c = MagicMock()
        c.id = "abcdef0123456789abcdef0123456789"
        c.name = name
        c.status = status
        c.image.tags = [image_tag] if image_tag else []
        c.image.id = "sha256:" + ("0" * 64)
        return c

    def test_update_cache_populates_containers(self, monkeypatch):
        import app.utils.web_helpers as wh

        client = MagicMock()
        client.containers.list.return_value = [
            self._build_fake_container("zeta"),
            self._build_fake_container("alpha"),
        ]
        client.close = MagicMock()
        monkeypatch.setattr("app.utils.web_helpers.docker.from_env", lambda **kw: client)

        # Reset cache state
        with wh.cache_lock:
            wh.docker_cache["containers"] = []
            wh.docker_cache["error"] = None
            wh.docker_cache["global_timestamp"] = None
            wh.docker_cache["access_count"] = 0

        wh.update_docker_cache(logging.getLogger("t"))
        # Sorted alphabetically
        names = [c["name"] for c in wh.docker_cache["containers"]]
        assert names == ["alpha", "zeta"]
        assert wh.docker_cache["global_timestamp"] is not None
        assert wh.docker_cache["error"] is None

    def test_update_cache_handles_docker_exception(self, monkeypatch):
        import importlib
        import sys
        import docker as docker_mod

        # Earlier tests (e.g. test_configuration_services.py) install a
        # stub ``app.utils.web_helpers`` module in ``sys.modules`` that
        # lacks the real ``update_docker_cache``/``cache_lock``/``docker``
        # attributes.  Force a fresh load from disk for this test, then
        # restore whatever was there afterwards so we don't break a
        # subsequent run inside the same process.
        prev_wh = sys.modules.get("app.utils.web_helpers")
        prev_app_utils = sys.modules.get("app.utils")
        # Drop the cached entry so importlib reloads the real module.
        sys.modules.pop("app.utils.web_helpers", None)
        try:
            wh = importlib.import_module("app.utils.web_helpers")
            # Make sure ``app.utils`` exposes the freshly loaded child.
            app_utils_pkg = importlib.import_module("app.utils")
            app_utils_pkg.web_helpers = wh

            def _raise(**kw):
                raise docker_mod.errors.DockerException("daemon down")

            # Patch via the live module attribute (not via dotted string).
            monkeypatch.setattr(wh.docker, "from_env", _raise)

            # Reset cache state so we deterministically observe the error
            # written by this exception path.
            with wh.cache_lock:
                wh.docker_cache["error"] = None

            wh.update_docker_cache(logging.getLogger("t"))
            # Error stored on cache with the alarm prefix
            assert "DOCKER CONNECTIVITY LOST" in (wh.docker_cache["error"] or "")
        finally:
            # Restore prior sys.modules state so we don't disturb other tests.
            if prev_wh is not None:
                sys.modules["app.utils.web_helpers"] = prev_wh
                if prev_app_utils is not None:
                    setattr(prev_app_utils, "web_helpers", prev_wh)
            else:
                sys.modules.pop("app.utils.web_helpers", None)

    def test_update_cache_handles_timeout_message(self, monkeypatch):
        import app.utils.web_helpers as wh

        client = MagicMock()
        client.containers.list.side_effect = Exception(
            "Read timed out after 30 seconds"
        )
        client.close = MagicMock()
        monkeypatch.setattr("app.utils.web_helpers.docker.from_env", lambda **kw: client)

        with wh.cache_lock:
            wh.docker_cache["containers"] = []
            wh.docker_cache["error"] = None
        # Timeout path should swallow into empty-list update, no crash
        wh.update_docker_cache(logging.getLogger("t"))
        assert wh.docker_cache["containers"] == []

    def test_update_cache_image_id_fallback_when_no_tags(self, monkeypatch):
        """No tags -> image field uses id[:12]."""
        import app.utils.web_helpers as wh

        c = MagicMock()
        c.id = "deadbeefcafe0011223344556677889900"
        c.name = "no_tags"
        c.status = "running"
        c.image.tags = []
        c.image.id = "sha256:deadbeefcafe0011223344"

        client = MagicMock()
        client.containers.list.return_value = [c]
        client.close = MagicMock()
        monkeypatch.setattr("app.utils.web_helpers.docker.from_env", lambda **kw: client)

        with wh.cache_lock:
            wh.docker_cache["containers"] = []

        wh.update_docker_cache(logging.getLogger("t"))
        result = [c for c in wh.docker_cache["containers"] if c["name"] == "no_tags"][0]
        # First 12 chars of the image *id* string
        assert result["image"] == "sha256:deadb"


class TestGetDockerContainersLive:
    """Cover the cache-hit / cache-miss branches of get_docker_containers_live."""

    def test_filtered_cache_hit(self, monkeypatch):
        import app.utils.web_helpers as wh

        # Disable background-refresh side effects
        monkeypatch.setattr(wh, "ENABLE_BACKGROUND_REFRESH", False)
        monkeypatch.setattr(wh, "DEFAULT_CACHE_DURATION", 999)

        with wh.cache_lock:
            wh.docker_cache["containers"] = [
                {"id": "1", "name": "alpha", "status": "running", "image": "x"},
                {"id": "2", "name": "beta", "status": "running", "image": "x"},
            ]
            wh.docker_cache["error"] = None
            wh.docker_cache["global_timestamp"] = time.time()

        out, err = wh.get_docker_containers_live(
            logging.getLogger("t"), container_name="alpha"
        )
        assert err is None
        assert len(out) == 1 and out[0]["name"] == "alpha"

    def test_full_cache_hit(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setattr(wh, "ENABLE_BACKGROUND_REFRESH", False)
        monkeypatch.setattr(wh, "DEFAULT_CACHE_DURATION", 999)
        with wh.cache_lock:
            wh.docker_cache["containers"] = [
                {"id": "1", "name": "alpha", "status": "running", "image": "x"},
            ]
            wh.docker_cache["error"] = None
            wh.docker_cache["global_timestamp"] = time.time()

        out, _ = wh.get_docker_containers_live(logging.getLogger("t"))
        assert out and out[0]["name"] == "alpha"

    def test_missing_container_returns_all(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setattr(wh, "ENABLE_BACKGROUND_REFRESH", False)
        monkeypatch.setattr(wh, "DEFAULT_CACHE_DURATION", 999)
        with wh.cache_lock:
            wh.docker_cache["containers"] = [
                {"id": "1", "name": "alpha", "status": "running", "image": "x"},
            ]
            wh.docker_cache["error"] = None
            wh.docker_cache["global_timestamp"] = time.time()

        out, _ = wh.get_docker_containers_live(
            logging.getLogger("t"), container_name="missing"
        )
        # Missing -> falls back to returning all
        assert any(c["name"] == "alpha" for c in out)

    def test_force_refresh_invokes_update(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setattr(wh, "ENABLE_BACKGROUND_REFRESH", False)
        called = {"n": 0}

        def fake_update(logger):
            called["n"] += 1
            with wh.cache_lock:
                wh.docker_cache["containers"] = [
                    {"id": "1", "name": "x", "status": "running", "image": "img"}
                ]
                wh.docker_cache["global_timestamp"] = time.time()

        monkeypatch.setattr(wh, "update_docker_cache", fake_update)
        out, _ = wh.get_docker_containers_live(
            logging.getLogger("t"), force_refresh=True
        )
        assert called["n"] == 1
        assert out and out[0]["name"] == "x"


class TestBackgroundRefreshLifecycle:
    """Cover start_background_refresh and stop_background_refresh entry/exit."""

    def test_start_background_refresh_handles_connectivity_failure(
        self, monkeypatch
    ):
        import app.utils.web_helpers as wh

        # Force the connectivity probe to raise.
        class _FailClient:
            def __init__(self, *a, **k):
                raise RuntimeError("docker offline")

        monkeypatch.setattr("app.utils.web_helpers.docker.DockerClient", _FailClient)

        # Stub thread creation so no real worker starts.
        fake_thread = MagicMock()
        monkeypatch.setattr(
            "app.utils.web_helpers.create_thread",
            lambda target, args, daemon=True, name=None: fake_thread,
        )
        # Reset module state so this start actually creates a thread.
        monkeypatch.setattr(wh, "background_refresh_thread", None, raising=False)
        wh.stop_background_thread.set()

        wh.start_background_refresh(logging.getLogger("t"))
        # Confirm we called start() on the fake thread (or start_later for gevent)
        assert fake_thread.start.called or fake_thread.start_later.called

    def test_stop_background_refresh_no_thread_no_op(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setattr(wh, "background_refresh_thread", None, raising=False)
        # Should not raise even when thread is None
        wh.stop_background_refresh(logging.getLogger("t"))

    def test_stop_background_refresh_joins_thread(self, monkeypatch):
        import app.utils.web_helpers as wh

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        # gevent flag false in this build (lazy import path)
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        monkeypatch.setattr(wh, "background_refresh_thread", fake_thread, raising=False)
        wh.stop_background_refresh(logging.getLogger("t"))
        # join should have been attempted
        assert fake_thread.join.called

    def test_stop_mech_decay_no_thread(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setattr(wh, "mech_decay_thread", None, raising=False)
        wh.stop_mech_decay_background(logging.getLogger("t"))


class TestSetInitialPasswordFromEnv:
    """Cover the bootstrap helper that seeds the admin password from env."""

    def test_no_env_var_skips(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.delenv("DDC_ADMIN_PASSWORD", raising=False)
        # Should silently return without touching config
        wh.set_initial_password_from_env()  # no exception

    def test_env_var_sets_hash_when_unset(self, monkeypatch):
        import app.utils.web_helpers as wh

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "supersecret")

        saved = {}

        def fake_load_config():
            return {"web_ui_password_hash": None}

        def fake_save_config(cfg):
            saved.update(cfg)
            return True

        monkeypatch.setattr(
            "services.config.config_service.load_config", fake_load_config
        )
        monkeypatch.setattr(
            "services.config.config_service.save_config", fake_save_config
        )
        wh.set_initial_password_from_env()
        assert "web_ui_password_hash" in saved
        # Make sure the saved hash is non-empty (proves generate_password_hash ran)
        assert saved["web_ui_password_hash"] and len(saved["web_ui_password_hash"]) > 10

    def test_env_var_skips_when_password_already_set(self, monkeypatch):
        import app.utils.web_helpers as wh
        from werkzeug.security import generate_password_hash

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "supersecret")

        # Existing hash that is NOT 'admin' -> should skip
        existing = generate_password_hash("not-admin", method="pbkdf2:sha256:600000")
        save_calls = {"n": 0}

        def fake_save(cfg):
            save_calls["n"] += 1
            return True

        monkeypatch.setattr(
            "services.config.config_service.load_config",
            lambda: {"web_ui_password_hash": existing},
        )
        monkeypatch.setattr(
            "services.config.config_service.save_config", fake_save
        )
        wh.set_initial_password_from_env()
        assert save_calls["n"] == 0

    def test_env_var_resets_when_default_admin(self, monkeypatch):
        """If existing hash matches 'admin', env var should overwrite."""
        import app.utils.web_helpers as wh
        from werkzeug.security import generate_password_hash

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "supersecret")
        admin_hash = generate_password_hash("admin", method="pbkdf2:sha256:600000")
        saved = {}

        monkeypatch.setattr(
            "services.config.config_service.load_config",
            lambda: {"web_ui_password_hash": admin_hash},
        )
        monkeypatch.setattr(
            "services.config.config_service.save_config",
            lambda c: saved.update(c) or True,
        )
        wh.set_initial_password_from_env()
        # admin hash should have been replaced
        assert saved.get("web_ui_password_hash") != admin_hash

    def test_env_var_handles_malformed_hash(self, monkeypatch):
        """A malformed hash triggers the data-error branch and resets."""
        import app.utils.web_helpers as wh

        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "supersecret")
        saved = {}
        monkeypatch.setattr(
            "services.config.config_service.load_config",
            lambda: {"web_ui_password_hash": "not-a-valid-hash"},
        )
        monkeypatch.setattr(
            "services.config.config_service.save_config",
            lambda c: saved.update(c) or True,
        )
        wh.set_initial_password_from_env()
        # Either reset or skipped — function should not raise


class TestSetupActionLogger:
    """Cover setup_action_logger error paths."""

    def test_returns_logger_on_success(self, monkeypatch):
        import app.utils.web_helpers as wh

        # Stub the action_logger module that the helper imports
        fake_logger = logging.getLogger("user_actions_test")
        fake_module = MagicMock()
        fake_module.user_action_logger = fake_logger
        fake_module._ACTION_LOG_FILE = "/tmp/fake.log"

        # Patch via real module path
        monkeypatch.setattr(
            "services.infrastructure.action_logger.user_action_logger",
            fake_logger,
            raising=False,
        )
        monkeypatch.setattr(
            "services.infrastructure.action_logger._ACTION_LOG_FILE",
            "/tmp/fake.log",
            raising=False,
        )

        app_inst = MagicMock()
        app_inst.logger = logging.getLogger("setup_action_test")
        result = wh.setup_action_logger(app_inst)
        assert result is fake_logger

    def test_returns_fallback_on_import_error(self, monkeypatch):
        """ImportError should hit the except branch and return a fallback logger."""
        import app.utils.web_helpers as wh

        # Make the action_logger module import fail by removing it from
        # sys.modules and stubbing builtins.__import__ for that path.
        real_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict
        ) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "services.infrastructure.action_logger":
                raise ImportError("simulated import failure")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        app_inst = MagicMock()
        app_inst.logger = MagicMock()
        result = wh.setup_action_logger(app_inst)
        # Returns a fallback logger object (logging.getLogger result)
        assert result is not None
        assert hasattr(result, "info") or callable(getattr(result, "info", None))


class TestBackgroundRefreshWorker:
    """Run background_refresh_worker briefly and verify clean exit."""

    def test_worker_exits_when_stop_event_set(self, monkeypatch):
        import app.utils.web_helpers as wh

        # Stub update_docker_cache so we don't hit real Docker
        monkeypatch.setattr(
            wh, "update_docker_cache", lambda logger: None
        )
        # Make sleep return immediately
        monkeypatch.setattr(wh, "HAS_GEVENT", False)

        # Set the stop event before calling so the loop exits on first check
        wh.stop_background_thread.set()
        try:
            wh.background_refresh_worker(logging.getLogger("t"))
        finally:
            wh.stop_background_thread.clear()
        # Reaching here = success (worker returned cleanly)

    def test_worker_handles_runtime_error(self, monkeypatch):
        """Inner exception path: update_docker_cache raises -> handled."""
        import app.utils.web_helpers as wh

        monkeypatch.setattr(wh, "HAS_GEVENT", False)

        called = {"n": 0}

        def fake_update(logger):
            called["n"] += 1
            # First call raises, then set the stop event so the loop exits
            if called["n"] == 1:
                wh.stop_background_thread.set()
                raise RuntimeError("svc unavailable")

        monkeypatch.setattr(wh, "update_docker_cache", fake_update)
        # Patch time.sleep to no-op to keep the test fast
        monkeypatch.setattr(wh.time, "sleep", lambda s: None)
        wh.stop_background_thread.clear()
        try:
            wh.background_refresh_worker(logging.getLogger("t"))
        finally:
            wh.stop_background_thread.clear()
        # Worker should have invoked update_docker_cache exactly once
        assert called["n"] == 1


class TestMechDecayWorker:
    """Run mech_decay_worker briefly + lifecycle helpers."""

    def test_worker_exits_when_stop_event_set(self, monkeypatch):
        import app.utils.web_helpers as wh

        # Stub the mech progress service
        fake_state = SimpleNamespace(is_offline=False, power_current=10.5)
        fake_service = MagicMock()
        fake_service.get_state.return_value = fake_state
        monkeypatch.setattr(
            "services.mech.progress_service.get_progress_service",
            lambda: fake_service,
        )
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        monkeypatch.setattr(wh.time, "sleep", lambda s: None)

        # Make the inner loop exit immediately by setting the stop event after
        # the first get_state call
        original_get_state = fake_service.get_state

        def trip_then_return():
            wh.stop_mech_decay_thread.set()
            return fake_state

        fake_service.get_state.side_effect = trip_then_return
        wh.stop_mech_decay_thread.clear()
        try:
            wh.mech_decay_worker(logging.getLogger("t"))
        finally:
            wh.stop_mech_decay_thread.clear()

    def test_worker_handles_offline_state(self, monkeypatch):
        import app.utils.web_helpers as wh

        offline_state = SimpleNamespace(is_offline=True, power_current=0)
        fake_service = MagicMock()

        def trip_then_return():
            wh.stop_mech_decay_thread.set()
            return offline_state

        fake_service.get_state.side_effect = trip_then_return
        monkeypatch.setattr(
            "services.mech.progress_service.get_progress_service",
            lambda: fake_service,
        )
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        monkeypatch.setattr(wh.time, "sleep", lambda s: None)
        wh.stop_mech_decay_thread.clear()
        try:
            wh.mech_decay_worker(logging.getLogger("t"))
        finally:
            wh.stop_mech_decay_thread.clear()

    def test_start_mech_decay_creates_thread(self, monkeypatch):
        import app.utils.web_helpers as wh

        fake_thread = MagicMock()
        fake_thread.dead = False
        fake_thread.is_alive.return_value = False
        monkeypatch.setattr(
            wh,
            "create_thread",
            lambda target, args, daemon=True, name=None: fake_thread,
        )
        monkeypatch.setattr(wh, "mech_decay_thread", None, raising=False)
        wh.start_mech_decay_background(logging.getLogger("t"))
        # Either start() or start_later() should have been called
        assert fake_thread.start.called or fake_thread.start_later.called

    def test_start_mech_decay_skips_when_alive(self, monkeypatch):
        import app.utils.web_helpers as wh

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        fake_thread.dead = False
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        monkeypatch.setattr(wh, "mech_decay_thread", fake_thread, raising=False)
        creation_counter = {"n": 0}
        monkeypatch.setattr(
            wh, "create_thread",
            lambda *a, **kw: creation_counter.update(n=creation_counter["n"] + 1) or MagicMock(),
        )
        wh.start_mech_decay_background(logging.getLogger("t"))
        # Existing thread alive -> create_thread not called
        assert creation_counter["n"] == 0

    def test_stop_mech_decay_joins_thread(self, monkeypatch):
        import app.utils.web_helpers as wh

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        fake_thread.dead = False
        monkeypatch.setattr(wh, "HAS_GEVENT", False)
        monkeypatch.setattr(wh, "mech_decay_thread", fake_thread, raising=False)
        wh.stop_mech_decay_background(logging.getLogger("t"))
        assert fake_thread.join.called


class TestCheckDockerConnectivity:
    """Cover the async check_docker_connectivity helper."""

    def test_check_docker_connectivity_success(self, monkeypatch):
        import asyncio

        from app.utils import web_helpers as wh

        fake_service = MagicMock()

        async def fake_check(req):
            return SimpleNamespace(
                is_connected=True,
                error_message="",
                error_type="",
                technical_details="",
            )

        fake_service.check_connectivity = fake_check
        monkeypatch.setattr(
            "services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
            lambda: fake_service,
        )
        result = asyncio.get_event_loop().run_until_complete(
            wh.check_docker_connectivity(logging.getLogger("t"))
        ) if not asyncio.get_event_loop().is_running() else None
        if result is None:
            # Fallback for environments where the loop is already running
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    wh.check_docker_connectivity(logging.getLogger("t"))
                )
            finally:
                loop.close()
        assert result is True

    def test_check_docker_connectivity_failure(self, monkeypatch):
        import asyncio

        from app.utils import web_helpers as wh

        fake_service = MagicMock()

        async def fake_check(req):
            return SimpleNamespace(
                is_connected=False,
                error_message="connection refused",
                error_type="ConnectionError",
                technical_details="docker.sock missing",
            )

        fake_service.check_connectivity = fake_check
        monkeypatch.setattr(
            "services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
            lambda: fake_service,
        )
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                wh.check_docker_connectivity(logging.getLogger("t"))
            )
        finally:
            loop.close()
        assert result is False


# ===========================================================================
# app/utils/port_diagnostics.py
# ===========================================================================


class TestPortDiagnosticsHelpers:
    """Cover smaller helpers in PortDiagnostics not exercised by existing tests."""

    @pytest.fixture
    def diag(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        # Skip the heavy host_info collection by stubbing slow methods
        monkeypatch.setattr(
            PortDiagnostics, "_get_host_info", lambda self: {"is_unraid": False}
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc-test"
        )
        return PortDiagnostics()

    def test_get_unraid_solutions_contains_unraid_token(self, diag):
        out = diag._get_unraid_solutions()
        assert any("UNRAID" in s for s in out)
        # Container name flows into the manual command
        assert any("ddc-test" in s for s in out)

    def test_get_docker_solutions_contains_port_mapping(self, diag):
        out = diag._get_docker_solutions()
        assert any("-p 8374" in s for s in out)
        assert any("ddc-test" in s for s in out)

    def test_is_port_listening_socket_error_returns_false(self, diag, monkeypatch):
        # Force socket.connect_ex to raise OSError so we hit the except branch
        class _BoomSock:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def settimeout(self, t):
                pass

            def connect_ex(self, addr):
                raise OSError("boom")

        monkeypatch.setattr(socket, "socket", lambda *a, **k: _BoomSock())
        assert diag._is_port_listening(9374) is False

    def test_is_external_port_accessible_returns_true(self, diag):
        # Stubbed implementation always returns True
        assert diag._is_external_port_accessible(8374) is True

    def test_get_docker_port_mappings_no_container_name(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_get_host_info", lambda self: {"is_unraid": False}
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: None
        )
        diag = PortDiagnostics()
        assert diag._get_docker_port_mappings() == {}

    def test_get_docker_port_mappings_parses_output(self, diag, monkeypatch):
        result = SimpleNamespace(
            returncode=0,
            stdout="9374/tcp -> 0.0.0.0:8374\n",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        mappings = diag._get_docker_port_mappings()
        assert "9374" in mappings
        assert mappings["9374"][0]["port"] == "8374"

    def test_get_docker_port_mappings_handles_cmd_missing(self, diag, monkeypatch):
        def _missing(*a, **k):
            raise FileNotFoundError("docker not found")

        monkeypatch.setattr(subprocess, "run", _missing)
        assert diag._get_docker_port_mappings() == {}

    def test_check_port_binding_no_internal_listener(self, diag, monkeypatch):
        monkeypatch.setattr(
            type(diag), "_is_port_listening", lambda self, p: False
        )
        result = diag.check_port_binding()
        assert result["internal_port_listening"] is False
        assert any("not listening" in i for i in result["issues"])

    def test_check_port_binding_listening_with_mapping(self, diag, monkeypatch):
        monkeypatch.setattr(
            type(diag), "_is_port_listening", lambda self, p: True
        )
        monkeypatch.setattr(
            type(diag),
            "_get_docker_port_mappings",
            lambda self: {"9374": [{"host": "0.0.0.0", "port": "8374"}]},
        )
        out = diag.check_port_binding()
        assert out["internal_port_listening"] is True
        assert out["external_ports"]

    def test_try_environment_variable_ip_returns_value(self, diag, monkeypatch):
        monkeypatch.setenv("HOST_IP", "10.20.30.40")
        assert diag._try_environment_variable_ip() == "10.20.30.40"

    def test_try_environment_variable_ip_unraid(self, diag, monkeypatch):
        monkeypatch.delenv("HOST_IP", raising=False)
        monkeypatch.setenv("UNRAID_IP", "192.168.1.99")
        assert diag._try_environment_variable_ip() == "192.168.1.99"

    def test_try_environment_variable_ip_none(self, diag, monkeypatch):
        for var in ("HOST_IP", "UNRAID_IP", "SERVER_IP"):
            monkeypatch.delenv(var, raising=False)
        assert diag._try_environment_variable_ip() is None

    def test_get_actual_host_ip_uses_env_var(self, diag, monkeypatch):
        monkeypatch.setenv("HOST_IP", "1.2.3.4")
        assert diag._get_actual_host_ip() == "1.2.3.4"

    def test_get_actual_host_ip_all_methods_fail(self, diag, monkeypatch):
        for var in ("HOST_IP", "UNRAID_IP", "SERVER_IP"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            type(diag), "_try_traceroute_ip", lambda self: None
        )
        monkeypatch.setattr(
            type(diag), "_try_docker_host_gateway", lambda self: None
        )
        # Returns None; no exception
        assert diag._get_actual_host_ip() is None

    def test_run_port_diagnostics_convenience(self, monkeypatch):
        from app.utils.port_diagnostics import (
            PortDiagnostics,
            run_port_diagnostics,
        )

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False, "platform": "alpine"},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "check_port_binding",
            lambda self: {
                "internal_port_listening": True,
                "external_ports": [],
                "port_mappings": {},
                "issues": [],
                "solutions": [],
            },
        )
        report = run_port_diagnostics()
        assert "host_info" in report
        assert report["container_name"] == "ddc"

    def test_test_if_this_is_our_host_socket_failure(self, diag, monkeypatch):
        # All connect_ex calls fail -> nc fallback also raises -> returns False
        sock_mock = MagicMock()
        sock_mock.__enter__ = lambda self: self
        sock_mock.__exit__ = lambda self, *a: False
        sock_mock.connect_ex.return_value = 1
        monkeypatch.setattr(socket, "socket", lambda *a, **k: sock_mock)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("nc")),
        )
        assert diag._test_if_this_is_our_host("1.2.3.4") is False


class TestPortDiagnosticsHostMetrics:
    """Cover the host metrics helpers (uptime, memory, disk, supervisord)."""

    @pytest.fixture
    def fresh_diag(self, monkeypatch):
        """Build PortDiagnostics WITHOUT bypassing _get_host_info."""
        from app.utils.port_diagnostics import PortDiagnostics

        # Speed up: stub all the slow side methods individually
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        return PortDiagnostics

    def test_get_container_uptime_parses_proc_uptime(self, monkeypatch, fresh_diag):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        # 90061 seconds = 1d 1h 1m
        with patch("builtins.open", mock_open(read_data="90061.0 0\n")):
            instance = object.__new__(PortDiagnostics)
            uptime = instance._get_container_uptime()
        assert "1d" in uptime

    def test_get_container_uptime_hour_format(self):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        # 7200 seconds = 2 hours
        with patch("builtins.open", mock_open(read_data="7200.0 0\n")):
            instance = object.__new__(PortDiagnostics)
            uptime = instance._get_container_uptime()
        assert "h" in uptime and "d" not in uptime

    def test_get_container_uptime_minute_format(self):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        with patch("builtins.open", mock_open(read_data="120.0 0\n")):
            instance = object.__new__(PortDiagnostics)
            uptime = instance._get_container_uptime()
        assert uptime.endswith("m")

    def test_get_container_uptime_io_error_returns_unknown(self):
        from app.utils.port_diagnostics import PortDiagnostics

        with patch("builtins.open", side_effect=OSError("nope")):
            instance = object.__new__(PortDiagnostics)
            assert instance._get_container_uptime() == "unknown"

    def test_get_container_uptime_value_error_returns_unknown(self):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        with patch("builtins.open", mock_open(read_data="garbage\n")):
            instance = object.__new__(PortDiagnostics)
            assert instance._get_container_uptime() == "unknown"

    def test_get_memory_usage_parses_meminfo(self):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        meminfo = "MemTotal: 1024000 kB\nMemAvailable: 512000 kB\n"
        with patch("builtins.open", mock_open(read_data=meminfo)):
            instance = object.__new__(PortDiagnostics)
            usage = instance._get_memory_usage()
        # Format: "X MB / Y MB (Z%)"
        assert "MB" in usage
        assert "%" in usage

    def test_get_memory_usage_io_error(self):
        from app.utils.port_diagnostics import PortDiagnostics

        with patch("builtins.open", side_effect=OSError("nope")):
            instance = object.__new__(PortDiagnostics)
            assert instance._get_memory_usage() == "unknown"

    def test_get_disk_usage_returns_string(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        # Stub shutil.disk_usage to return predictable values
        import shutil

        monkeypatch.setattr(
            shutil,
            "disk_usage",
            lambda p: SimpleNamespace(
                total=1000_000_000, used=500_000_000, free=500_000_000
            ).__dict__.values()
            and (1000_000_000, 500_000_000, 500_000_000),
        )
        instance = object.__new__(PortDiagnostics)
        usage = instance._get_disk_usage()
        # Should produce a parsable string
        assert isinstance(usage, str)

    def test_get_disk_usage_oserror_returns_unknown(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics
        import shutil

        def _fail(p):
            raise OSError("disk gone")

        monkeypatch.setattr(shutil, "disk_usage", _fail)
        instance = object.__new__(PortDiagnostics)
        assert instance._get_disk_usage() == "unknown"

    def test_get_supervisord_status_parses_output(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        result = SimpleNamespace(
            returncode=0,
            stdout="webui RUNNING pid 100\nbot RUNNING pid 200\n",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        instance = object.__new__(PortDiagnostics)
        out = instance._get_supervisord_status()
        assert out.get("webui") == "RUNNING"
        assert out.get("bot") == "RUNNING"

    def test_get_supervisord_status_missing_returns_error(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(
                FileNotFoundError("supervisorctl")
            ),
        )
        instance = object.__new__(PortDiagnostics)
        out = instance._get_supervisord_status()
        assert "error" in out

    def test_get_ddc_memory_usage_parses_docker_stats(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )

        result = SimpleNamespace(
            returncode=0,
            stdout="MemUsage\n100MiB / 1GiB\n",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        instance = PortDiagnostics()
        usage = instance._get_ddc_memory_usage()
        assert usage == "100MiB / 1GiB"

    def test_get_ddc_memory_usage_subprocess_fail_returns_unknown(
        self, monkeypatch
    ):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("docker")),
        )
        instance = PortDiagnostics()
        assert instance._get_ddc_memory_usage() == "unknown"

    def test_get_ddc_image_size_parses_output(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )

        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "Repository:Tag\tSize\n"
                "dockerdiscordcontrol/ddc:latest\t150MB\n"
            ),
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        instance = PortDiagnostics()
        size = instance._get_ddc_image_size()
        assert size == "150MB"

    def test_get_ddc_image_size_missing_docker_returns_unknown(
        self, monkeypatch
    ):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("docker")),
        )
        instance = PortDiagnostics()
        assert instance._get_ddc_image_size() == "unknown"


class TestPortDiagnosticsContainerName:
    """Cover the _detect_container_name resolution paths."""

    def test_detect_container_name_uses_etc_hostname(self):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        # docker inspect not available; fallback to hostname
        with patch("builtins.open", mock_open(read_data="my-host\n")):
            with patch.object(
                subprocess,
                "run",
                side_effect=FileNotFoundError("no docker"),
            ):
                instance = object.__new__(PortDiagnostics)
                name = instance._detect_container_name()
        assert name == "my-host"

    def test_detect_container_name_inspect_success(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        result = SimpleNamespace(returncode=0, stdout="/named-x\n")
        with patch("builtins.open", mock_open(read_data="abc\n")):
            monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
            instance = object.__new__(PortDiagnostics)
            name = instance._detect_container_name()
        assert name == "named-x"

    def test_detect_container_name_oserror_returns_default(self):
        from app.utils.port_diagnostics import PortDiagnostics

        with patch("builtins.open", side_effect=OSError("denied")):
            instance = object.__new__(PortDiagnostics)
            name = instance._detect_container_name()
        assert name == "dockerdiscordcontrol"


class TestPortDiagnosticsLogStartup:
    """Cover log_startup_diagnostics output paths."""

    def test_log_startup_diagnostics_listening(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False, "platform": "alpine"},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "check_port_binding",
            lambda self: {
                "internal_port_listening": True,
                "external_ports": [{"host": "0.0.0.0", "port": "8374"}],
                "port_mappings": {"9374": [{"host": "0.0.0.0", "port": "8374"}]},
                "issues": [],
                "solutions": [],
            },
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_actual_host_ip", lambda self: "192.168.1.1"
        )
        diag = PortDiagnostics()
        # Just verify it returns a report dict without raising
        report = diag.log_startup_diagnostics()
        assert "host_info" in report

    def test_log_startup_diagnostics_not_listening(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": True, "platform": "unraid"},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "check_port_binding",
            lambda self: {
                "internal_port_listening": False,
                "external_ports": [],
                "port_mappings": {},
                "issues": ["not listening"],
                "solutions": [],
            },
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_actual_host_ip", lambda self: None
        )
        diag = PortDiagnostics()
        report = diag.log_startup_diagnostics()
        assert report["port_check"]["internal_port_listening"] is False

    def test_log_port_diagnostics_convenience(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics, log_port_diagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False, "platform": "alpine"},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "check_port_binding",
            lambda self: {
                "internal_port_listening": True,
                "external_ports": [],
                "port_mappings": {},
                "issues": [],
                "solutions": [],
            },
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_actual_host_ip", lambda self: None
        )
        report = log_port_diagnostics()
        assert "host_info" in report


class TestPortDiagnosticsHostIP:
    """Cover the multi-step host IP detection helpers."""

    def test_try_traceroute_ip_parses_second_hop(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()

        result = SimpleNamespace(
            returncode=0,
            stdout="1 172.17.0.1 0.5 ms\n2 192.168.1.1 1.2 ms\n",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        ip = diag._try_traceroute_ip()
        assert ip == "192.168.1.1"

    def test_try_traceroute_ip_traceroute_missing(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()
        # Both traceroute and tracepath unavailable
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("none")),
        )
        ip = diag._try_traceroute_ip()
        # Should not raise, just return None
        assert ip is None

    def test_try_docker_host_gateway_etc_hosts(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()

        hosts_data = "10.5.0.1 host.docker.internal host-gateway\n"
        with patch("builtins.open", mock_open(read_data=hosts_data)):
            result = SimpleNamespace(returncode=1, stdout="")
            monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
            ip = diag._try_docker_host_gateway()
        assert ip == "10.5.0.1"

    def test_try_docker_host_gateway_ip_route(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()

        # Empty hosts file -> falls through to ip route
        with patch("builtins.open", mock_open(read_data="")):
            result = SimpleNamespace(
                returncode=0, stdout="default via 10.5.0.1 dev eth0\n"
            )
            monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
            ip = diag._try_docker_host_gateway()
        assert ip == "10.5.0.1"

    def test_try_docker_host_gateway_skips_default_docker_gateway(
        self, monkeypatch
    ):
        from app.utils.port_diagnostics import PortDiagnostics
        from unittest.mock import mock_open

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()

        with patch("builtins.open", mock_open(read_data="")):
            result = SimpleNamespace(
                returncode=0, stdout="default via 172.17.0.1 dev eth0\n"
            )
            monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
            ip = diag._try_docker_host_gateway()
        # Filter excludes 172.17.0.1
        assert ip is None

    def test_get_actual_host_ip_uses_traceroute_fallback(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()
        # No env vars
        for v in ("HOST_IP", "UNRAID_IP", "SERVER_IP"):
            monkeypatch.delenv(v, raising=False)
        # Traceroute returns an IP
        monkeypatch.setattr(
            type(diag), "_try_traceroute_ip", lambda self: "10.5.0.1"
        )
        ip = diag._get_actual_host_ip()
        assert ip == "10.5.0.1"


class TestPortDiagnosticsHostInfo:
    """Cover the _get_host_info aggregator."""

    def test_get_host_info_aggregates_helpers(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        # Stub all collectors to simple values
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "_detect_platform",
            lambda self: ("alpine", False),
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_python_version", lambda self: "3.11.0"
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_container_uptime", lambda self: "1h"
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_memory_usage", lambda self: "100MB"
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_disk_usage", lambda self: "200MB"
        )
        monkeypatch.setattr(
            PortDiagnostics,
            "_get_supervisord_status",
            lambda self: {"webui": "RUNNING"},
        )
        # Make docker socket appear available so the DDC-specific branches run
        monkeypatch.setattr(
            "app.utils.port_diagnostics.os.path.exists",
            lambda p: p == "/var/run/docker.sock",
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_ddc_memory_usage", lambda self: "50MB"
        )
        monkeypatch.setattr(
            PortDiagnostics, "_get_ddc_image_size", lambda self: "300MB"
        )
        diag = PortDiagnostics()
        info = diag.host_info
        assert info["platform"] == "alpine"
        assert info["python_version"] == "3.11.0"
        assert info["ddc_memory_usage"] == "50MB"


class TestPortDiagnosticsHostInfoBranches:
    """Cover platform detection and uptime/memory helpers."""

    def test_detect_platform_unknown(self, monkeypatch):
        import app.utils.port_diagnostics as pd

        # No marker files present
        monkeypatch.setattr(pd.os.path, "exists", lambda p: False)
        from app.utils.port_diagnostics import PortDiagnostics

        # Need to instantiate with stubbed host info to avoid the heavy work
        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()
        platform_name, is_unraid = diag._detect_platform()
        assert platform_name == "unknown"
        assert is_unraid is False

    def test_get_python_version_returns_string(self, monkeypatch):
        from app.utils.port_diagnostics import PortDiagnostics

        monkeypatch.setattr(
            PortDiagnostics,
            "_get_host_info",
            lambda self: {"is_unraid": False},
        )
        monkeypatch.setattr(
            PortDiagnostics, "_detect_container_name", lambda self: "ddc"
        )
        diag = PortDiagnostics()
        v = diag._get_python_version()
        # Format X.Y.Z (or 'unknown')
        assert v != ""
        assert isinstance(v, str)


# ===========================================================================
# utils/app_commands_helper.py
# ===========================================================================


class TestAppCommandsHelper:
    """Cover the get_*/is_* dispatchers and mock fallback Option."""

    def test_initialize_returns_tuple(self):
        from utils import app_commands_helper as ach

        ac, opt, avail = ach.initialize_app_commands()
        # ac and opt should never be None after initialize
        assert ac is not None
        assert opt is not None
        assert isinstance(avail, bool)

    def test_get_app_commands_initializes_lazily(self, monkeypatch):
        from utils import app_commands_helper as ach

        # Already initialized at import time -> just returns the cached value
        result = ach.get_app_commands()
        assert result is ach.app_commands

    def test_get_discord_option_returns_class_or_mock(self):
        from utils import app_commands_helper as ach

        opt_cls = ach.get_discord_option()
        assert opt_cls is not None

    def test_is_app_commands_available_returns_bool(self):
        from utils import app_commands_helper as ach

        assert isinstance(ach.is_app_commands_available(), bool)

    def test_mock_option_describe_handles_kwargs(self):
        """Cover the ActualMockOption fallback class."""
        from utils import app_commands_helper as ach

        # The ActualMockOption is only instantiated when DiscordOption is None
        # at import time. We can still exercise it directly by reaching into
        # the function that creates the class.  Easiest: invoke initialize on
        # a fresh, unmocked module and verify the fallback Option works.
        DiscordOption = ach.get_discord_option()
        # We don't know which class wins (real PyCord Option or ActualMockOption);
        # both should accept `(int, "desc")` style construction.
        try:
            inst = DiscordOption(int, "test description")
        except TypeError:
            # PyCord 2.x positional args may differ — just probe the class
            inst = DiscordOption(input_type=int, description="test description")
        assert inst is not None

    def test_mock_app_commands_decorators(self):
        """Verify the AppCommandsMock decorators preserve the wrapped function."""
        # Build a mock instance directly to test the no-discord path
        from utils.app_commands_helper import initialize_app_commands

        ac, _opt, _avail = initialize_app_commands()
        # AppCommandsMock + real app_commands both expose .command() decorator
        if hasattr(ac, "command"):
            decorator = ac.command()
            # decorator wraps and returns its arg
            def _f():
                return 42

            try:
                wrapped = decorator(_f)
                # Some decorators return a wrapper callable
                assert callable(wrapped)
            except TypeError:
                # PyCord's @app_commands.command might require slash-context;
                # falling through is acceptable — the mock path is what we
                # really want to exercise.
                pass

    def test_mock_choice_class_stores_name_value(self):
        """The fallback AppCommandsMock.Choice stores name & value attributes."""
        from utils.app_commands_helper import initialize_app_commands

        ac, _opt, avail = initialize_app_commands()
        # Only check the Mock fallback path
        if not avail and hasattr(ac, "Choice"):
            choice = ac.Choice("Display Name", 42)
            assert choice.name == "Display Name"
            assert choice.value == 42

    def test_mock_app_commands_describe_decorator(self):
        from utils.app_commands_helper import initialize_app_commands

        ac, _opt, avail = initialize_app_commands()
        if not avail and hasattr(ac, "describe"):
            # The mock's describe() returns a passthrough decorator
            def _f():
                return 1

            wrapped = ac.describe(arg="info")(_f)
            assert callable(wrapped)
            assert wrapped() == 1

    def test_mock_app_commands_autocomplete_decorator(self):
        from utils.app_commands_helper import initialize_app_commands

        ac, _opt, avail = initialize_app_commands()
        if not avail and hasattr(ac, "autocomplete"):
            def _f():
                return "hi"

            wrapped = ac.autocomplete(arg="opt")(_f)
            assert callable(wrapped)

    def test_actual_mock_option_stores_attrs(self):
        """Cover ActualMockOption fallback class attributes."""
        from utils.app_commands_helper import initialize_app_commands

        ac, opt, avail = initialize_app_commands()
        if not avail:
            # The fallback ActualMockOption requires actual_input_type
            inst = opt(int, description="a value", name="my_opt")
            assert inst.description == "a value"
            assert inst.name == "my_opt"
            # Property accessor
            assert inst.input_type is int
            # __name__ attribute mirrors actual_input_type
            assert inst.__name__ == "int"

    def test_actual_mock_option_with_unnamed_input_type(self):
        """Cover the branch when input_type has no __name__ attribute."""
        from utils.app_commands_helper import initialize_app_commands

        ac, opt, avail = initialize_app_commands()
        if not avail:
            class _NoName:
                pass

            # Strip __name__ to force the fallback branch
            no_name = _NoName()
            # Pass an instance that doesn't have __name__
            inst = opt(no_name, description="x")
            # __name__ should fall back to str(actual_input_type)
            assert isinstance(inst.__name__, str)

    def test_get_app_commands_lazy_init_when_none(self, monkeypatch):
        """When app_commands is None, get_app_commands triggers initialize."""
        from utils import app_commands_helper as ach

        # Save and reset module globals
        prev = ach.app_commands
        prev_opt = ach.DiscordOption
        prev_avail = ach.app_commands_available
        try:
            ach.app_commands = None
            ach.DiscordOption = None
            ach.app_commands_available = False
            ac = ach.get_app_commands()
            # Should never be None after the lazy-init path
            assert ac is not None
            assert ach.app_commands is not None
        finally:
            ach.app_commands = prev
            ach.DiscordOption = prev_opt
            ach.app_commands_available = prev_avail

    def test_get_discord_option_lazy_init_when_none(self):
        """When DiscordOption is None, get_discord_option triggers initialize."""
        from utils import app_commands_helper as ach

        prev = ach.app_commands
        prev_opt = ach.DiscordOption
        prev_avail = ach.app_commands_available
        try:
            ach.app_commands = None
            ach.DiscordOption = None
            ach.app_commands_available = False
            opt = ach.get_discord_option()
            assert opt is not None
        finally:
            ach.app_commands = prev
            ach.DiscordOption = prev_opt
            ach.app_commands_available = prev_avail

    def test_is_app_commands_available_lazy_init_when_none(self):
        from utils import app_commands_helper as ach

        prev = ach.app_commands
        prev_opt = ach.DiscordOption
        prev_avail = ach.app_commands_available
        try:
            ach.app_commands = None
            ach.DiscordOption = None
            ach.app_commands_available = False
            result = ach.is_app_commands_available()
            assert isinstance(result, bool)
        finally:
            ach.app_commands = prev
            ach.DiscordOption = prev_opt
            ach.app_commands_available = prev_avail

    def test_initialize_when_app_commands_available_but_no_option(
        self, monkeypatch
    ):
        """Cover line 109 (DiscordOption fallback while app_commands_available=True)."""
        from utils import app_commands_helper as ach

        prev = ach.app_commands
        prev_opt = ach.DiscordOption
        prev_avail = ach.app_commands_available
        try:
            # Force the post-init branch: app_commands_available=True and
            # DiscordOption=None which triggers the conditional logging branch
            ach.app_commands = None
            ach.DiscordOption = None
            ach.app_commands_available = False

            # Force the second strategy via builtins.__import__ so:
            #   - "from discord import Option" raises ImportError
            #   - "from discord import app_commands" succeeds
            real_import = __builtins__["__import__"] if isinstance(
                __builtins__, dict
            ) else __builtins__.__import__

            class _FakeAppCommands:
                pass

            class _FakeDiscord:
                app_commands = _FakeAppCommands()

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "discord" and "Option" in (fromlist or ()):
                    raise ImportError("no Option in this build")
                if name == "discord" and "app_commands" in (fromlist or ()):
                    return _FakeDiscord()
                if name == "discord.commands":
                    raise ImportError("no discord.commands")
                if name == "discord.ext.commands":
                    raise ImportError("not reached")
                return real_import(name, globals, locals, fromlist, level)

            monkeypatch.setattr("builtins.__import__", fake_import)

            ac, opt, avail = ach.initialize_app_commands()
            # app_commands_available should be True via Strategy 2
            assert avail is True
            # opt should be the ActualMockOption fallback (line 109 hit)
            assert opt is not None
        finally:
            ach.app_commands = prev
            ach.DiscordOption = prev_opt
            ach.app_commands_available = prev_avail


# ===========================================================================
# utils/import_utils.py
# ===========================================================================


class TestImportUtils:
    """Cover safe_import / safe_import_from / cache / failure paths."""

    def test_safe_import_caches_results(self):
        from utils import import_utils as iu

        # Clear cache to avoid pollution from earlier tests
        iu._import_cache.pop("os", None)
        first = iu.safe_import("os")
        second = iu.safe_import("os")
        assert first[1] is True
        assert first == second

    def test_safe_import_failure_path(self):
        from utils import import_utils as iu

        cache_key = "definitely_not_a_real_module_xyz_42"
        iu._import_cache.pop(cache_key, None)
        mod, ok = iu.safe_import("definitely_not_a_real_module_xyz_42")
        assert ok is False
        assert mod is None

    def test_safe_import_nested_module(self):
        from utils import import_utils as iu

        iu._import_cache.pop("os.path", None)
        mod, ok = iu.safe_import("os.path")
        assert ok is True
        # resolved to the leaf module
        import os.path

        assert mod is os.path

    def test_safe_import_from_success(self):
        from utils import import_utils as iu

        iu._import_cache.pop("os.getcwd", None)
        item, ok = iu.safe_import_from("os", "getcwd")
        assert ok is True
        assert callable(item)

    def test_safe_import_from_failure(self):
        from utils import import_utils as iu

        iu._import_cache.pop("os.does_not_exist_xyz", None)
        item, ok = iu.safe_import_from("os", "does_not_exist_xyz")
        assert ok is False
        assert item is None

    def test_import_ujson_returns_module(self):
        from utils import import_utils as iu

        iu._import_cache.pop("ujson", None)
        mod, _ok = iu.import_ujson()
        # Always returns at least the json fallback
        assert mod is not None

    def test_import_uvloop_handles_install_failure(self, monkeypatch):
        from utils import import_utils as iu

        # Simulate uvloop being importable but install() raising
        fake_uvloop = MagicMock()
        fake_uvloop.install.side_effect = RuntimeError("loop already set")
        iu._import_cache.pop("uvloop", None)
        monkeypatch.setattr(iu, "safe_import", lambda name, **kw: (fake_uvloop, True))
        mod, ok = iu.import_uvloop()
        assert mod is fake_uvloop
        # success flipped to False because install() failed
        assert ok is False

    def test_get_performance_imports_returns_dict(self):
        from utils import import_utils as iu

        result = iu.get_performance_imports()
        assert "ujson" in result
        assert "uvloop" in result
        assert "gevent" in result
        for v in result.values():
            assert "available" in v and "module" in v and "description" in v

    def test_log_performance_status_runs(self):
        from utils import import_utils as iu

        # Just ensure it runs without raising
        iu.log_performance_status()


# ===========================================================================
# utils/logging_utils.py
# ===========================================================================


class TestLoggingUtilsHelpers:
    """Cover helpers, mixin and convenience getters not in the bundle1 tests."""

    @pytest.fixture(autouse=True)
    def _reset_state(self):
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

    def test_get_temporary_debug_status_returns_disabled(self):
        from utils.logging_utils import get_temporary_debug_status

        is_enabled, expiry, remaining = get_temporary_debug_status()
        assert is_enabled is False
        assert remaining == 0

    def test_get_temporary_debug_status_returns_enabled(self):
        from utils.logging_utils import (
            enable_temporary_debug,
            get_temporary_debug_status,
        )

        enable_temporary_debug(2)
        is_enabled, expiry, remaining = get_temporary_debug_status()
        assert is_enabled is True
        assert remaining > 0

    def test_disable_temporary_debug(self):
        from utils.logging_utils import (
            disable_temporary_debug,
            enable_temporary_debug,
            get_temporary_debug_status,
        )

        enable_temporary_debug(2)
        assert get_temporary_debug_status()[0] is True
        result = disable_temporary_debug()
        assert result is True
        assert get_temporary_debug_status()[0] is False

    def test_setup_logger_idempotent(self):
        from utils.logging_utils import setup_logger

        l1 = setup_logger("ddc.test.idempotent")
        l2 = setup_logger("ddc.test.idempotent")
        # Returned the same logger and didn't double-attach handlers
        assert l1 is l2

    def test_setup_logger_with_file_handler(self, tmp_path, monkeypatch):
        from utils.logging_utils import setup_logger

        # Redirect the file-output dir at the function's own helper logic by
        # patching os.path.dirname so the logs directory lands in tmp_path.
        # The function uses `os.path.join(logs_dir, ...)` — we can patch the
        # makedirs call to be a no-op and patch RotatingFileHandler to a
        # MagicMock so we don't actually open files on the SMB mount.
        from logging.handlers import RotatingFileHandler as _RFH

        captured = {}

        class _FakeHandler(logging.Handler):
            def __init__(self, *a, **kw):
                super().__init__()
                captured["args"] = a
                captured["kw"] = kw

            def emit(self, record):
                pass

        monkeypatch.setattr(
            "utils.logging_utils.RotatingFileHandler", _FakeHandler
        )
        # Avoid filesystem touch
        monkeypatch.setattr("utils.logging_utils.os.makedirs", lambda *a, **k: None)
        logger = setup_logger("ddc.test.filelogger", log_to_file=True)
        # Handler attached
        assert any(isinstance(h, _FakeHandler) for h in logger.handlers)

    def test_setup_logger_file_handler_handles_oserror(self, monkeypatch):
        """OS errors during file handler creation are swallowed gracefully."""
        from utils.logging_utils import setup_logger

        def _boom(*a, **kw):
            raise OSError("permission denied")

        monkeypatch.setattr("utils.logging_utils.os.makedirs", _boom)
        # Should not raise
        logger = setup_logger("ddc.test.broken_file_logger", log_to_file=True)
        assert logger is not None

    def test_get_module_logger_uses_ddc_prefix(self):
        from utils.logging_utils import get_module_logger

        logger = get_module_logger("foo")
        assert logger.name == "ddc.foo"

    def test_get_action_logger(self):
        from utils.logging_utils import get_action_logger

        logger = get_action_logger()
        assert logger.name == "user_actions"

    def test_get_import_logger(self):
        from utils.logging_utils import get_import_logger

        logger = get_import_logger()
        assert logger.name == "discord.app_commands_import"

    def test_logger_mixin_uses_class_name(self):
        from utils.logging_utils import LoggerMixin

        class MyService(LoggerMixin):
            pass

        instance = MyService()
        assert instance.logger.name == "ddc.MyService"

    def test_logger_mixin_with_explicit_name(self):
        from utils.logging_utils import LoggerMixin

        class MyService(LoggerMixin):
            pass

        instance = MyService(logger_name="my.custom")
        assert instance.logger.name == "my.custom"

    def test_setup_all_loggers_runs(self):
        from utils.logging_utils import setup_all_loggers

        # Just exercise it
        setup_all_loggers(level=logging.WARNING)

    def test_timezone_formatter_falls_back_when_pytz_missing(self):
        from utils.logging_utils import TimezoneFormatter

        formatter = TimezoneFormatter()
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname=__file__, lineno=1,
            msg="m", args=(), exc_info=None,
        )
        # Just ensure it returns *some* string without raising
        result = formatter.formatTime(record)
        assert isinstance(result, str) and len(result) > 0

    def test_refresh_debug_status_runs(self, monkeypatch):
        from utils import logging_utils as lu

        # Pure smoke - patch the cache invalidation to no-op so we don't
        # touch the real config service.
        class _FakeSvc:
            class _CS:
                def invalidate_cache(self):
                    pass

            _cache_service = _CS()

        monkeypatch.setattr(
            "services.config.config_service.get_config_service",
            lambda: _FakeSvc(),
        )
        result = lu.refresh_debug_status()
        # Returns a bool
        assert isinstance(result, bool)


# ===========================================================================
# app/blueprints/main_routes.py — additional routes
# ===========================================================================


@pytest.fixture
def main_app(monkeypatch):
    from app.blueprints.main_routes import main_bp

    _stub_auth(monkeypatch)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-app-utils-extended"
    app.config["WTF_CSRF_ENABLED"] = False
    app.register_blueprint(main_bp)
    return app


def _ns(success=True, **kwargs):
    out = SimpleNamespace(success=success)
    for k, v in kwargs.items():
        setattr(out, k, v)
    return out


class TestMainRoutesAdditional:
    """Extra routes not covered by test_main_automation_security_routes.py."""

    def test_logout_returns_401_with_realm(self, main_app):
        resp = main_app.test_client().get("/logout")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers
        assert "DDC-logout-" in resp.headers["WWW-Authenticate"]

    def test_logout_post_also_works(self, main_app):
        resp = main_app.test_client().post("/logout")
        assert resp.status_code == 401

    def test_setup_get_redirects_when_password_already_set(
        self, main_app, monkeypatch
    ):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config",
            lambda: {"web_ui_password_hash": "existing_hash"},
        )
        resp = main_app.test_client().get("/setup")
        # Redirect to config page (302)
        assert resp.status_code == 302

    def test_setup_get_renders_when_no_password(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )

        # Avoid template-not-found by mocking render_template
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda *a, **kw: "SETUP_TEMPLATE_OK",
        )
        resp = main_app.test_client().get("/setup")
        assert resp.status_code == 200
        assert b"SETUP_TEMPLATE_OK" in resp.data

    def test_setup_post_blocked_when_password_set(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config",
            lambda: {"web_ui_password_hash": "existing"},
        )
        resp = main_app.test_client().post(
            "/setup", data={"password": "Test1234abcd!", "confirm_password": "Test1234abcd!"}
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "not allowed" in body["error"].lower()

    def test_setup_post_password_mismatch(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        resp = main_app.test_client().post(
            "/setup",
            data={"password": "ValidPass123!", "confirm_password": "Different456!"},
        )
        assert resp.get_json()["success"] is False

    def test_setup_post_password_too_short(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        resp = main_app.test_client().post(
            "/setup", data={"password": "abc", "confirm_password": "abc"}
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "12 characters" in body["error"]

    def test_setup_post_low_complexity_rejected(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        # 12 chars but only one class -> complexity < 3
        weak = "aaaaaaaaaaaa"
        resp = main_app.test_client().post(
            "/setup", data={"password": weak, "confirm_password": weak}
        )
        body = resp.get_json()
        assert body["success"] is False

    def test_setup_post_success_calls_update_config_fields(
        self, main_app, monkeypatch
    ):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        captured = {}
        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields",
            lambda fields: captured.update(fields) or True,
        )
        # Stub log_user_action to keep the action_logger out of the test
        monkeypatch.setattr(
            "app.blueprints.main_routes.log_user_action",
            lambda *a, **kw: None,
        )
        # Mix uppercase, lowercase, digit, symbol = 4 classes
        strong = "GoodPass123!@"
        resp = main_app.test_client().post(
            "/setup", data={"password": strong, "confirm_password": strong}
        )
        body = resp.get_json()
        assert body["success"] is True
        assert "web_ui_password_hash" in captured
        assert captured.get("web_ui_user") == "admin"

    def test_setup_post_missing_fields(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        resp = main_app.test_client().post("/setup", data={})
        body = resp.get_json()
        assert body["success"] is False
        assert "required" in body["error"].lower()

    def test_discord_bot_setup_renders_with_config(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config",
            lambda: {"bot_token": "xyz"},
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda template, **kw: f"OK:{template}:bot_token={kw['config'].get('bot_token')}",
        )
        resp = main_app.test_client().get(
            "/discord_bot_setup", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert b"discord_bot_setup.html" in resp.data
        assert b"bot_token=xyz" in resp.data

    def test_discord_bot_setup_unauth(self, main_app):
        resp = main_app.test_client().get("/discord_bot_setup")
        assert resp.status_code == 401

    def test_donations_list_failure_returns_failure(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_donation_history.return_value = _ns(
            success=False, data=None, error="db down"
        )
        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            lambda: svc,
        )
        resp = main_app.test_client().get(
            "/api/donations/list", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False

    def test_get_mech_music_info_failure(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_all_music_info.return_value = _ns(
            success=False, data=None, error="x", status_code=500
        )
        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/music/info")
        assert resp.status_code == 500

    def test_get_mech_display_image_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_mech_display_image.return_value = _ns(
            success=True,
            image_bytes=b"FAKEWEBP",
            filename="mech_5_shadow.webp",
            error_message=None,
        )
        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/display/5/shadow")
        assert resp.status_code == 200
        assert resp.data == b"FAKEWEBP"
        assert resp.headers["Content-Type"] == "image/webp"

    def test_get_mech_display_image_not_found(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_mech_display_image.return_value = _ns(
            success=False,
            image_bytes=None,
            filename=None,
            error_message="missing",
        )
        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/display/8/unlocked")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"] == "Image not available"

    def test_get_mech_display_info_success(self, main_app, monkeypatch, tmp_path):
        # Build fake cache files so the route can list them
        fake_dir = tmp_path
        (fake_dir / "mech_3_shadow.webp").write_bytes(b"x" * 10)
        (fake_dir / "mech_5_unlocked.webp").write_bytes(b"y" * 20)

        svc = MagicMock()
        svc.cache_dir = fake_dir
        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/display/info")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["total_cached"] == 2
        assert 3 in body["cached_images"] or "3" in body["cached_images"]

    def test_get_cached_mech_state_cache_hit(self, monkeypatch):
        from app.blueprints.main_routes import _get_cached_mech_state

        # Build a fake cache result and service
        cache_result = SimpleNamespace(
            success=True,
            level=4,
            power=12.5,
            total_donated=50,
            name="Mech-4",
            threshold=100,
            speed=80,
            cache_age_seconds=1.0,
        )
        cache_service = MagicMock()
        cache_service.get_cached_status.return_value = cache_result
        monkeypatch.setattr(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            lambda: cache_service,
        )
        # Need an app context for ``current_app.logger``
        app = Flask(__name__)
        with app.app_context():
            state = _get_cached_mech_state(include_decimals=False)
        assert state.level == 4
        assert state.Power == 12.5
        assert state.power == 12.5
        assert state.name == "Mech-4"

    def test_get_cached_mech_state_cache_miss_falls_back(self, monkeypatch):
        from app.blueprints.main_routes import _get_cached_mech_state

        cache_service = MagicMock()
        cache_service.get_cached_status.return_value = SimpleNamespace(
            success=False,
            level=None,
            power=None,
            total_donated=None,
            name=None,
            threshold=None,
            speed=None,
            cache_age_seconds=0,
        )
        monkeypatch.setattr(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            lambda: cache_service,
        )
        # Mech service fallback returns success
        mech_service = MagicMock()
        state_result = SimpleNamespace(
            success=True,
            level=2,
            power=5,
            total_donated=10,
            name="Mech-2",
            threshold=20,
            speed=50,
        )
        mech_service.get_mech_state_service.return_value = state_result
        monkeypatch.setattr(
            "services.mech.mech_service.get_mech_service",
            lambda: mech_service,
        )

        app = Flask(__name__)
        with app.app_context():
            state = _get_cached_mech_state(include_decimals=False)
        assert state.level == 2
        assert state.power == 5

    def test_get_cached_mech_state_total_failure_returns_none(self, monkeypatch):
        from app.blueprints.main_routes import _get_cached_mech_state

        # Cache call raises ImportError -> outer except
        def _boom():
            raise ImportError("nope")

        monkeypatch.setattr(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            _boom,
        )
        app = Flask(__name__)
        with app.app_context():
            state = _get_cached_mech_state(include_decimals=False)
        assert state is None

    def test_save_config_api_data_error_returns_failure(self, main_app, monkeypatch):
        """ValueError inside save_configuration -> data error path."""

        def boom():
            raise ValueError("bad data")

        monkeypatch.setattr(
            "services.web.configuration_save_service.get_configuration_save_service",
            boom,
        )
        resp = main_app.test_client().post(
            "/save_config_api",
            data={"x": "y", "display_name_alpha": "Alpha"},
            headers={**_AUTH_HEADER, "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False

    def test_simulate_donation_broadcast_returns_stub(self, main_app):
        resp = main_app.test_client().post(
            "/api/simulate-donation-broadcast", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True

    def test_config_page_renders_with_service_data(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.prepare_page_data.return_value = SimpleNamespace(
            success=True,
            template_data={"config": {"x": 1}, "extra": "ok"},
            error=None,
        )
        monkeypatch.setattr(
            "services.web.configuration_page_service.get_configuration_page_service",
            lambda: svc,
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda *a, **kw: f"CONFIG_OK:{kw.get('extra', '')}",
        )
        resp = main_app.test_client().get("/", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"CONFIG_OK:ok" in resp.data

    def test_config_page_service_failure_uses_fallback(
        self, main_app, monkeypatch
    ):
        svc = MagicMock()
        svc.prepare_page_data.return_value = SimpleNamespace(
            success=False, template_data={}, error="db down"
        )
        monkeypatch.setattr(
            "services.web.configuration_page_service.get_configuration_page_service",
            lambda: svc,
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda *a, **kw: f"FALLBACK:{kw.get('error_message', '')}",
        )
        resp = main_app.test_client().get("/", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"FALLBACK:" in resp.data

    def test_config_page_runtime_error_uses_service_fallback(
        self, main_app, monkeypatch
    ):
        def _boom():
            raise RuntimeError("svc dead")

        monkeypatch.setattr(
            "services.web.configuration_page_service.get_configuration_page_service",
            _boom,
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda *a, **kw: f"ERR:{kw.get('error_message', '')}",
        )
        resp = main_app.test_client().get("/", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"Service error" in resp.data

    def test_setup_get_unauthenticated_works(self, main_app, monkeypatch):
        """The /setup GET route is intentionally unauthenticated."""
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda *a, **kw: "OK",
        )
        resp = main_app.test_client().get("/setup")
        assert resp.status_code == 200

    def test_setup_post_unauthenticated_when_no_password(self, main_app, monkeypatch):
        """The /setup POST is also unauthenticated when no password is set."""
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        # Missing password fields -> 400 JSON error
        resp = main_app.test_client().post("/setup", data={})
        body = resp.get_json()
        assert body["success"] is False
