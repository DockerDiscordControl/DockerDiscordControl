# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package D1-2 end to end: changing the Web UI password through the
config form with the real ConfigService and change_web_ui_password() (package C2),
against a throwaway config directory.
"""

from __future__ import annotations

import json

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import services.config.config_service as config_service_module
from services.config.config_form_parser_service import ConfigFormParserService
from services.config.config_service import ConfigService

OLD_PASSWORD = "Old-Password-123"
NEW_PASSWORD = "New-Password-456"
# Shaped like a Discord bot token (config_validation_service.looks_like_discord_token)
PLAIN_TOKEN = "MTA" + "a" * 21 + "." + "b" * 6 + "." + "c" * 27


@pytest.fixture
def isolated_config_service(tmp_path, monkeypatch):
    """A fresh ConfigService rooted at tmp_path, also returned by get_config_service()."""
    if not hasattr(config_service_module, "change_web_ui_password"):
        pytest.skip("change_web_ui_password (package C2) not available")

    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ConfigService, "_instance", None)
    svc = ConfigService()
    monkeypatch.setattr(config_service_module, "_config_service_instance", svc)
    # Channel files are not part of this test
    monkeypatch.setattr(ConfigFormParserService, "_save_channel_permissions", staticmethod(lambda perms: None))

    old_hash = generate_password_hash(OLD_PASSWORD, method="pbkdf2:sha256:600000")
    (tmp_path / "config.json").write_text(json.dumps({
        "language": "en",
        "web_ui_user": "admin",
        "web_ui_password_hash": old_hash,
        "bot_token": svc.encrypt_token(PLAIN_TOKEN, old_hash),
    }))
    return svc, tmp_path / "config.json"


def test_form_password_change_rehashes_and_keeps_token_usable(isolated_config_service):
    svc, config_file = isolated_config_service
    current = svc.get_config(force_reload=True)
    assert current["bot_token_decrypted_for_usage"] == PLAIN_TOKEN

    # What the page posts: the new password twice, plus the token field still holding the
    # value rendered before the change (encrypted with the old key).
    form = {
        "new_web_ui_password": NEW_PASSWORD,
        "confirm_web_ui_password": NEW_PASSWORD,
        "bot_token": current["bot_token"],
        "web_ui_user": "admin",
        "language": "de",
    }
    updated, success, message = ConfigFormParserService.process_config_form(form, current, svc)
    assert success is True, message

    # ConfigurationSaveService saves the processed config a second time; it must not revert.
    svc.save_config(updated)

    fresh = svc.get_config(force_reload=True)
    assert check_password_hash(fresh["web_ui_password_hash"], NEW_PASSWORD)
    assert not check_password_hash(fresh["web_ui_password_hash"], OLD_PASSWORD)
    assert fresh["bot_token_decrypted_for_usage"] == PLAIN_TOKEN
    assert fresh["language"] == "de"

    raw_text = config_file.read_text()
    raw = json.loads(raw_text)
    assert "new_web_ui_password" not in raw
    assert "confirm_web_ui_password" not in raw
    assert "bot_token_decrypted_for_usage" not in raw
    assert NEW_PASSWORD not in raw_text
    assert PLAIN_TOKEN not in raw_text


def test_too_short_password_is_rejected_by_the_real_helper(isolated_config_service):
    svc, config_file = isolated_config_service
    before = config_file.read_text()
    current = svc.get_config(force_reload=True)

    form = {"new_web_ui_password": "short", "confirm_web_ui_password": "short", "language": "de"}
    _, success, message = ConfigFormParserService.process_config_form(form, current, svc)

    assert success is False
    assert "Nothing was saved" in message
    assert config_file.read_text() == before
