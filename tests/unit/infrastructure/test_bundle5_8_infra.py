# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Bundle 5/8 Infrastructure Tests                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for Bundle 5/8 hardening: CSRF foundation, Docker infra, requirements
upper-bounds and scheduler hosted/standalone modes.

These tests assert the infrastructure-level invariants — they do not exercise
the runtime UI flow.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml
from flask import Blueprint, Flask


PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = PROJECT_ROOT / "docker-compose.yml"
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile"
REQ_PROD_PATH = PROJECT_ROOT / "requirements.prod.txt"
REQ_TEST_PATH = PROJECT_ROOT / "requirements-test.txt"
CSRF_MODULE_PATH = PROJECT_ROOT / "app" / "web" / "csrf.py"
AUDIT_PATH = PROJECT_ROOT / "AUDIT.md"
BASE_TEMPLATE_PATH = PROJECT_ROOT / "app" / "templates" / "_base.html"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _make_app_with_blueprints(blueprint_count: int = 2) -> Flask:
    """Build a tiny Flask app with N dummy blueprints registered."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-for-csrf"
    for i in range(blueprint_count):
        bp = Blueprint(f"dummy_bp_{i}", __name__, url_prefix=f"/bp{i}")

        @bp.route("/")
        def _index():  # pragma: no cover - never called
            return "ok"

        app.register_blueprint(bp)
    return app


def _read_compose() -> dict:
    with COMPOSE_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has_upper_bound(specifier: str) -> bool:
    """Return True if a PEP 508 specifier string contains an upper bound."""
    # The simplest robust check: an upper bound uses '<' (or '<=') somewhere.
    return "<" in specifier


def _parse_prod_requirements() -> dict[str, str]:
    """Map package name -> raw specifier from requirements.prod.txt."""
    result: dict[str, str] = {}
    text = _read_text(REQ_PROD_PATH)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments after the specifier.
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        # Strip environment markers like "; python_version >= '3.13'"
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        if not line:
            continue
        # Match name and the rest as specifier.
        match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
        if not match:
            continue
        name, spec = match.group(1), match.group(2).strip()
        result[name.lower()] = spec
    return result


# ============================================================================
# 1. CSRF-Foundation (Bundle 8b / S1)
# ============================================================================
class TestCsrfFoundation:
    """Tests for ``app.web.csrf.install_csrf_protection``."""

    def test_installs_extension_when_flask_wtf_available(self):
        """When flask_wtf is installed, csrf protection is initialized."""
        pytest.importorskip("flask_wtf")
        from app.web.csrf import install_csrf_protection

        app = _make_app_with_blueprints(2)
        install_csrf_protection(app)

        assert "ddc_csrf" in app.extensions, (
            "ddc_csrf extension should be registered when Flask-WTF is installed"
        )
        assert "csrf_token" in app.jinja_env.globals, (
            "csrf_token should be a Jinja global"
        )

    def test_csrf_token_global_is_callable(self):
        """csrf_token Jinja global must be callable."""
        pytest.importorskip("flask_wtf")
        from app.web.csrf import install_csrf_protection

        app = _make_app_with_blueprints(1)
        install_csrf_protection(app)

        token_helper = app.jinja_env.globals["csrf_token"]
        assert callable(token_helper)

    def test_blueprints_are_exempted(self):
        """Every registered blueprint should be exempted via csrf.exempt."""
        pytest.importorskip("flask_wtf")
        from app.web import csrf as csrf_module

        app = _make_app_with_blueprints(3)
        # Patch CSRFProtect class so we can observe exempt() calls without
        # interfering with Flask-WTF's real behavior.
        fake_csrf = MagicMock()
        fake_csrf_class = MagicMock(return_value=fake_csrf)

        with patch.object(csrf_module, "__name__", csrf_module.__name__):
            with patch.dict(
                sys.modules,
                {
                    "flask_wtf.csrf": MagicMock(
                        CSRFProtect=fake_csrf_class,
                        generate_csrf=lambda: "fake-token",
                    ),
                },
            ):
                # Force re-import of the inner from-import.
                csrf_module.install_csrf_protection(app)

        assert fake_csrf.exempt.call_count == 3, (
            f"Expected 3 exempt() calls (one per blueprint), got "
            f"{fake_csrf.exempt.call_count}"
        )

    def test_fallback_when_flask_wtf_missing(self):
        """If flask_wtf is missing, csrf_token returns '' and no crash."""
        from app.web import csrf as csrf_module

        app = _make_app_with_blueprints(1)

        # Block the import.
        original_modules = {
            k: v for k, v in sys.modules.items()
            if k == "flask_wtf" or k.startswith("flask_wtf.")
        }
        try:
            for name in list(sys.modules):
                if name == "flask_wtf" or name.startswith("flask_wtf."):
                    del sys.modules[name]

            class _Blocker:
                def find_module(self, fullname, path=None):
                    if fullname == "flask_wtf" or fullname.startswith("flask_wtf."):
                        return self
                    return None

                def load_module(self, fullname):
                    raise ImportError(f"blocked for test: {fullname}")

                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "flask_wtf" or fullname.startswith("flask_wtf."):
                        raise ImportError(f"blocked for test: {fullname}")
                    return None

            blocker = _Blocker()
            sys.meta_path.insert(0, blocker)
            try:
                # Should not raise, even without flask_wtf available.
                csrf_module.install_csrf_protection(app)
            finally:
                sys.meta_path.remove(blocker)
        finally:
            sys.modules.update(original_modules)

        token_helper = app.jinja_env.globals.get("csrf_token")
        assert token_helper is not None, "csrf_token fallback must be registered"
        assert callable(token_helper)
        assert token_helper() == "", (
            "Fallback csrf_token() must return empty string"
        )

    def test_no_crash_with_zero_blueprints(self):
        """install_csrf_protection should handle apps with no blueprints."""
        pytest.importorskip("flask_wtf")
        from app.web.csrf import install_csrf_protection

        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test-secret"
        # Should not raise even with no blueprints.
        install_csrf_protection(app)
        assert "csrf_token" in app.jinja_env.globals


# ============================================================================
# 2. Docker-Compose YAML Validation (Bundle 3 + 5)
# ============================================================================
class TestDockerComposeHardening:
    """Validate hardening fields in docker-compose.yml."""

    def test_compose_file_exists(self):
        assert COMPOSE_PATH.exists(), f"Missing compose file: {COMPOSE_PATH}"

    def test_compose_security_opt_no_new_privileges(self):
        d = _read_compose()
        sec_opts = d["services"]["ddc"].get("security_opt", [])
        assert "no-new-privileges:true" in sec_opts, (
            f"Expected 'no-new-privileges:true' in security_opt, got {sec_opts}"
        )

    def test_compose_pids_limit(self):
        d = _read_compose()
        limits = (
            d["services"]["ddc"]
            .get("deploy", {})
            .get("resources", {})
            .get("limits", {})
        )
        # YAML may parse as int or string.
        assert int(limits.get("pids", 0)) == 256, (
            f"Expected pids: 256, got {limits.get('pids')!r}"
        )

    def test_compose_restart_policy(self):
        d = _read_compose()
        assert d["services"]["ddc"].get("restart") == "unless-stopped"

    def test_compose_healthcheck_uses_python_urllib(self):
        d = _read_compose()
        hc = d["services"]["ddc"].get("healthcheck")
        assert hc is not None, "healthcheck section missing"
        test_cmd = hc.get("test")
        assert test_cmd is not None
        # Healthcheck command should reference urllib.
        flat = " ".join(map(str, test_cmd)) if isinstance(test_cmd, list) else str(test_cmd)
        assert "urllib" in flat, f"Healthcheck missing urllib check: {flat}"
        assert "python" in flat.lower()

    def test_compose_logging_driver_json_file_with_rotation(self):
        d = _read_compose()
        logging_cfg = d["services"]["ddc"].get("logging", {})
        assert logging_cfg.get("driver") == "json-file", (
            f"Expected json-file driver, got {logging_cfg.get('driver')!r}"
        )
        opts = logging_cfg.get("options", {})
        assert str(opts.get("max-size")) == "10m", (
            f"Expected max-size 10m, got {opts.get('max-size')!r}"
        )
        assert str(opts.get("max-file")) == "3", (
            f"Expected max-file 3, got {opts.get('max-file')!r}"
        )


# ============================================================================
# 3. Dockerfile Alpine-Digest-Pin (Bundle 3 / S15)
# ============================================================================
class TestDockerfileDigestPin:
    """Both alpine FROM lines must pin to an immutable sha256 digest."""

    def test_dockerfile_exists(self):
        assert DOCKERFILE_PATH.exists()

    def test_all_alpine_from_lines_pinned(self):
        text = _read_text(DOCKERFILE_PATH)
        from_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("FROM ")
        ]
        assert len(from_lines) >= 2, (
            f"Expected at least 2 FROM lines (builder + runtime), got {len(from_lines)}"
        )
        unpinned = [
            line for line in from_lines
            if "alpine" in line.lower() and "@sha256:" not in line
        ]
        assert not unpinned, (
            f"All alpine FROM lines must pin a sha256 digest, found unpinned: {unpinned}"
        )

    def test_two_alpine_stages(self):
        """Sanity: builder + runtime stages both alpine."""
        text = _read_text(DOCKERFILE_PATH)
        alpine_from_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("FROM ") and "alpine" in line.lower()
        ]
        assert len(alpine_from_lines) >= 2, (
            f"Expected builder + runtime alpine stages, got {len(alpine_from_lines)}"
        )


# ============================================================================
# 4. Requirements Upper-Bounds (Bundle 8a / S9)
# ============================================================================
class TestRequirementsUpperBounds:
    """Critical >= deps must now have upper bounds; Flask-WTF must be present."""

    UPPER_BOUND_PACKAGES = [
        "werkzeug",
        "requests",
        "urllib3",
        "flask-httpauth",
        "pillow",
        "jinja2",
        "cryptography",
    ]

    def test_prod_requirements_exist(self):
        assert REQ_PROD_PATH.exists()

    @pytest.mark.parametrize("pkg", UPPER_BOUND_PACKAGES)
    def test_package_has_upper_bound(self, pkg):
        reqs = _parse_prod_requirements()
        assert pkg in reqs, f"{pkg} missing from {REQ_PROD_PATH.name}"
        spec = reqs[pkg]
        # Skip purely "==pinned" specs (treated as both lower and upper bound).
        # We expect the pkg to have a `<` upper bound when pinned via `>=...`.
        if spec.startswith(">="):
            assert _has_upper_bound(spec), (
                f"{pkg} has lower bound only ({spec!r}), expected an upper '<' bound"
            )

    def test_flask_wtf_present(self):
        reqs = _parse_prod_requirements()
        assert "flask-wtf" in reqs, "Flask-WTF must be present in requirements.prod.txt"

    def test_docker_pinned_in_prod(self):
        reqs = _parse_prod_requirements()
        assert "docker" in reqs
        assert reqs["docker"] == "==7.1.0", (
            f"Expected docker==7.1.0 in prod, got {reqs['docker']!r}"
        )

    def test_docker_pinned_in_test_requirements(self):
        assert REQ_TEST_PATH.exists()
        text = _read_text(REQ_TEST_PATH)
        # Search for the pin (allow whitespace).
        assert re.search(r"^docker==7\.1\.0\s*$", text, flags=re.MULTILINE), (
            "Expected 'docker==7.1.0' in requirements-test.txt"
        )


# ============================================================================
# 5. Scheduler Hosted vs Standalone Mode (Bundle 8 / P10b)
# ============================================================================
class TestSchedulerLifecycleModes:
    """SchedulerService must adapt between hosted (running loop) and standalone.

    The service spawns a real thread / asyncio Task whose body runs the
    actual scheduler loop. To keep the unit test deterministic and quick we
    short-circuit the inner loop body via patching — we only assert on the
    lifecycle bookkeeping that ``start()`` / ``stop()`` perform.
    """

    @staticmethod
    def _stub_runners(svc):
        """Replace the actual loop runners with no-ops.

        The conftest enables gevent monkey-patching, which makes spinning up
        a real event loop in a thread fragile. We're only validating the
        bookkeeping (``_owns_event_loop``, ``thread`` vs ``_service_task``,
        ``running``) — not the runtime behavior of ``_service_loop`` itself.
        """
        # Standalone mode entry point: do nothing inside the worker thread.
        svc._run_service = lambda: None  # type: ignore[assignment]

        # Hosted mode coroutine: yield once and exit cleanly.
        async def _supervised_noop():
            await asyncio.sleep(0)
            return None

        svc._service_loop_supervised = _supervised_noop  # type: ignore[assignment]
        return svc

    def test_standalone_mode_owns_loop_and_starts_thread(self):
        from services.scheduling.scheduler_service import SchedulerService

        svc = SchedulerService()
        self._stub_runners(svc)
        try:
            assert svc.start() is True
            # Standalone -> owns the event loop, runs in its own thread.
            assert svc._owns_event_loop is True
            assert svc.thread is not None
            assert isinstance(svc.thread, threading.Thread)
            assert svc._service_task is None, (
                "Standalone mode must not create an asyncio Task"
            )
        finally:
            svc.running = False
            if svc.thread is not None:
                svc.thread.join(timeout=2.0)

    def test_double_start_is_no_op(self):
        from services.scheduling.scheduler_service import SchedulerService

        svc = SchedulerService()
        self._stub_runners(svc)
        try:
            assert svc.start() is True
            # Stub never resets ``running`` so the early-return guard fires.
            assert svc.start() is False, (
                "Second start() while running must return False"
            )
        finally:
            svc.running = False
            if svc.thread is not None:
                svc.thread.join(timeout=2.0)

    def test_stop_returns_false_when_not_running(self):
        from services.scheduling.scheduler_service import SchedulerService

        svc = SchedulerService()
        # Never started -> stop() returns False.
        assert svc.stop() is False

    def test_standalone_stop_clears_running_flag(self):
        """stop() must clear running and join the thread (standalone mode)."""
        from services.scheduling.scheduler_service import SchedulerService

        svc = SchedulerService()
        self._stub_runners(svc)
        assert svc.start() is True
        # Stub left ``running`` True; stop() clears it and joins the thread.
        assert svc.stop() is True
        assert svc.running is False
        assert svc.thread is None

    def test_hosted_mode_uses_running_loop_and_creates_task(self):
        """When started inside a running loop, scheduler attaches to it."""
        from services.scheduling.scheduler_service import SchedulerService

        async def _full():
            svc = SchedulerService()
            self._stub_runners(svc)
            assert svc.start() is True
            assert svc._owns_event_loop is False, (
                "Hosted mode must not own the event loop"
            )
            assert svc.thread is None, (
                "Hosted mode must not spawn a standalone thread"
            )
            assert isinstance(svc._service_task, asyncio.Task)
            # Stop before yielding so ``running`` is still True for stop()'s
            # guard. The stubbed supervisor will finish via its own awaits.
            assert svc.stop() is True
            assert svc.running is False
            # Drain any remaining callbacks.
            for _ in range(10):
                await asyncio.sleep(0)
            return svc

        svc = asyncio.run(_full())
        assert svc.running is False


# ============================================================================
# 6. AUDIT.md & CSRF-Foundation Files vorhanden (Sanity)
# ============================================================================
class TestSanityArtifacts:
    """Smoke checks for files added by Bundle 5/8."""

    def test_csrf_module_exists(self):
        assert CSRF_MODULE_PATH.exists(), (
            f"Expected app/web/csrf.py at {CSRF_MODULE_PATH}"
        )

    def test_csrf_module_defines_install_function(self):
        text = _read_text(CSRF_MODULE_PATH)
        assert "def install_csrf_protection" in text, (
            "csrf.py must define install_csrf_protection"
        )

    def test_audit_file_exists(self):
        assert AUDIT_PATH.exists(), f"Missing AUDIT.md at {AUDIT_PATH}"

    def test_base_template_references_csrf_token(self):
        """Base template wires the meta-tag that AJAX layers consume."""
        # Spec mentioned _log_section.html but the actual integration lives
        # in _base.html which is included by every other template.
        assert BASE_TEMPLATE_PATH.exists(), (
            f"Missing base template at {BASE_TEMPLATE_PATH}"
        )
        text = _read_text(BASE_TEMPLATE_PATH)
        assert "csrf_token()" in text, (
            "Base template must reference csrf_token() for the CSRF meta tag"
        )
