# -*- coding: utf-8 -*-
"""Spam settings are checked by the server, and every brake has a default.

THE FINDING (spam audit, 2026-09-26, F8/F9):

* ``POST /api/spam-protection`` stored whatever JSON arrived. The panel's
  number fields say 0-300, but only the browser read that: a cooldown of -5,
  of 10**9, of "abc" or of true went straight into channels_config.json - a
  negative or text cooldown then broke the comparison in is_on_cooldown, and
  a limit of 0 per minute refused every button.
* Two names the bot asks for had no default - "addadmin" (command) and
  "admin_overview_maintenance" (button) - so they braked by the silent
  five-second fallback.
* The 🔧 on a container's admin panel had no brake at all.

HOW THIS TEST CAN FAIL: it posts bad values (each must be refused and
nothing saved), an ordinary setting (must be saved), reads the defaults, and
presses the container 🔧 on a running cooldown.

COUNTER-CHECK (2026-09-26): red before on every bad value, on both defaults
and on the 🔧; the ordinary save green on both sides.
"""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"


def _basic():
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.json").write_text(json.dumps({"language": "en"}))
    (config / "tasks.json").write_text("[]")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config))
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    auth_limiter.ip_dict.clear()
    clear_credential_cache()

    saved = []
    service = MagicMock()
    service.save_config = lambda cfg: (saved.append(cfg) or MagicMock(success=True))
    monkeypatch.setattr("app.blueprints.main_routes.get_spam_protection_service", lambda: service)
    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}), saved
    auth_limiter.ip_dict.clear()


def _settings(**overrides):
    settings = {"global_settings": {"enabled": True, "cooldown_message": True,
                                    "log_violations": True, "max_commands_per_minute": 20,
                                    "max_buttons_per_minute": 30},
                "command_cooldowns": {"control": 5}, "button_cooldowns": {"info": 3}}
    for key, value in overrides.items():
        section, name = key.split("__")
        settings[section][name] = value
    return settings


def _save(app, settings):
    return app.test_client().post("/api/spam-protection", json=settings, headers=_basic())


@pytest.mark.parametrize("override", [
    {"command_cooldowns__control": -5},
    {"command_cooldowns__control": 10 ** 9},
    {"command_cooldowns__control": "abc"},
    {"button_cooldowns__info": True},
    {"global_settings__max_commands_per_minute": 0},
    {"global_settings__max_buttons_per_minute": 10 ** 6},
])
def test_a_bad_value_is_refused(panel, override):
    app, saved = panel
    answer = _save(app, _settings(**override))
    assert answer.status_code == 400, f"{override} was accepted"
    assert saved == [], f"{override} was written into the configuration"


def test_an_ordinary_setting_is_saved(panel):
    app, saved = panel
    assert _save(app, _settings()).status_code == 200
    assert len(saved) == 1


def test_every_brake_the_bot_asks_for_has_a_default():
    from services.infrastructure.spam_protection_service import SpamProtectionService

    defaults = SpamProtectionService._get_default_config(None)
    assert "addadmin" in defaults.command_cooldowns
    assert "admin_overview_maintenance" in defaults.button_cooldowns


def test_the_container_wrench_is_braked(monkeypatch):
    from cogs.watchdog_maintenance import ContainerMaintenanceButton

    spam = MagicMock()
    spam.is_enabled.return_value = True
    spam.is_on_cooldown.return_value = True
    spam.get_remaining_cooldown.return_value = 4.0
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr("cogs.watchdog_maintenance._may_pause", lambda *_a: True)
    monkeypatch.setattr("services.automation.maintenance.pauses",
                        MagicMock(side_effect=AssertionError("the pause list was read")))

    async def press():
        button = ContainerMaintenanceButton("vrising")
        interaction = MagicMock()
        interaction.user.id = 7
        interaction.response.send_message = AsyncMock()
        await button.callback(interaction)
        return interaction

    interaction = asyncio.run(press())
    text = str(interaction.response.send_message.await_args)
    assert "wait" in text.lower(), f"the 🔧 answered on a running cooldown: {text}"
