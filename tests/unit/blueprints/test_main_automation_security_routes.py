# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Blueprint Functional Tests                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Functional tests for main_routes / automation_routes / security_routes.

Targets
-------
- ``app/blueprints/main_routes.py``        (largest blueprint, 757 LOC)
- ``app/blueprints/automation_routes.py``  (automation API)
- ``app/blueprints/security_routes.py``    (token / encryption status API)

Strategy
--------
Each blueprint is mounted on a *minimal* Flask application so we never load
the full ``create_app`` stack (Docker / scheduler / mech background services).
HTTP basic auth is stubbed via ``auth.verify_password_callback`` so all
``@auth.login_required`` routes accept the canned credentials.  Service
singletons consumed lazily inside each handler are replaced with ``MagicMock``
objects via ``monkeypatch`` on the relevant ``get_xxx_service`` factory.

Setup-flow tests (``/setup``, ``/logout``) are intentionally not duplicated —
they live in ``tests/unit/security/test_bundle3_security.py``.

Compatibility note
------------------
Several services use ``@dataclass(frozen=True, slots=True)``.  ``slots=True``
on dataclass requires Python >= 3.10, but the local interpreter is Python 3.9
where it raises ``TypeError`` on class-body execution.  We patch
``dataclasses.dataclass`` once at module-load time to silently strip ``slots``
so the route imports succeed during test collection.  This is a *test-only*
shim and does not affect production code paths.
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
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Auth helpers — verify_password is stubbed to accept any Basic credential
# ---------------------------------------------------------------------------

_AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(b"admin:test").decode(),
}


def _stub_auth(monkeypatch):
    """Replace HTTPBasicAuth.verify_password_callback so any non-empty creds pass.

    flask_httpauth calls ``verify_password`` even when no Authorization header
    is present (with empty username/password). To still enforce 401 for
    unauthenticated requests, we only authenticate when *both* fields are
    truthy — matching the basic-auth contract (no header = no creds = 401).
    """
    from app import auth as auth_module

    def _verify(username, password):
        if username and password:
            return "admin"
        return None

    monkeypatch.setattr(auth_module.auth, "verify_password_callback", _verify)
    # Stub the error handler too: the production handler calls load_config()
    # which on the dev SMB mount triggers PermissionError on the real
    # config/ directory. Override it with a deterministic 401 JSON response.
    from flask import jsonify as _jsonify

    def _err(status):  # pragma: no cover - simple stub
        resp = _jsonify(message="Authentication Required")
        resp.status_code = status
        return resp

    monkeypatch.setattr(auth_module.auth, "auth_error_callback", _err)


def _build_app(blueprint, monkeypatch, *, url_prefix=None):
    """Create a minimal Flask app with one blueprint and stubbed auth."""
    _stub_auth(monkeypatch)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-blueprint-routes"
    app.config["WTF_CSRF_ENABLED"] = False
    if url_prefix is not None:
        app.register_blueprint(blueprint, url_prefix=url_prefix)
    else:
        app.register_blueprint(blueprint)
    return app


# ===========================================================================
# main_routes
# ===========================================================================


@pytest.fixture
def main_app(monkeypatch):
    from app.blueprints.main_routes import main_bp

    return _build_app(main_bp, monkeypatch)


def _result(success=True, **kwargs):
    """Build a SimpleNamespace mimicking the various *Result dataclasses."""
    ns = SimpleNamespace(success=success)
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---- /set_ui_language --------------------------------------------------------


