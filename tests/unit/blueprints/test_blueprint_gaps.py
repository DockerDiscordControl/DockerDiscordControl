# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Blueprint Coverage-Gap Tests                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Targeted coverage-gap tests for the four blueprints below.

Targets
-------
- ``app/blueprints/main_routes.py``
- ``app/blueprints/log_routes.py``
- ``app/blueprints/security_routes.py``
- ``app/blueprints/tasks_bp.py``

Strategy
--------
Each test exercises an *uncovered* line range as reported by ``pytest --cov``
with the existing test suite (see test_main_automation_security_routes.py and
test_other_routes.py). Like those files we mount the blueprint on a minimal
Flask app and stub HTTPBasicAuth + service factories with monkeypatch so the
route bodies execute without the real services.

NEVER manipulate ``sys.modules`` here.
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
from flask import Flask, jsonify as _jsonify


_AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(b"admin:test").decode(),
}


def _stub_auth(monkeypatch):
    """Replace HTTPBasicAuth.verify_password_callback so any creds pass."""
    from app import auth as auth_module

    def _verify(username, password):
        if username and password:
            return "admin"
        return None

    monkeypatch.setattr(auth_module.auth, "verify_password_callback", _verify)

    def _err(status):  # pragma: no cover - simple stub
        resp = _jsonify(message="Authentication Required")
        resp.status_code = status
        return resp

    monkeypatch.setattr(auth_module.auth, "auth_error_callback", _err)


def _build_app(blueprint, monkeypatch, *, url_prefix=None):
    _stub_auth(monkeypatch)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-blueprint-gaps"
    app.config["WTF_CSRF_ENABLED"] = False
    if url_prefix is not None:
        app.register_blueprint(blueprint, url_prefix=url_prefix)
    else:
        app.register_blueprint(blueprint)
    return app


# ===========================================================================
# main_routes.py
# ===========================================================================


@pytest.fixture
def main_app(monkeypatch):
    from app.blueprints.main_routes import main_bp

    return _build_app(main_bp, monkeypatch)


# ---- _get_cached_mech_state — fallback failure (lines 74-75) ---------------


class TestGetCachedMechState:
    def test_cache_miss_and_service_failure_returns_none(self, monkeypatch):
        """Cache miss + downstream mech service failure -> returns None (74-75)."""
        from app.blueprints.main_routes import _get_cached_mech_state

        cache_service = MagicMock()
        cache_service.get_cached_status.return_value = SimpleNamespace(
            success=False,
            level=None, power=None, total_donated=None, name=None,
            threshold=None, speed=None, cache_age_seconds=0,
        )
        monkeypatch.setattr(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            lambda: cache_service,
        )
        mech_service = MagicMock()
        mech_service.get_mech_state_service.return_value = SimpleNamespace(
            success=False
        )
        monkeypatch.setattr(
            "services.mech.mech_service.get_mech_service",
            lambda: mech_service,
        )

        app = Flask(__name__)
        with app.app_context():
            state = _get_cached_mech_state()
        assert state is None

    def test_cache_value_error_returns_none(self, monkeypatch):
        """ValueError inside cache call -> data-error branch (81-84)."""
        from app.blueprints.main_routes import _get_cached_mech_state

        def _boom():
            raise ValueError("bad")

        monkeypatch.setattr(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            _boom,
        )
        app = Flask(__name__)
        with app.app_context():
            state = _get_cached_mech_state()
        assert state is None


# ---- /  (config_page) data-error path (lines 123-126) ----------------------


