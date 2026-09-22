# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package D1: channel file saving (D1-5), result classes (D1-7),
ConfigSaveError handling in the save service and route (D1-4), the scheduler interval
pre-fill (D1-8) and the DDC_ADMIN_PASSWORD bootstrap (D1-2).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask

from services.config.channel_config_service import ChannelConfigService
from services.exceptions import ConfigSaveError
from services.web.configuration_page_service import ConfigurationPageService
from services.web.configuration_save_service import (
    ConfigurationSaveRequest,
    ConfigurationSaveResult,
    ConfigurationSaveService,
    CriticalChanges,
)
from services.web.container_refresh_service import (
    ContainerRefreshRequest,
    ContainerRefreshResult,
    ContainerRefreshService,
)
from services.web.donation_tracking_service import (
    DonationClickRequest,
    DonationClickResult,
    DonationTrackingService,
)

VALID_CHANNEL_ID = "123456789012345678"
ANOTHER_VALID_ID = "987654321098765432"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_channel_service(tmp_path: Path) -> ChannelConfigService:
    """ChannelConfigService rooted at tmp_path (bypasses __init__ / the real config dir)."""
    svc = ChannelConfigService.__new__(ChannelConfigService)
    svc.base_dir = tmp_path
    svc.channels_dir = tmp_path / "config" / "channels"
    svc.config_file = tmp_path / "config" / "config.json"
    svc.channels_dir.mkdir(parents=True, exist_ok=True)
    return svc


# --------------------------------------------------------------------------- D1-5


