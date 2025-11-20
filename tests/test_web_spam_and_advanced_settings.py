# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from werkzeug.security import generate_password_hash

from app.web import create_app


@pytest.fixture
def auth_headers(monkeypatch):
    username = "tester"
    password = "s3cret"
    password_hash = generate_password_hash(password)

    # Ensure both the auth module and config service return the same credentials
    monkeypatch.setattr("app.auth.load_config", lambda: {
        "web_ui_user": username,
        "web_ui_password_hash": password_hash,
    })
    monkeypatch.setattr("services.config.config_service.load_config", lambda: {
        "web_ui_user": username,
        "web_ui_password_hash": password_hash,
    })

    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def isolated_web_app(monkeypatch, tmp_path, auth_headers):
    # Disable background services that spawn threads during tests
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")

    # Avoid touching the real filesystem or Docker when the app boots
    monkeypatch.setattr("app.utils.shared_data.load_active_containers_from_config", lambda: [])
    monkeypatch.setattr("app.utils.web_helpers.setup_action_logger", lambda app: None)

    # Only register the main blueprint to keep dependencies minimal
    def register_only_main_blueprint(app):
        from app.blueprints.main_routes import main_bp

        app.register_blueprint(main_bp)

    monkeypatch.setattr("app.web.blueprints.register_blueprints", register_only_main_blueprint)

    # Skip inline route registration that depends on additional services
    monkeypatch.setattr("app.web.routes.register_routes", lambda app: None)

    return create_app({"TESTING": True})


def test_spam_protection_routes_roundtrip(monkeypatch, isolated_web_app, auth_headers):
    from services.infrastructure import spam_protection_service as spam_module

    saved_payload = {}

    class StubSpamService:
        def __init__(self):
            self.saved_config = None

        def get_config(self):
            config = spam_module.SpamProtectionConfig.from_dict({
                "command_cooldowns": {"ping": 7},
                "button_cooldowns": {"info": 5},
                "global_settings": {
                    "enabled": True,
                    "max_commands_per_minute": 12,
                    "max_buttons_per_minute": 18,
                    "cooldown_message": True,
                    "log_violations": False,
                },
            })
            return spam_module.ServiceResult(success=True, data=config)

        def save_config(self, config):
            self.saved_config = config
            saved_payload.update(config.to_dict())
            return spam_module.ServiceResult(success=True, data=config)

    stub_service = StubSpamService()
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: stub_service,
    )
    monkeypatch.setattr(
        "app.blueprints.main_routes.get_spam_protection_service",
        lambda: stub_service,
    )

    # Capture audit log calls without invoking the real logger infrastructure
    logged_actions = []
    monkeypatch.setattr(
        "services.infrastructure.action_logger.log_user_action",
        lambda **kwargs: logged_actions.append(kwargs),
    )
    monkeypatch.setattr(
        "app.blueprints.main_routes.log_user_action",
        lambda **kwargs: logged_actions.append(kwargs),
    )

    client = isolated_web_app.test_client()

    response = client.get("/api/spam-protection", headers=auth_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["global_settings"]["enabled"] is True
    assert payload["command_cooldowns"] == {"ping": 7}
    assert payload["button_cooldowns"] == {"info": 5}

    new_settings = {
        "command_cooldowns": {"ping": 9, "help": 4},
        "button_cooldowns": {"info": 6, "logs": 8},
        "global_settings": {
            "enabled": False,
            "max_commands_per_minute": 20,
            "max_buttons_per_minute": 25,
            "cooldown_message": False,
            "log_violations": True,
        },
    }

    save_response = client.post("/api/spam-protection", json=new_settings, headers=auth_headers)
    assert save_response.status_code == 200
    assert save_response.get_json() == {"success": True}

    assert saved_payload == new_settings
    assert logged_actions == [
        {
            "action": "SAVE",
            "target": "Spam Protection Settings",
            "source": "Web UI",
            "details": "Spam protection enabled: False",
        }
    ]


def test_config_page_exposes_advanced_settings(monkeypatch, isolated_web_app, auth_headers):
    advanced_settings = {
        "DDC_DOCKER_CACHE_DURATION": "45",
        "DDC_DOCKER_QUERY_COOLDOWN": "3",
        "DDC_DOCKER_MAX_CACHE_AGE": "180",
        "DDC_ENABLE_BACKGROUND_REFRESH": "true",
        "DDC_BACKGROUND_REFRESH_INTERVAL": "15",
        "DDC_BACKGROUND_REFRESH_LIMIT": "25",
        "DDC_BACKGROUND_REFRESH_TIMEOUT": "20",
        "DDC_MAX_CONTAINERS_DISPLAY": "40",
        "DDC_SCHEDULER_CHECK_INTERVAL": "90",
        "DDC_MAX_CONCURRENT_TASKS": "4",
        "DDC_TASK_BATCH_SIZE": "6",
        "DDC_LIVE_LOGS_REFRESH_INTERVAL": "4",
        "DDC_LIVE_LOGS_MAX_REFRESHES": "10",
        "DDC_LIVE_LOGS_TAIL_LINES": "75",
        "DDC_LIVE_LOGS_TIMEOUT": "140",
        "DDC_LIVE_LOGS_ENABLED": "true",
        "DDC_LIVE_LOGS_AUTO_START": "false",
        "DDC_FAST_STATS_TIMEOUT": "8",
        "DDC_SLOW_STATS_TIMEOUT": "22",
        "DDC_CONTAINER_LIST_TIMEOUT": "18",
    }

    template_calls = []

    def fake_render(template_name, **context):
        template_calls.append((template_name, context))
        return "rendered"

    monkeypatch.setattr("app.blueprints.main_routes.render_template", fake_render)

    def fake_service_factory():
        class FakeService:
            def prepare_page_data(self, request):
                return SimpleNamespace(
                    success=True,
                    template_data={
                        "config": {
                            "env": advanced_settings,
                            "donation_disable_key": "",
                        },
                        "DEFAULT_CONFIG": {},
                        "donations_disabled": False,
                        "common_timezones": ["UTC"],
                        "current_timezone": "UTC",
                        "all_containers": [],
                        "configured_servers": [],
                        "active_container_names": [],
                        "container_info_data": {},
                        "cache_error": None,
                        "docker_status": {},
                        "docker_cache": {},
                        "last_cache_update": "never",
                        "formatted_timestamp": "20240101000000",
                        "auto_refresh_interval": 30,
                        "version_tag": "test",
                        "show_clear_logs_button": True,
                        "show_download_logs_button": True,
                        "tasks": [],
                    },
                )

        return FakeService()

    monkeypatch.setattr(
        "services.web.configuration_page_service.get_configuration_page_service",
        fake_service_factory,
    )

    client = isolated_web_app.test_client()
    response = client.get("/", headers=auth_headers)

    assert response.status_code == 200
    assert response.data == b"rendered"

    assert template_calls, "The config page should render a template with context"
    template_name, context = template_calls[-1]
    assert template_name == "config.html"
    assert context["config"]["env"] == advanced_settings
    assert context["config"]["env"]["DDC_ENABLE_BACKGROUND_REFRESH"] == "true"
    assert context["config"]["env"]["DDC_DOCKER_CACHE_DURATION"] == "45"