class TestConfigPageDataError:
    def test_value_error_uses_data_error_fallback(self, main_app, monkeypatch):
        def _boom():
            raise ValueError("bad data")

        monkeypatch.setattr(
            "services.web.configuration_page_service.get_configuration_page_service",
            _boom,
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.render_template",
            lambda *a, **kw: f"DATA_ERR:{kw.get('error_message', '')}",
        )
        resp = main_app.test_client().get("/", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"Data error" in resp.data


# ---- /set_ui_language exception path (lines 140-142) -----------------------


class TestSetUiLanguageExceptionPath:
    def test_unexpected_exception_returns_500(self, main_app, monkeypatch):
        def _boom(_fields):
            raise RuntimeError("explode")

        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields", _boom
        )
        resp = main_app.test_client().post(
            "/set_ui_language", data={"ui_language": "en"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False


# ---- /save_config_api with donation_disable_key (line 169) ----------------


class TestSaveConfigDonationKey:
    def test_donation_disable_key_present_logs_debug(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.save_configuration.return_value = SimpleNamespace(
            success=True, message="saved", config_files=[],
            critical_settings_changed=False, error=None,
        )
        monkeypatch.setattr(
            "services.web.configuration_save_service.get_configuration_save_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/save_config_api",
            data={"donation_disable_key": "secret-key", "x": "y"},
            headers={**_AUTH_HEADER, "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ---- /refresh_containers service / data error (lines 259-269) ---------------


class TestRefreshContainersErrorPaths:
    def test_runtime_error_returns_failure_payload(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc unavailable")

        monkeypatch.setattr(
            "services.web.container_refresh_service.get_container_refresh_service",
            _boom,
        )
        resp = main_app.test_client().post(
            "/refresh_containers", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Service error" in body["message"]

    def test_value_error_returns_data_error_failure(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.refresh_containers.side_effect = ValueError("bad data")
        monkeypatch.setattr(
            "services.web.container_refresh_service.get_container_refresh_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/refresh_containers", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Data error" in body["message"]


# ---- /enable_temp_debug, /disable_temp_debug, /temp_debug_status errors -----


class TestTempDebugErrorPaths:
    def test_enable_temp_debug_runtime_error(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("nope")

        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", _boom
        )
        resp = main_app.test_client().post(
            "/enable_temp_debug", data={"duration": "10"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_enable_temp_debug_value_error(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.enable_temp_debug.side_effect = ValueError("bad duration")
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/enable_temp_debug", data={"duration": "abc"}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_disable_temp_debug_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.disable_temp_debug.return_value = SimpleNamespace(
            success=False, data={}, error="cannot disable"
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/disable_temp_debug", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_disable_temp_debug_runtime_error(self, main_app, monkeypatch):
        def _boom():
            raise AttributeError("missing")

        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", _boom
        )
        resp = main_app.test_client().post(
            "/disable_temp_debug", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_temp_debug_status_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_debug_status.return_value = SimpleNamespace(
            success=False, data={}, error="cache fail"
        )
        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service",
            lambda: svc,
        )
        resp = main_app.test_client().get(
            "/temp_debug_status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_temp_debug_status_runtime_error(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("nope")

        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", _boom
        )
        resp = main_app.test_client().get(
            "/temp_debug_status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert body.get("is_enabled") is False


# ---- /performance_stats service-error path (lines 417-420) ------------------


class TestPerformanceStatsErrorPaths:
    def test_runtime_error_returns_failure_payload(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("nope")

        monkeypatch.setattr(
            "services.web.performance_stats_service.get_performance_stats_service",
            _boom,
        )
        resp = main_app.test_client().get(
            "/performance_stats", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Service error" in body["message"]


# ---- /api/spam-protection error paths --------------------------------------


class TestSpamProtectionErrorPaths:
    def test_get_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc down")

        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service", _boom
        )
        resp = main_app.test_client().get(
            "/api/spam-protection", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert "Service error" in resp.get_json()["error"]

    def test_post_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc down")

        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service", _boom
        )
        resp = main_app.test_client().post(
            "/api/spam-protection",
            json={"global_settings": {"enabled": True}},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_post_value_error_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        monkeypatch.setattr(
            "app.blueprints.main_routes.get_spam_protection_service",
            lambda: svc,
        )

        def _boom_from(_d):
            raise ValueError("bad config dict")

        monkeypatch.setattr(
            "services.infrastructure.spam_protection_service.SpamProtectionConfig.from_dict",
            staticmethod(_boom_from),
        )
        resp = main_app.test_client().post(
            "/api/spam-protection",
            json={"global_settings": {"enabled": True}},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False


# ---- /api/donation/status error paths --------------------------------------


class TestDonationStatusErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc down")

        monkeypatch.setattr(
            "services.web.donation_status_service.get_donation_status_service",
            _boom,
        )
        resp = main_app.test_client().get("/api/donation/status")
        assert resp.status_code == 500

    def test_value_error_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_donation_status.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.donation_status_service.get_donation_status_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/donation/status")
        assert resp.status_code == 500


# ---- /api/donation/click error paths ---------------------------------------


class TestDonationClickErrorPaths:
    def test_failure_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.record_donation_click.return_value = SimpleNamespace(
            success=False, timestamp=None, message=None, error="bad type"
        )
        monkeypatch.setattr(
            "services.web.donation_tracking_service.get_donation_tracking_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/api/donation/click", json={"type": "x"}
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc down")

        monkeypatch.setattr(
            "services.web.donation_tracking_service.get_donation_tracking_service",
            _boom,
        )
        resp = main_app.test_client().post(
            "/api/donation/click", json={"type": "paypal"}
        )
        assert resp.status_code == 500


# ---- /api/donation/add-power test-donation failure & errors ----------------


class TestAddTestPowerErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom(_u, _a):
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.donation.unified_donation_service.process_test_donation",
            _boom,
        )
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": 5},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_negative_amount_state_with_higher_power_else_branch(
        self, main_app, monkeypatch
    ):
        """Branch where new_power >= current power (line 606-607)."""
        # current.Power=10, amount=-0 wouldn't be < 0, but amount -3 with state
        # gives new_power=max(0, 10-3)=7 < 10 -> uses early-return branch.
        # The else-fallthrough is unreachable in normal logic; we use a state
        # where Power=0 and amount=-1 -> new_power=max(0,-1)=0, NOT < Power(0).
        state = SimpleNamespace(
            level=1, level_name="Mech-1", Power=0, total_donated=0
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: state,
        )
        resp = main_app.test_client().post(
            "/api/donation/add-power",
            json={"amount": -1},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["Power"] == 0


# ---- /api/donation/reset-power error paths ---------------------------------


class TestResetPowerErrorPaths:
    def test_reset_failure_returns_failure(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "services.donation.unified_donation_service.reset_all_donations",
            lambda source: SimpleNamespace(
                success=False, error_message="db locked"
            ),
        )
        resp = main_app.test_client().post(
            "/api/donation/reset-power", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False

    def test_reset_state_unavailable_returns_failure(
        self, main_app, monkeypatch
    ):
        monkeypatch.setattr(
            "services.donation.unified_donation_service.reset_all_donations",
            lambda source: SimpleNamespace(success=True, error_message=None),
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: None,
        )
        resp = main_app.test_client().post(
            "/api/donation/reset-power", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "reset state" in body["error"].lower()

    def test_reset_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom(source):
            raise RuntimeError("crash")

        monkeypatch.setattr(
            "services.donation.unified_donation_service.reset_all_donations",
            _boom,
        )
        resp = main_app.test_client().post(
            "/api/donation/reset-power", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500


# ---- /api/donation/consume-power error path (lines 673, 686-689) -----------


class TestConsumePowerErrorPaths:
    def test_no_state_returns_failure(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state",
            lambda include_decimals=False: None,
        )
        resp = main_app.test_client().post(
            "/api/donation/consume-power", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False

    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom(include_decimals=False):
            raise RuntimeError("nope")

        monkeypatch.setattr(
            "app.blueprints.main_routes._get_cached_mech_state", _boom
        )
        resp = main_app.test_client().post(
            "/api/donation/consume-power", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500


# ---- /api/donation/submit error paths --------------------------------------


class TestSubmitDonationErrorPaths:
    def test_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.process_donation.return_value = SimpleNamespace(
            success=False, message=None, donation_info=None,
            error="invalid amount",
        )
        monkeypatch.setattr(
            "services.web.donation_service.get_donation_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/donation/submit",
            json={"amount": 0, "donor_name": "Bob"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.donation_service.get_donation_service", _boom
        )
        resp = main_app.test_client().post(
            "/api/donation/submit",
            json={"amount": 5},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_value_error_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.process_donation.side_effect = ValueError("bad amount")
        monkeypatch.setattr(
            "services.web.donation_service.get_donation_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/donation/submit",
            json={"amount": "x"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400


# ---- /mech_animation error paths (lines 757-770) ---------------------------


class TestMechAnimationErrorPaths:
    def test_failure_returns_error_response(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_live_animation.return_value = SimpleNamespace(
            success=False,
            animation_bytes=b"",
            content_type="image/webp",
            cache_headers={},
            status_code=500,
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().get("/mech_animation")
        assert resp.status_code == 500
        assert b"Animation generation failed" in resp.data

    def test_runtime_error_returns_500_json(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", _boom
        )
        resp = main_app.test_client().get("/mech_animation")
        assert resp.status_code == 500
        assert resp.get_json()["error"].startswith("Service error")

    def test_value_error_returns_500_json(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_live_animation.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().get("/mech_animation")
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]


# ---- /api/test-mech-animation error paths (lines 805-818) ------------------


class TestTestMechAnimationErrorPaths:
    def test_failure_returns_error_response(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_test_animation.return_value = SimpleNamespace(
            success=False,
            animation_bytes=b"",
            content_type="image/webp",
            status_code=503,
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/test-mech-animation",
            json={"donor_name": "X", "amount": "1$", "total_donations": 0},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 503
        assert b"Service not available" in resp.data

    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", _boom
        )
        resp = main_app.test_client().post(
            "/api/test-mech-animation",
            json={"donor_name": "X"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500


# ---- /api/mech-speed-config error paths (lines 859-866) --------------------


class TestSpeedConfigErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", _boom
        )
        resp = main_app.test_client().post(
            "/api/mech-speed-config",
            json={"total_donations": 5},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_value_error_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_speed_config.side_effect = ValueError("bad input")
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech-speed-config",
            json={"total_donations": "x"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400


# ---- /port_diagnostics runtime error (lines 893-896) -----------------------


class TestPortDiagnosticsErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc dead")

        monkeypatch.setattr(
            "services.web.diagnostics_service.get_diagnostics_service", _boom
        )
        resp = main_app.test_client().get(
            "/port_diagnostics", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False


# ---- /api/mech/difficulty error / set / reset paths -------------------------


class TestMechDifficultyErrorPaths:
    def test_get_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=False, data=None, error="db down"
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().get(
            "/api/mech/difficulty", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_get_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", _boom
        )
        resp = main_app.test_client().get(
            "/api/mech/difficulty", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_post_no_manual_override_uses_reset_op(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=True, data={"reset": True}, error=None
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty",
            json={"difficulty_multiplier": 1.5, "manual_override": False},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        # Service called with operation='reset'
        call_arg = svc.manage_difficulty.call_args[0][0]
        assert call_arg.operation == "reset"

    def test_post_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=False, data=None, error="db locked"
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty",
            json={"difficulty_multiplier": 1.0, "manual_override": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_post_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", _boom
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty",
            json={"difficulty_multiplier": 2.0, "manual_override": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_reset_failure_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.manage_difficulty.return_value = SimpleNamespace(
            success=False, data=None, error="x"
        )
        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", lambda: svc
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_reset_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_web_service.get_mech_web_service", _boom
        )
        resp = main_app.test_client().post(
            "/api/mech/difficulty/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500


# ---- /api/donations/list error paths (lines 1032-1042) ----------------------


class TestDonationsApiErrorPaths:
    def test_runtime_error_returns_failure(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc dead")

        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            _boom,
        )
        resp = main_app.test_client().get(
            "/api/donations/list", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Service error" in body["error"]

    def test_value_error_returns_failure(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_donation_history.side_effect = ValueError("bad data")
        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            lambda: svc,
        )
        resp = main_app.test_client().get(
            "/api/donations/list", headers=_AUTH_HEADER
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Data error" in body["error"]


# ---- /api/donations/delete error paths (lines 1086-1096) -------------------


class TestDeleteDonationErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            _boom,
        )
        resp = main_app.test_client().post(
            "/api/donations/delete/0", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_value_error_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.delete_donation.side_effect = ValueError("bad index")
        monkeypatch.setattr(
            "services.donation.donation_management_service.get_donation_management_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/api/donations/delete/0", headers=_AUTH_HEADER
        )
        assert resp.status_code == 400


# ---- /setup POST - error paths (lines 1210-1232) ---------------------------


class TestSetupPostErrorPaths:
    def test_save_failure_returns_failure(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )
        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields",
            lambda fields: False,
        )
        strong = "GoodPass123!@"
        resp = main_app.test_client().post(
            "/setup", data={"password": strong, "confirm_password": strong}
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Failed to save" in body["error"]

    def test_setup_value_error_returns_failure(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )

        def _boom(_password, **_kw):
            raise ValueError("bad hash params")

        # Patch werkzeug's generate_password_hash imported inside the route.
        monkeypatch.setattr(
            "werkzeug.security.generate_password_hash", _boom
        )
        strong = "GoodPass123!@"
        resp = main_app.test_client().post(
            "/setup", data={"password": strong, "confirm_password": strong}
        )
        body = resp.get_json()
        assert body["success"] is False

    def test_setup_io_error_returns_failure(self, main_app, monkeypatch):
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: {}
        )

        def _boom(_fields):
            raise IOError("disk full")

        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields", _boom
        )
        strong = "GoodPass123!@"
        resp = main_app.test_client().post(
            "/setup", data={"password": strong, "confirm_password": strong}
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "save configuration" in body["error"].lower()


# ---- /api/mech/music/<level> error paths (lines 1271-1281) ------------------


class TestMechMusicErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service", _boom
        )
        resp = main_app.test_client().get("/api/mech/music/3")
        assert resp.status_code == 500

    def test_value_error_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_mech_music_url.side_effect = ValueError("bad level")
        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/music/3")
        assert resp.status_code == 400


# ---- /api/mech/music/info error path (lines 1310-1313) ---------------------


class TestMusicInfoErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc dead")

        monkeypatch.setattr(
            "services.web.mech_music_service.get_mech_music_service", _boom
        )
        resp = main_app.test_client().get("/api/mech/music/info")
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False


# ---- /api/mech/display/<level>/<type> error paths (lines 1369-1376) --------


class TestMechDisplayErrorPaths:
    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            _boom,
        )
        resp = main_app.test_client().get("/api/mech/display/5/shadow")
        assert resp.status_code == 500
        assert resp.get_json()["error"].startswith("Service error")

    def test_value_error_returns_400(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_mech_display_image.side_effect = ValueError("bad params")
        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/display/5/shadow")
        assert resp.status_code == 400


# ---- /api/mech/display/info error / oddly-named files (1412-1413, 1424-1441)


class TestMechDisplayInfoErrorPaths:
    def test_skips_filenames_with_non_int_level(
        self, main_app, monkeypatch, tmp_path
    ):
        """Filename ``mech_X_shadow.webp`` -> int(X) raises ValueError, continue (1412-1413)."""
        (tmp_path / "mech_X_shadow.webp").write_bytes(b"x")
        (tmp_path / "mech_2_shadow.webp").write_bytes(b"y")

        svc = MagicMock()
        svc.cache_dir = tmp_path
        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/display/info")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        # only the well-formed file counts in cached_images
        assert body["total_cached"] == 2  # both files counted by glob

    def test_runtime_error_returns_500(self, main_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            _boom,
        )
        resp = main_app.test_client().get("/api/mech/display/info")
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_io_error_returns_500(self, main_app, monkeypatch):
        # Build a service whose cache_dir.glob() raises OSError
        svc = MagicMock()
        cache_dir_mock = MagicMock()
        cache_dir_mock.glob.side_effect = OSError("permission denied")
        svc.cache_dir = cache_dir_mock
        monkeypatch.setattr(
            "services.mech.mech_display_cache_service.get_mech_display_cache_service",
            lambda: svc,
        )
        resp = main_app.test_client().get("/api/mech/display/info")
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert "File system error" in body["error"]


# ---- /api/mech/reset additional paths (action_logger error, errors) --------


class TestMechResetExtra:
    def test_action_logger_error_continues_to_success(
        self, main_app, monkeypatch
    ):
        """log_user_action raising shouldn't abort reset (lines 1472-1474)."""
        svc = MagicMock()
        svc.get_current_status.return_value = {"current_level": 5}
        svc.full_reset.return_value = SimpleNamespace(
            success=True,
            message="ok",
            details={
                "timestamp": "2025-01-01T00:00:00Z",
                "operations": [
                    "Donations: All donations cleared",
                    "Mech State: Mech state reset to Level 1",
                ],
            },
        )
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service",
            lambda: svc,
        )

        def _boom(**_kw):
            raise RuntimeError("logger broken")

        monkeypatch.setattr(
            "services.infrastructure.action_logger.log_user_action", _boom
        )
        resp = main_app.test_client().post(
            "/api/mech/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        # Allowlist-validated operations are returned
        assert "operations" in body
        assert "Donations: All donations cleared" in body["operations"]

    def test_value_error_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_current_status.side_effect = ValueError("bad data")
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service",
            lambda: svc,
        )
        resp = main_app.test_client().post(
            "/api/mech/reset", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]


# ---- /api/mech/status data error path (lines 1639-1643) --------------------


class TestMechStatusDataErrorPath:
    def test_value_error_returns_500(self, main_app, monkeypatch):
        svc = MagicMock()
        svc.get_current_status.side_effect = ValueError("parse fail")
        monkeypatch.setattr(
            "services.mech.mech_reset_service.get_mech_reset_service",
            lambda: svc,
        )
        resp = main_app.test_client().get(
            "/api/mech/status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False


# ===========================================================================
# log_routes.py
# ===========================================================================


@pytest.fixture
def log_app(monkeypatch):
    from app.blueprints.log_routes import log_bp

    return _build_app(log_bp, monkeypatch)


class TestLogRoutesGaps:
    """Hit the data-error branches and individual endpoint failure paths.

    The shared ContainerLogService factory is patched per-test. The route
    does ``from services.web.container_log_service import get_container_log_service``
    at runtime, so the monkeypatch path must target that module's
    ``get_container_log_service`` attribute.
    """

    def test_container_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_container_logs.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get(
            "/container_logs/web", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert b"Data error" in resp.data

    def test_bot_logs_failure_returns_status_code(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_filtered_logs.return_value = SimpleNamespace(
            success=False, content="", error="not found", status_code=404
        )
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get("/bot_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 404
        assert b"Failed to fetch bot logs" in resp.data

    def test_bot_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_filtered_logs.side_effect = TypeError("bad type")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get("/bot_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert b"Data error" in resp.data

    def test_discord_logs_runtime_error(self, log_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            _boom,
        )
        resp = log_app.test_client().get("/discord_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert b"Service error" in resp.data

    def test_discord_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_filtered_logs.side_effect = KeyError("missing")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get("/discord_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert b"Data error" in resp.data

    def test_webui_logs_runtime_error(self, log_app, monkeypatch):
        def _boom():
            raise AttributeError("missing dep")

        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            _boom,
        )
        resp = log_app.test_client().get("/webui_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert b"Service error" in resp.data

    def test_webui_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_filtered_logs.side_effect = ValueError("oops")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get("/webui_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert b"Data error" in resp.data

    def test_application_logs_runtime_error(self, log_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            _boom,
        )
        resp = log_app.test_client().get(
            "/application_logs", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert b"Service error" in resp.data

    def test_application_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_filtered_logs.side_effect = ValueError("oops")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get(
            "/application_logs", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert b"Data error" in resp.data

    def test_action_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_action_logs.side_effect = ValueError("oops")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get("/action_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert b"Data error" in resp.data

    def test_action_logs_json_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_action_logs.side_effect = ValueError("oops")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().get(
            "/action_logs_json", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False

    def test_clear_logs_data_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.clear_logs.side_effect = TypeError("bad type")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        resp = log_app.test_client().post(
            "/clear_logs", json={"log_type": "container"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False


# ===========================================================================
# security_routes.py
# ===========================================================================


@pytest.fixture
def security_app(monkeypatch):
    from app.blueprints.security_routes import security_bp

    return _build_app(security_bp, monkeypatch)


class TestSecurityDataErrorPaths:
    def test_token_status_value_error_returns_500_with_recommendations(
        self, security_app, monkeypatch
    ):
        svc = MagicMock()
        svc.get_token_security_status.side_effect = ValueError("bad data")
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/token-security-status", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert "Data error" in body["error"]
        assert "recommendations" in body
        assert body["token_exists"] is False

    def test_encrypt_token_value_error_returns_500(
        self, security_app, monkeypatch
    ):
        svc = MagicMock()
        svc.encrypt_token.side_effect = ValueError("encryption failed")
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().post(
            "/api/encrypt-token", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert "Data error" in body["error"]

    def test_migration_help_runtime_error_returns_500(
        self, security_app, monkeypatch
    ):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.security_service.get_security_service", _boom
        )
        resp = security_app.test_client().get(
            "/api/migration-help", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert "Service error" in body["error"]
        assert body["instructions"] == []

    def test_migration_help_value_error_returns_500(
        self, security_app, monkeypatch
    ):
        svc = MagicMock()
        svc.get_migration_help.side_effect = ValueError("oops")
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/migration-help", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert "Data error" in body["error"]

    def test_security_audit_runtime_error_returns_500(
        self, security_app, monkeypatch
    ):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.security_service.get_security_service", _boom
        )
        resp = security_app.test_client().get(
            "/api/security-audit", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert "Service error" in body["error"]

    def test_security_audit_value_error_returns_500(
        self, security_app, monkeypatch
    ):
        svc = MagicMock()
        svc.get_security_audit.side_effect = ValueError("oops")
        monkeypatch.setattr(
            "services.web.security_service.get_security_service", lambda: svc
        )
        resp = security_app.test_client().get(
            "/api/security-audit", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert "Data error" in body["error"]


# ===========================================================================
# tasks_bp.py
# ===========================================================================


@pytest.fixture
def tasks_app(monkeypatch):
    from app.blueprints.tasks_bp import tasks_bp

    return _build_app(tasks_bp, monkeypatch)


class TestTasksAddRoute:
    def test_add_no_body_returns_400(self, tasks_app):
        """POST with falsy JSON body -> 400 'No data provided' (line 23)."""
        # Send an explicit ``null`` JSON literal: Flask parses it as None
        # which the route treats as missing data, hitting the early-return.
        resp = tasks_app.test_client().post(
            "/tasks/add",
            data=b"null",
            headers={**_AUTH_HEADER, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "No data provided"

    def test_add_missing_cycle(self, tasks_app):
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"container": "web", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "Cycle" in resp.get_json()["error"]

    def test_add_missing_container(self, tasks_app):
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"cycle": "daily", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "Container" in resp.get_json()["error"]

    def test_add_missing_action(self, tasks_app):
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"cycle": "daily", "container": "web"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "Action" in resp.get_json()["error"]

    def test_add_success(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.add_task.return_value = SimpleNamespace(
            success=True, message="ok", task_data={"id": "t1"}, error=None
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"cycle": "daily", "container": "web", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["task"]["id"] == "t1"

    def test_add_service_failure_returns_400(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.add_task.return_value = SimpleNamespace(
            success=False, message=None, task_data=None, error="bad cycle"
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"cycle": "x", "container": "y", "action": "z"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_add_runtime_error_returns_500(self, tasks_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            _boom,
        )
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"cycle": "x", "container": "y", "action": "z"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert "Service error" in resp.get_json()["error"]

    def test_add_value_error_returns_500(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.add_task.side_effect = ValueError("bad fields")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().post(
            "/tasks/add",
            json={"cycle": "x", "container": "y", "action": "z"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]


class TestTasksListRoute:
    def test_list_failure_returns_500(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.list_tasks.return_value = SimpleNamespace(
            success=False, tasks=[], error="db down"
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().get("/tasks/list", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert "Failed to list tasks" in resp.get_json()["error"]

    def test_list_data_error_returns_500(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.list_tasks.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().get("/tasks/list", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]


class TestTasksFormRoute:
    """Cover lines 103-134 (show_task_form success / failure / error fallback)."""

    def test_form_success_renders(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.get_task_form_data.return_value = SimpleNamespace(
            success=True,
            form_data={
                "active_containers": ["a"],
                "timezone_str": "Europe/Berlin",
                "timezone_name": "CEST",
            },
            error=None,
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        monkeypatch.setattr(
            "app.blueprints.tasks_bp.render_template",
            lambda template, **kw: f"FORM_OK:{kw.get('timezone_name')}",
        )
        resp = tasks_app.test_client().get("/tasks/form", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"FORM_OK:CEST" in resp.data

    def test_form_failure_renders_fallback(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.get_task_form_data.return_value = SimpleNamespace(
            success=False, form_data={}, error="db down"
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        monkeypatch.setattr(
            "app.blueprints.tasks_bp.render_template",
            lambda template, **kw: f"FALLBACK:{kw.get('error_message')}",
        )
        resp = tasks_app.test_client().get("/tasks/form", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"FALLBACK:db down" in resp.data

    def test_form_runtime_error_renders_service_error(
        self, tasks_app, monkeypatch
    ):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            _boom,
        )
        monkeypatch.setattr(
            "app.blueprints.tasks_bp.render_template",
            lambda template, **kw: f"SVC_ERR:{kw.get('error_message')}",
        )
        resp = tasks_app.test_client().get("/tasks/form", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"Service error" in resp.data

    def test_form_value_error_renders_data_error(
        self, tasks_app, monkeypatch
    ):
        svc = MagicMock()
        svc.get_task_form_data.side_effect = ValueError("bad data")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        monkeypatch.setattr(
            "app.blueprints.tasks_bp.render_template",
            lambda template, **kw: f"DATA_ERR:{kw.get('error_message')}",
        )
        resp = tasks_app.test_client().get("/tasks/form", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"Data error" in resp.data


class TestTasksUpdateStatusRoute:
    def test_update_status_data_error_returns_500(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.update_task_status.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().post(
            "/tasks/update_status",
            json={"task_id": "t1", "is_active": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]

    def test_update_status_not_found_returns_404(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.update_task_status.return_value = SimpleNamespace(
            success=False, message=None, task_data=None,
            error="Task not found in store",
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().post(
            "/tasks/update_status",
            json={"task_id": "missing", "is_active": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 404


class TestTasksDeleteRoute:
    def test_delete_success(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.delete_task.return_value = SimpleNamespace(
            success=True, message="deleted", error=None
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().delete(
            "/tasks/delete/t1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_delete_not_found_returns_404(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.delete_task.return_value = SimpleNamespace(
            success=False, message=None, error="Task not found"
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().delete(
            "/tasks/delete/missing", headers=_AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_delete_runtime_error_returns_500(self, tasks_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            _boom,
        )
        resp = tasks_app.test_client().delete(
            "/tasks/delete/t1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_delete_value_error_returns_500(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.delete_task.side_effect = ValueError("bad id")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().delete(
            "/tasks/delete/t1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]


class TestTasksEditRoute:
    def test_edit_get_success(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.edit_task.return_value = SimpleNamespace(
            success=True, message=None, task_data={"id": "t1"}, error=None
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().get(
            "/tasks/edit/t1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json()["task"]["id"] == "t1"

    def test_edit_get_not_found_returns_404(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.edit_task.return_value = SimpleNamespace(
            success=False, message=None, task_data=None, error="Task not found"
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().get(
            "/tasks/edit/missing", headers=_AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_edit_put_no_data_returns_400(self, tasks_app, monkeypatch):
        svc = MagicMock()
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        # JSON ``null`` -> get_json() returns None -> route's early-return
        resp = tasks_app.test_client().put(
            "/tasks/edit/t1",
            data=b"null",
            headers={**_AUTH_HEADER, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "No data" in resp.get_json()["error"]

    def test_edit_put_success(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.edit_task.return_value = SimpleNamespace(
            success=True, message="updated", task_data={"id": "t1"}, error=None
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().put(
            "/tasks/edit/t1",
            json={"cycle": "daily", "timezone_str": "UTC"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_edit_put_not_found_returns_404(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.edit_task.return_value = SimpleNamespace(
            success=False, message=None, task_data=None, error="Task not found"
        )
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().put(
            "/tasks/edit/missing", json={"x": 1}, headers=_AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_edit_runtime_error_returns_500(self, tasks_app, monkeypatch):
        def _boom():
            raise RuntimeError("svc gone")

        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            _boom,
        )
        resp = tasks_app.test_client().get(
            "/tasks/edit/t1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500

    def test_edit_value_error_returns_500(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.edit_task.side_effect = ValueError("bad data")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        resp = tasks_app.test_client().get(
            "/tasks/edit/t1", headers=_AUTH_HEADER
        )
        assert resp.status_code == 500
        assert "Data error" in resp.get_json()["error"]