class TestSaveAllChannels:

    def test_explicit_empty_save_removes_the_last_channel(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.save_channel(VALID_CHANNEL_ID, {"name": "last"})

        assert svc.save_all_channels({}, allow_empty=True) is True

        assert not (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()
        assert svc.get_all_channels() == {}
        assert json.loads(svc.config_file.read_text())["channel_permissions"] == {}

    def test_empty_save_without_flag_is_still_refused(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.save_channel(VALID_CHANNEL_ID, {"name": "kept"})

        assert svc.save_all_channels({}) is False
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

    def test_default_json_is_kept_and_does_not_fail_the_save(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        default_file = svc.channels_dir / "default.json"
        default_file.write_text(json.dumps({"commands": {"serverstatus": True}}))
        svc.save_channel(VALID_CHANNEL_ID, {"name": "old"})

        assert svc.save_all_channels({ANOTHER_VALID_ID: {"name": "new"}}) is True
        assert default_file.exists()
        assert not (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

        assert svc.save_all_channels({}, allow_empty=True) is True
        assert default_file.exists()


# --------------------------------------------------------------------------- D1-7


@pytest.mark.parametrize("result_cls", [ConfigurationSaveResult, ContainerRefreshResult, DonationClickResult])
def test_result_classes_can_be_built_without_message(result_cls):
    result = result_cls(success=False, error="boom")
    assert result.message == ""


def test_save_service_dependency_failure_returns_result(monkeypatch):
    monkeypatch.setattr(
        "services.config.config_service.get_config_service",
        MagicMock(side_effect=ImportError("config service gone")),
    )

    result = ConfigurationSaveService()._initialize_dependencies()

    assert result.success is False
    assert "config service gone" in result.error


def test_container_refresh_error_path_returns_result(monkeypatch):
    svc = ContainerRefreshService()
    monkeypatch.setattr(svc, "_initialize_dependencies", MagicMock(side_effect=RuntimeError("docker down")))

    result = svc.refresh_containers(ContainerRefreshRequest())

    assert result.success is False
    assert "docker down" in result.error


def test_donation_click_invalid_type_returns_result():
    result = DonationTrackingService().record_donation_click(
        DonationClickRequest(donation_type="bogus", request_object=None))

    assert result.success is False
    assert result.error


# --------------------------------------------------------------------------- D1-4


def _disk_full():
    return ConfigSaveError("Configuration save failed (I/O error): [Errno 28] No space left on device")


def test_save_service_turns_config_save_error_into_failure(monkeypatch):
    svc = ConfigurationSaveService()
    monkeypatch.setattr(svc, "_initialize_dependencies", lambda: ConfigurationSaveResult(success=True))
    monkeypatch.setattr(svc, "_process_configuration", lambda form: ({"language": "en"}, True, "ok"))
    # two arguments since 2026-09-22: the check is handed the config as it was BEFORE the write
    monkeypatch.setattr(svc, "_check_critical_changes", lambda data, before=None: CriticalChanges())
    monkeypatch.setattr(svc, "_save_server_order", lambda data: None)

    def failing_save(*args):
        raise _disk_full()

    monkeypatch.setattr(svc, "_save_configuration_files", failing_save)

    result = svc.save_configuration(ConfigurationSaveRequest(form_data={"language": ["en"]}))

    assert result.success is False
    assert "No space left on device" in result.error


@pytest.fixture
def main_app(monkeypatch):
    from app import auth as auth_module
    from app.blueprints.main_routes import main_bp

    monkeypatch.setattr(
        auth_module.auth, "verify_password_callback",
        lambda username, password: "admin" if username and password else None,
    )
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-audit-2026-09-d1")
    app.register_blueprint(main_bp)
    return app


def test_save_config_api_answers_config_save_error_with_json(main_app, monkeypatch):
    failing_service = MagicMock()
    failing_service.save_configuration.side_effect = _disk_full()
    monkeypatch.setattr(
        "services.web.configuration_save_service.get_configuration_save_service",
        lambda: failing_service,
    )
    headers = {
        "Authorization": "Basic " + base64.b64encode(b"admin:pw").decode(),
        "X-Requested-With": "XMLHttpRequest",
    }

    resp = main_app.test_client().post("/save_config_api", data={"language": "en"}, headers=headers)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is False
    assert "No space left on device" in body["message"]


# --------------------------------------------------------------------------- D1-8


def test_scheduler_interval_prefill_matches_scheduler_default(monkeypatch):
    monkeypatch.delenv("DDC_SCHEDULER_CHECK_INTERVAL", raising=False)
    svc = ConfigurationPageService.__new__(ConfigurationPageService)

    settings = svc._prepare_advanced_settings({})

    source = (REPO_ROOT / "services" / "scheduling" / "scheduler_service.py").read_text(encoding="utf-8")
    match = re.search(r"_get_config_value\('DDC_SCHEDULER_CHECK_INTERVAL',\s*'(\d+)'\)", source)
    assert match is not None
    assert settings["DDC_SCHEDULER_CHECK_INTERVAL"] == match.group(1) == "60"


def test_scheduler_interval_configured_value_still_wins(monkeypatch):
    monkeypatch.delenv("DDC_SCHEDULER_CHECK_INTERVAL", raising=False)
    svc = ConfigurationPageService.__new__(ConfigurationPageService)

    settings = svc._prepare_advanced_settings({"advanced_settings": {"DDC_SCHEDULER_CHECK_INTERVAL": 90}})

    assert settings["DDC_SCHEDULER_CHECK_INTERVAL"] == "90"


# --------------------------------------------------------------------------- D1-2


class TestAdminPasswordBootstrap:
    """set_initial_password_from_env() delegates to change_web_ui_password() (package C2,
    stubbed here with raising=False because it may not exist yet)."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("DDC_ADMIN_PASSWORD", "Bootstrap-Pass-1")
        monkeypatch.setattr(
            "services.config.config_service.load_config",
            lambda: {"web_ui_password_hash": None, "bot_token": "enc",
                     "bot_token_decrypted_for_usage": "plain-token"},
        )
        self.save_config = MagicMock()
        monkeypatch.setattr("services.config.config_service.save_config", self.save_config)

    def test_env_password_goes_through_change_helper(self, monkeypatch):
        import app.utils.web_helpers as wh
        calls = []
        monkeypatch.setattr("services.config.config_service.change_web_ui_password",
                            lambda pw, **kwargs: calls.append(pw), raising=False)

        wh.set_initial_password_from_env()

        assert calls == ["Bootstrap-Pass-1"]
        self.save_config.assert_not_called()

    @pytest.mark.parametrize("error", [ValueError("Password must be at least 12 characters."), _disk_full()])
    def test_helper_errors_are_logged_not_raised(self, monkeypatch, error):
        import app.utils.web_helpers as wh

        def failing_change(pw, **kwargs):
            raise error

        monkeypatch.setattr("services.config.config_service.change_web_ui_password",
                            failing_change, raising=False)

        wh.set_initial_password_from_env()  # must not raise

        self.save_config.assert_not_called()