class TestSetUiLanguage:
    def test_unauthenticated_returns_401(self, main_app):
        client = main_app.test_client()
        resp = client.post("/set_ui_language", data={"ui_language": "de"})
        assert resp.status_code == 401

    def test_success_calls_update_config_fields_with_language(
        self, main_app, monkeypatch
    ):
        called = {}

        def fake_update(fields):
            called.update(fields)
            return True

        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields", fake_update
        )
        client = main_app.test_client()
        resp = client.post(
            "/set_ui_language", data={"ui_language": "de"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"success": True, "language": "de"}
        assert called == {"ui_language": "de"}

    def test_failure_returns_500(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields", lambda f: False
        )
        client = main_app.test_client()
        resp = client.post(
            "/set_ui_language", data={"ui_language": "fr"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False

    def test_default_language_when_missing(self, main_app, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields",
            lambda f: captured.update(f) or True,
        )
        client = main_app.test_client()
        resp = client.post("/set_ui_language", data={}, headers=_AUTH_HEADER)
        assert resp.status_code == 200
        # default 'en' applied when ui_language form field absent
        assert captured.get("ui_language") == "en"


# ---- /save_config_api -------------------------------------------------------


class TestSaveConfigApi:
    def test_unauthenticated_returns_401(self, main_app):
        client = main_app.test_client()
        resp = client.post("/save_config_api", data={"foo": "bar"})
        assert resp.status_code == 401

    def test_success_returns_json_for_ajax(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.save_configuration.return_value = SimpleNamespace(
            success=True,
            message="saved",
            config_files=["config.json"],
            critical_settings_changed=False,
            error=None,
        )
        monkeypatch.setattr(
            "services.web.configuration_save_service.get_configuration_save_service",
            lambda: svc,
        )

        client = main_app.test_client()
        resp = client.post(
            "/save_config_api",
            data={"some_field": "value"},
            headers={**_AUTH_HEADER, "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["message"] == "saved"

    def test_non_ajax_redirects_to_config_page(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.save_configuration.return_value = SimpleNamespace(
            success=True,
            message="saved",
            config_files=[],
            critical_settings_changed=False,
            error=None,
        )
        monkeypatch.setattr(
            "services.web.configuration_save_service.get_configuration_save_service",
            lambda: svc,
        )

        client = main_app.test_client()
        resp = client.post(
            "/save_config_api", data={"x": "y"}, headers=_AUTH_HEADER
        )
        # Plain form-submit -> redirect to config page.
        assert resp.status_code == 302
        assert "/" in resp.headers.get("Location", "")

    def test_service_failure_returns_failure_payload(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.save_configuration.return_value = SimpleNamespace(
            success=False,
            message=None,
            config_files=[],
            critical_settings_changed=False,
            error="boom",
        )
        monkeypatch.setattr(
            "services.web.configuration_save_service.get_configuration_save_service",
            lambda: svc,
        )
        client = main_app.test_client()
        resp = client.post(
            "/save_config_api",
            data={"x": "y"},
            headers={**_AUTH_HEADER, "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False
        assert body["message"] == "boom"

    def test_runtime_error_handled_gracefully(self, main_app, monkeypatch):
        def boom():
            raise RuntimeError("svc unavailable")

        monkeypatch.setattr(
            "services.web.configuration_save_service.get_configuration_save_service",
            boom,
        )
        client = main_app.test_client()
        resp = client.post(
            "/save_config_api",
            data={"x": "y"},
            headers={**_AUTH_HEADER, "X-Requested-With": "XMLHttpRequest"},
        )
        # AJAX path returns JSON 200 with success=False (route's except branch)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False


# ---- /performance_stats ------------------------------------------------------


class TestPerformanceStats:
    def test_unauthenticated_returns_401(self, main_app):
        resp = main_app.test_client().get("/performance_stats")
        assert resp.status_code == 401

    def test_success_returns_data(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_performance_stats.return_value = SimpleNamespace(
            success=True, performance_data={"cpu": 12.5}, error=None
        )
        monkeypatch.setattr(
            "services.web.performance_stats_service.get_performance_stats_service",
            lambda: svc,
        )
        resp = main_app.test_client().get(
            "/performance_stats", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["performance_data"] == {"cpu": 12.5}

    def test_service_failure_returns_failure_payload(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_performance_stats.return_value = SimpleNamespace(
            success=False, performance_data=None, error="db timeout"
        )
        monkeypatch.setattr(
            "services.web.performance_stats_service.get_performance_stats_service",
            lambda: svc,
        )
        resp = main_app.test_client().get(
            "/performance_stats", headers=_AUTH_HEADER
        )
        # Route returns 200 (no explicit non-200 status code in failure branch)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False


# ---- /refresh_containers -----------------------------------------------------


class TestRefreshContainers:
    def test_unauthenticated_returns_401(self, main_app):
        resp = main_app.test_client().post("/refresh_containers")
        assert resp.status_code == 401

    def test_success_returns_count_and_timestamp(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.refresh_containers.return_value = SimpleNamespace(
            success=True,
            container_count=4,
            timestamp=1700000000,
            formatted_time="2023-11-14 22:13:20",
            error=None,
        )
        monkeypatch.setattr(
            "services.web.container_refresh_service.get_container_refresh_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/refresh_containers", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["container_count"] == 4
        assert body["formatted_time"] == "2023-11-14 22:13:20"

    def test_service_failure_returns_generic_message(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.refresh_containers.return_value = SimpleNamespace(
            success=False,
            container_count=0,
            timestamp=0,
            formatted_time="",
            error="docker down",
        )
        monkeypatch.setattr(
            "services.web.container_refresh_service.get_container_refresh_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/refresh_containers", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        # Generic error surfaced to user — no raw service error leaks
        assert "docker down" not in body["message"]


# ---- /enable_temp_debug + /disable_temp_debug + /temp_debug_status ----------


class TestTempDebugRoutes:
    def test_enable_temp_debug_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.enable_temp_debug.return_value = SimpleNamespace(
            success=True, data={"expires_at": "soon"}, error=None
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/enable_temp_debug", data={"duration": "15"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["expires_at"] == "soon"

    def test_enable_temp_debug_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.enable_temp_debug.return_value = SimpleNamespace(
            success=False, data={}, error="cannot enable"
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/enable_temp_debug", data={}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_disable_temp_debug_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.disable_temp_debug.return_value = SimpleNamespace(
            success=True, data={"disabled_at": "now"}, error=None
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/disable_temp_debug", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_temp_debug_status_returns_200(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_debug_status.return_value = SimpleNamespace(
            success=True, data={"is_enabled": False}, error=None
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", lambda: svc
        )
        resp = main_app.test_client().get("/temp_debug_status", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ---- /api/spam-protection (GET + POST) --------------------------------------


class TestSpamProtection:
    def test_get_returns_settings_dict(self, main_app, monkeypatch):
        cfg = MagicMock()
        cfg.to_dict.return_value = {"global_settings": {"enabled": True}}
        svc = MagicMock()
        svc.get_config.return_value = SimpleNamespace(success=True, data=cfg)
        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/api/spam-protection", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"global_settings": {"enabled": True}}

    def test_post_no_body_returns_400(self, main_app, monkeypatch):
        # Provide a stub service to avoid singleton init; it should not be called.
        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service",
            lambda: MagicMock(),
        )
        resp = main_app.test_client().post(
            "/api/spam-protection",
            json={},  # explicit empty dict -> falsy -> early-return triggers
            headers=_AUTH_HEADER,
        )
        # Empty body -> 400 from the early-return guard
        assert resp.status_code == 400
        body = resp.get_json()
        assert body is not None and body["success"] is False

    def test_post_success_logs_action(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.save_config.return_value = SimpleNamespace(success=True)
        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service", lambda: svc
        )

        # Patch SpamProtectionConfig.from_dict so we don't need the real schema.
        fake_cfg = MagicMock()
        monkeypatch.setattr(
            "services.infrastructure.spam_protection_service.SpamProtectionConfig.from_dict",
            staticmethod(lambda d: fake_cfg),
        )
        # Capture log_user_action so we don't touch real logger.
        log_calls = []
        monkeypatch.setattr(
            "app.blueprints.main_routes.log_user_action",
            lambda **kw: log_calls.append(kw),
        )

        resp = main_app.test_client().post(
            "/api/spam-protection",
            json={"global_settings": {"enabled": True}},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert log_calls and log_calls[0]["action"] == "SAVE"

    def test_post_save_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.save_config.return_value = SimpleNamespace(success=False)
        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service", lambda: svc
        )
        monkeypatch.setattr(
            "services.infrastructure.spam_protection_service.SpamProtectionConfig.from_dict",
            staticmethod(lambda d: MagicMock()),
        )
        resp = main_app.test_client().post(
            "/api/spam-protection",
            json={"global_settings": {"enabled": False}},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500


# ---- /api/donation/status (no auth) -----------------------------------------


class TestDonationStatusEndpoint:
    def test_donation_status_returns_data(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_donation_status.return_value = SimpleNamespace(
            success=True, status_data={"level": 3, "Power": 25}, error=None
        )
        monkeypatch.setattr(
            "services.web.donation_status_service.get_donation_status_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/donation/status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["level"] == 3

    def test_donation_status_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_donation_status.return_value = SimpleNamespace(
            success=False, status_data=None, error="bad"
        )
        monkeypatch.setattr(
            "services.web.donation_status_service.get_donation_status_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/donation/status")
        assert resp.status_code == 500


# ---- /api/donation/click (no auth) ------------------------------------------


class TestDonationClickEndpoint:
    def test_missing_type_returns_400(self, main_app):
        resp = main_app.test_client().post("/api/donation/click", json={})
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_success_returns_timestamp(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.record_donation_click.return_value = SimpleNamespace(
            success=True, timestamp=1700000000, message="ok", error=None
        )
        monkeypatch.setattr(
            "services.web.donation_tracking_service.get_donation_tracking_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/api/donation/click", json={"type": "paypal"}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["timestamp"] == 1700000000


# ---- /api/donation/submit ----------------------------------------------------


class TestSubmitDonation:
    def test_unauthenticated_returns_401(self, main_app):
        resp = main_app.test_client().post(
            "/api/donation/submit", json={"amount": 5}
        )
        assert resp.status_code == 401

    def test_no_data_returns_400(self, main_app):
        resp = main_app.test_client().post(
            "/api/donation/submit",
            data=b"",
            headers={**_AUTH_HEADER, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_success_returns_donation_info(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.process_donation.return_value = SimpleNamespace(
            success=True,
            message="thanks",
            donation_info={"amount": 5},
            error=None,
        )
        monkeypatch.setattr(
            "services.web.donation_service.get_donation_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/donation/submit",
            json={"amount": 5, "donor_name": "Alice"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["donation_info"]["amount"] == 5


# ---- /api/donation/reset-power + add-power + consume-power ------------------


class TestPowerEndpoints:
    def test_reset_power_unauthenticated(self, main_app):
        resp = main_app.test_client().post("/api/donation/reset-power")
        assert resp.status_code == 401

    def test_reset_power_success(self, main_app, monkeypatch):
        # Patch unified service used inside route.
        monkeypatch.setattr(
            "services.donation.unified_donation_service.reset_all_donations",
            lambda source: SimpleNamespace(success=True, error_message=None),
        )
        # Patch _get_cached_mech_state helper to return a synthetic state.
        state = SimpleNamespace(
            level=1, level_name="Mech-1", Power=0, total_donated=0
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: state,
        )
        resp = main_app.test_client().post(
            "/api/donation/reset-power", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["level"] == 1

    def test_consume_power_returns_current_state(self, main_app, monkeypatch):
        state = SimpleNamespace(
            level=2, level_name="Mech-2", Power=42, total_donated=100
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: state,
        )
        resp = main_app.test_client().post(
            "/api/donation/consume-power", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["new_Power"] == 42
        assert body["level"] == 2

    def test_add_test_power_zero_amount_returns_400(self, main_app):
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": 0, "type": "test", "user": "x"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False

    def test_add_test_power_invalid_amount_returns_400(self, main_app):
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": "not-a-number"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400


# ---- /api/mech/difficulty ----------------------------------------------------


class TestMechDifficulty:
    def test_get_difficulty_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=True, data={"multiplier": 1.5}, error=None
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/api/mech/difficulty", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"multiplier": 1.5}

    def test_post_missing_param_returns_400(self, main_app):
        resp = main_app.test_client().post(
            "/api/mech/difficulty", json={}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert "difficulty_multiplier" in body["error"]

    def test_post_invalid_value_returns_400(self, main_app):
        resp = main_app.test_client().post(
            "/api/mech/difficulty",
            json={"difficulty_multiplier": "abc"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_post_with_manual_override_calls_set(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=True, data={"applied": 2.0}, error=None
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty",
            json={"difficulty_multiplier": 2.0, "manual_override": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        # Service invoked with operation='set' (manual_override path)
        call_arg = svc.manage_difficulty.call_args[0][0]
        assert call_arg.operation == "set"
        assert call_arg.multiplier == 2.0

    def test_reset_difficulty_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=True, data={"reset": True}, error=None
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json()["reset"] is True


# ---- /api/mech/music/<level> + /api/mech/music/info -------------------------


class TestMechMusicEndpoints:
    def test_get_music_url_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_mech_music_url.return_value = SimpleNamespace(
            success=True, title="Anthem", url="https://yt/abc", error=None,
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service", lambda: svc
        )
        resp = main_app.test_client().get("/api/mech/music/3")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["url"] == "https://yt/abc"
        assert body["platform"] == "YouTube"

    def test_get_music_url_failure(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_mech_music_url.return_value = SimpleNamespace(
            success=False, title=None, url=None, error="missing", status_code=404,
        )
        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service", lambda: svc
        )
        resp = main_app.test_client().get("/api/mech/music/99")
        assert resp.status_code == 404

    def test_music_info_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_all_music_info.return_value = SimpleNamespace(
            success=True, data={"tracks": []}, error=None, status_code=200
        )
        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service", lambda: svc
        )
        resp = main_app.test_client().get("/api/mech/music/info")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ---- /api/mech/display/<level>/<type> ---------------------------------------


class TestMechDisplay:
    def test_invalid_level_returns_400(self, main_app):
        resp = main_app.test_client().get("/api/mech/display/0/shadow")
        assert resp.status_code == 400

        resp = main_app.test_client().get("/api/mech/display/12/shadow")
        assert resp.status_code == 400

    def test_invalid_image_type_returns_400(self, main_app):
        resp = main_app.test_client().get("/api/mech/display/5/garbage")
        assert resp.status_code == 400


# ---- /api/donations/list -----------------------------------------------------


class TestDonationsApi:
    def test_unauthenticated_returns_401(self, main_app):
        resp = main_app.test_client().get("/api/donations/list")
        assert resp.status_code == 401

    def test_success_returns_serialized_history(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_donation_history.return_value = SimpleNamespace(
            success=True,
            data={
                "donations": [{"id": 1}],
                "stats": SimpleNamespace(
                    total_power=10, total_donations=1, average_donation=10
                ),
            },
            error=None,
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
        assert body["success"] is True
        assert body["donations"] == [{"id": 1}]
        assert body["stats"]["total_donations"] == 1


# ---- /api/donations/delete/<int:index> --------------------------------------


class TestDeleteDonation:
    def test_unauthenticated_returns_401(self, main_app):
        resp = main_app.test_client().post("/api/donations/delete/0")
        assert resp.status_code == 401

    def test_success_returns_message(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.delete_donation.return_value = SimpleNamespace(
            success=True,
            data={"action": "Deleted", "type": "DonationAdded", "deleted_seq": 42},
            error=None,
        )
        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/api/donations/delete/0", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "42" in body["message"]

    def test_failure_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.delete_donation.return_value = SimpleNamespace(
            success=False, data={}, error="not found"
        )
        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/api/donations/delete/99", headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


# ---- /api/donation/add-power success path -----------------------------------


class TestAddTestPowerSuccess:
    def test_positive_amount_uses_unified_service(self, main_app, monkeypatch):
        new_state = SimpleNamespace(
            level=2, level_name="Mech-2", Power=10, total_donated=10
        )
        monkeypatch.setattr(
            "services.donation.unified_donation_service.process_test_donation",
            lambda user, amount: SimpleNamespace(
                success=True, new_state=new_state, error_message=None
            ),
        )
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": 10, "user": "Tester", "type": "test"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["Power"] == 10
        assert body["level"] == 2

    def test_negative_amount_workaround_returns_current_state(
        self, main_app, monkeypatch
    ):
        state = SimpleNamespace(
            level=3, level_name="Mech-3", Power=15, total_donated=50
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: state,
        )
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": -5},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["Power"] == 15  # unchanged - reduction not supported

    def test_negative_amount_no_state_returns_500(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: None,
        )
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": -10},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500


# ---- /api/mech/speed-config + test-mech-animation + mech_animation ---------


class TestMechSpeedAndAnimation:
    def test_speed_config_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_speed_config.return_value = SimpleNamespace(
            success=True, data={"speed": 100}, error=None
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech-speed-config",
            json={"total_donations": 100},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"speed": 100}

    def test_speed_config_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_speed_config.return_value = SimpleNamespace(
            success=False, data=None, error="bad"
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech-speed-config",
            json={"total_donations": 0},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_mech_animation_success_returns_bytes(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_live_animation.return_value = SimpleNamespace(
            success=True,
            animation_bytes=b"\x89PNG\r\n",
            content_type="image/webp",
            cache_headers={"Cache-Control": "max-age=10"},
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().get("/mech_animation")
        assert resp.status_code == 200
        assert resp.data.startswith(b"\x89PNG")
        assert resp.headers.get("Cache-Control") == "max-age=10"

    def test_test_mech_animation_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_test_animation.return_value = SimpleNamespace(
            success=True,
            animation_bytes=b"FAKE",
            content_type="image/webp",
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/test-mech-animation",
            json={"donor_name": "Test", "amount": "5$", "total_donations": 5},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.data == b"FAKE"


# ---- /api/mech/reset + /api/mech/status -------------------------------------


class TestMechResetAndStatus:
    def test_reset_unauthenticated(self, main_app):
        resp = main_app.test_client().post("/api/mech/reset")
        assert resp.status_code == 401

    def test_reset_success(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_current_status.return_value = {
            "current_level": 5,
            "donations_count": 10,
            "total_donated": 100,
        }
        svc.full_reset.return_value = SimpleNamespace(
            success=True,
            message="ok",
            details={"timestamp": "2025-01-01", "operations": []},
        )
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service", lambda: svc
        )
        # Action logger may be called inside route
        monkeypatch.setattr(
            "services.infrastructure.action_logger.log_user_action",
            lambda **kw: None,
        )
        resp = main_app.test_client().post(
            "/api/mech/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["previous_status"]["current_level"] == 5

    def test_reset_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_current_status.return_value = {"current_level": 1}
        svc.full_reset.return_value = SimpleNamespace(
            success=False, message="fail", details={}
        )
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service", lambda: svc
        )
        monkeypatch.setattr(
            "services.infrastructure.action_logger.log_user_action",
            lambda **kw: None,
        )
        resp = main_app.test_client().post(
            "/api/mech/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_status_unauthenticated(self, main_app):
        resp = main_app.test_client().get("/api/mech/status")
        assert resp.status_code == 401

    def test_status_returns_sanitized_data(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_current_status.return_value = {
            "donations_count": 7,
            "total_donated": 25,
            "current_level": 2,
            "level_upgrades_count": 1,
            "next_level_threshold": 50,
            "amount_needed": 25,
            "next_level_name": "Mech-3",
            "channels_tracked": 0,
            "glvl_values": [1, 2, 3],
            "architecture": "v2",
            "deprecated_files_exist": False,
        }
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/api/mech/status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["status"]["current_level"] == 2
        assert body["status"]["glvl_values"] == [1, 2, 3]

    def test_status_service_error_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_current_status.return_value = {"error": "unavailable"}
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/api/mech/status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False


# ---- /port_diagnostics -------------------------------------------------------


class TestPortDiagnostics:
    def test_unauthenticated_returns_401(self, main_app):
        resp = main_app.test_client().get("/port_diagnostics")
        assert resp.status_code == 401

    def test_success_returns_data(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.run_port_diagnostics.return_value = SimpleNamespace(
            success=True, data={"ports": []}, error=None, status_code=200
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/port_diagnostics", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True

    def test_failure_uses_status_code(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.run_port_diagnostics.return_value = SimpleNamespace(
            success=False, data={}, error="net err", status_code=503
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/port_diagnostics", headers=_AUTH_HEADER
        )
        assert resp.status_code == 503


# ---- /api/simulate-donation-broadcast ---------------------------------------


class TestSimulateBroadcast:
    def test_simulate_returns_stub_message(self, main_app):
        resp = main_app.test_client().post(
            "/api/simulate-donation-broadcast", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert "not yet implemented" in body["message"].lower()


# ===========================================================================
# automation_routes
# ===========================================================================


@pytest.fixture
def automation_app(monkeypatch):
    from app.blueprints.automation_routes import automation_bp

    return _build_app(automation_bp, monkeypatch)


class TestAutomationRules:
    def test_get_rules_unauthenticated(self, automation_app):
        resp = automation_app.test_client().get("/api/automation/rules")
        assert resp.status_code == 401

    def test_get_rules_returns_serialized(self, automation_app, monkeypatch):
        rule = MagicMock()
        rule.to_dict.return_value = {"id": "r1", "name": "Rule 1"}
        cfg = MagicMock()
        cfg.get_rules.return_value = [rule]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().get(
            "/api/automation/rules", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"rules": [{"id": "r1", "name": "Rule 1"}]}

    def test_create_rule_success(self, automation_app, monkeypatch):
        new_rule = MagicMock()
        new_rule.to_dict.return_value = {"id": "new", "name": "New"}
        cfg = MagicMock()
        cfg.add_rule.return_value = SimpleNamespace(
            success=True, data=new_rule, error=None
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules",
            json={"name": "New"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["rule"]["id"] == "new"

    def test_create_rule_validation_error_returns_400(
        self, automation_app, monkeypatch
    ):
        cfg = MagicMock()
        cfg.add_rule.return_value = SimpleNamespace(
            success=False, data=None, error="bad input"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules",
            json={"foo": "bar"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"] == "bad input"

    def test_update_rule_success(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_rule.return_value = SimpleNamespace(success=True, error=None)
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().put(
            "/api/automation/rules/r1", json={"x": 1}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"success": True}

    def test_update_rule_failure_returns_400(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_rule.return_value = SimpleNamespace(
            success=False, error="missing"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().put(
            "/api/automation/rules/r1", json={}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400

    def test_delete_rule_success(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.delete_rule.return_value = SimpleNamespace(success=True, error=None)
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().delete(
            "/api/automation/rules/r1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200

    def test_delete_rule_failure_returns_400(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.delete_rule.return_value = SimpleNamespace(
            success=False, error="not found"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().delete(
            "/api/automation/rules/r1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


class TestAutomationToggleRule:
    def test_toggle_unknown_rule_returns_404(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.get_rule.return_value = None
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules/missing/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_toggle_success_flips_enabled(self, automation_app, monkeypatch):
        rule = MagicMock()
        rule.to_dict.return_value = {"id": "r1", "enabled": True}
        cfg = MagicMock()
        cfg.get_rule.return_value = rule
        cfg.update_rule.return_value = SimpleNamespace(success=True, error=None)
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules/r1/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["enabled"] is False  # flipped

    def test_toggle_update_failure_returns_400(self, automation_app, monkeypatch):
        rule = MagicMock()
        rule.to_dict.return_value = {"id": "r1", "enabled": False}
        cfg = MagicMock()
        cfg.get_rule.return_value = rule
        cfg.update_rule.return_value = SimpleNamespace(
            success=False, error="db locked"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/rules/r1/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


class TestAutomationSettings:
    def test_get_settings_returns_json(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.get_global_settings.return_value = {"enabled": True}
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().get(
            "/api/automation/settings", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"enabled": True}

    def test_update_settings_success(self, automation_app, monkeypatch):
        cfg = MagicMock()
        cfg.update_global_settings.return_value = SimpleNamespace(
            success=True, error=None
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/settings",
            json={"enabled": False},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"success": True}

    def test_update_settings_failure_returns_400(
        self, automation_app, monkeypatch
    ):
        cfg = MagicMock()
        cfg.update_global_settings.return_value = SimpleNamespace(
            success=False, error="bad"
        )
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_config_service",
            lambda: cfg,
        )
        resp = automation_app.test_client().post(
            "/api/automation/settings", json={}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


class TestAutomationHistory:
    def test_get_history_default_limit(self, automation_app, monkeypatch):
        state = MagicMock()
        state.get_history.return_value = [{"id": 1}]
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_state_service",
            lambda: state,
        )
        resp = automation_app.test_client().get(
            "/api/automation/history", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["history"] == [{"id": 1}]
        # Default limit applied: get_history called with (None, 50)
        state.get_history.assert_called_once_with(None, 50)

    def test_get_history_invalid_limit_falls_back_to_50(
        self, automation_app, monkeypatch
    ):
        state = MagicMock()
        state.get_history.return_value = []
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_state_service",
            lambda: state,
        )
        resp = automation_app.test_client().get(
            "/api/automation/history?limit=not-a-number&container=foo",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        state.get_history.assert_called_once_with("foo", 50)

    def test_get_history_clamps_high_limit(self, automation_app, monkeypatch):
        state = MagicMock()
        state.get_history.return_value = []
        monkeypatch.setattr(
            "app.blueprints.automation_routes.get_auto_action_state_service",
            lambda: state,
        )
        resp = automation_app.test_client().get(
            "/api/automation/history?limit=10000", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        # Clamped to 500
        state.get_history.assert_called_once_with(None, 500)


class TestAutomationTestRule:
    def test_test_rule_missing_body_returns_400(self, automation_app):
        resp = automation_app.test_client().post(
            "/api/automation/test",
            data=b"",
            headers={**_AUTH_HEADER, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400


class TestAutomationChannels:
    def test_channels_returns_empty_when_no_bot(self, automation_app, monkeypatch):
        # Bot instance unavailable -> empty list with warning
        monkeypatch.setattr(
            "services.scheduling.donation_message_service.get_bot_instance",
            lambda: None,
        )
        resp = automation_app.test_client().get(
            "/api/automation/channels", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["channels"] == []
        assert "warning" in body

    def test_channels_returns_empty_when_bot_no_guilds(
        self, automation_app, monkeypatch
    ):
        bot = MagicMock()
        bot.guilds = []
        monkeypatch.setattr(
            "services.scheduling.donation_message_service.get_bot_instance",
            lambda: bot,
        )
        resp = automation_app.test_client().get(
            "/api/automation/channels", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["channels"] == []
        assert "warning" in body


# ===========================================================================
# security_routes
# ===========================================================================


@pytest.fixture
def security_app(monkeypatch):
    from app.blueprints.security_routes import security_bp

    return _build_app(security_bp, monkeypatch)


class TestSecurityTokenStatus:
    def test_unauthenticated_returns_401(self, security_app):
        resp = security_app.test_client().get("/api/token-security-status")
        assert resp.status_code == 401

    def test_token_status_success(self, security_app, monkeypatch):
        svc = MagicMock()
        svc.get_token_security_status.return_value = SimpleNamespace(
            success=True,
            data={
                "token_exists": True,
                "is_encrypted": False,
                "can_encrypt": True,
            },
            error=None,
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/token-security-status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["token_exists"] is True

    def test_token_status_failure_uses_status_code(
        self, security_app, monkeypatch
    ):
        svc = MagicMock()
        svc.get_token_security_status.return_value = SimpleNamespace(
            success=False,
            data={"token_exists": False},
            error="no token",
            status_code=503,
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/token-security-status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"] == "no token"

    def test_runtime_error_returns_500_and_payload(
        self, security_app, monkeypatch
    ):
        def boom():
            raise RuntimeError("svc unreachable")

        monkeypatch.setattr(
            "services.web.security_service.get_security_service", boom
        )
        resp = security_app.test_client().get(
            "/api/token-security-status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert body["token_exists"] is False
        assert "recommendations" in body


class TestSecurityEncryptToken:
    def test_unauthenticated_returns_401(self, security_app):
        resp = security_app.test_client().post("/api/encrypt-token")
        assert resp.status_code == 401

    def test_encrypt_token_success(self, security_app, monkeypatch):
        svc = MagicMock()
        svc.encrypt_token.return_value = SimpleNamespace(
            success=True,
            data={"encrypted": True, "message": "ok"},
            error=None,
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().post(
            "/api/encrypt-token", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["encrypted"] is True

    def test_encrypt_token_failure_uses_status_code(
        self, security_app, monkeypatch
    ):
        svc = MagicMock()
        svc.encrypt_token.return_value = SimpleNamespace(
            success=False, data={}, error="already encrypted", status_code=409
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().post(
            "/api/encrypt-token", headers=_AUTH_HEADER
        )
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["success"] is False

    def test_encrypt_token_runtime_error_returns_500(
        self, security_app, monkeypatch
    ):
        def boom():
            raise AttributeError("missing dep")

        monkeypatch.setattr(
            "services.web.security_service.get_security_service", boom
        )
        resp = security_app.test_client().post(
            "/api/encrypt-token", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500


class TestSecurityMigrationHelp:
    def test_unauthenticated_returns_401(self, security_app):
        resp = security_app.test_client().get("/api/migration-help")
        assert resp.status_code == 401

    def test_migration_help_success(self, security_app, monkeypatch):
        svc = MagicMock()
        svc.get_migration_help.return_value = SimpleNamespace(
            success=True,
            data={"instructions": ["step 1"]},
            error=None,
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/migration-help", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"instructions": ["step 1"]}

    def test_migration_help_failure(self, security_app, monkeypatch):
        svc = MagicMock()
        svc.get_migration_help.return_value = SimpleNamespace(
            success=False, data={"instructions": []}, error="bad", status_code=500,
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/migration-help", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500


class TestSecurityAudit:
    def test_unauthenticated_returns_401(self, security_app):
        resp = security_app.test_client().get("/api/security-audit")
        assert resp.status_code == 401

    def test_audit_success(self, security_app, monkeypatch):
        svc = MagicMock()
        svc.get_security_audit.return_value = SimpleNamespace(
            success=True,
            data={"score": 95},
            error=None,
            status_code=200,
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/security-audit", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["score"] == 95

    def test_audit_failure(self, security_app, monkeypatch):
        svc = MagicMock()
        svc.get_security_audit.return_value = SimpleNamespace(
            success=False, data={}, error="not allowed", status_code=403
        )
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/security-audit", headers=_AUTH_HEADER
        )
        assert resp.status_code == 403
