# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package D1: ConfigFormParserService.process_config_form.

D1-2 password change, D1-3 catch-all field filter, D1-4 ConfigSaveError handling,
D1-5 explicit "zero channels" save, D1-6 duplicate channel IDs only warn.

change_web_ui_password() is package C2's helper in config_service; it is replaced by a
stub here (raising=False), so these tests don't depend on its implementation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import services.config.config_service as config_service_module
from services.config.config_form_parser_service import ConfigFormParserService
from services.exceptions import ConfigSaveError

VALID_CHANNEL_ID = "123456789012345678"
NEW_PASSWORD = "CorrectHorse-Battery9"


class FakeResult:
    def __init__(self, success=True, message="Configuration saved successfully"):
        self.success = success
        self.message = message


class FakeConfigService:
    """Stands in for ConfigService: records saves, serves a 'fresh' config on reload."""

    def __init__(self, fresh_config=None, save_exc=None):
        self.saved = []
        self.fresh_config = fresh_config or {}
        self.save_exc = save_exc
        self.reloads = 0

    def save_config(self, cfg):
        if self.save_exc is not None:
            raise self.save_exc
        self.saved.append(dict(cfg))
        return FakeResult()

    def get_config(self, force_reload=False):
        self.reloads += 1
        return dict(self.fresh_config)


@pytest.fixture
def channel_saves(monkeypatch):
    """Keep channel files out of the tests; record what would be saved."""
    calls = []
    # Returns True since 2026-09-20: the caller reads the result, and a falsy answer
    # means "the channel files were not written" (review B5).
    def _record(perms):
        calls.append(perms)
        return True

    monkeypatch.setattr(
        ConfigFormParserService, "_save_channel_permissions", staticmethod(_record),
    )
    return calls


@pytest.fixture
def password_changes(monkeypatch):
    """Stub for change_web_ui_password: rejects short passwords like the real helper."""
    calls = []

    def fake_change(new_password):
        if len(new_password) < 12:
            raise ValueError("Password must be at least 12 characters.")
        calls.append(new_password)

    monkeypatch.setattr(config_service_module, "change_web_ui_password", fake_change, raising=False)
    return calls


def _process(form, current_config, service):
    return ConfigFormParserService.process_config_form(form, current_config, service)


# --------------------------------------------------------------------------- D1-2


class TestPasswordChange:

    def test_new_password_is_changed_via_helper_and_never_persisted(self, channel_saves, password_changes):
        current = {"web_ui_password_hash": "old-hash", "bot_token": "enc-old"}
        fresh = {"web_ui_password_hash": "new-hash", "bot_token": "enc-new",
                 "bot_token_decrypted_for_usage": "plain-token"}
        service = FakeConfigService(fresh_config=fresh)
        form = {"new_web_ui_password": NEW_PASSWORD, "confirm_web_ui_password": NEW_PASSWORD,
                "language": "de"}

        updated, success, message = _process(form, current, service)

        assert success is True
        assert password_changes == [NEW_PASSWORD]
        saved = service.saved[-1]
        # The fresh hash / re-encrypted token are kept, not the stale values from before the change
        assert saved["web_ui_password_hash"] == "new-hash"
        assert saved["bot_token"] == "enc-new"
        for key in ("new_web_ui_password", "confirm_web_ui_password", "bot_token_decrypted_for_usage"):
            assert key not in saved
            assert key not in updated
        assert NEW_PASSWORD not in saved.values()
        assert saved["language"] == "de"
        assert "password changed" in message

    def test_stale_token_posted_with_new_password_does_not_undo_reencryption(self, channel_saves, password_changes):
        # The page renders bot_token encrypted with the OLD key and posts it back unchanged.
        current = {"web_ui_password_hash": "old-hash", "bot_token": "enc-old"}
        service = FakeConfigService(fresh_config={"web_ui_password_hash": "new-hash", "bot_token": "enc-new"})
        form = {"new_web_ui_password": NEW_PASSWORD, "confirm_web_ui_password": NEW_PASSWORD,
                "bot_token": "enc-old"}

        updated, success, _ = _process(form, current, service)

        assert success is True
        assert service.saved[-1]["bot_token"] == "enc-new"
        assert updated["bot_token"] == "enc-new"

    def test_blank_password_keeps_current_one(self, channel_saves, password_changes):
        service = FakeConfigService()
        form = {"new_web_ui_password": "", "confirm_web_ui_password": "", "language": "en"}

        _, success, _ = _process(form, {"web_ui_password_hash": "old-hash"}, service)

        assert success is True
        assert password_changes == []
        assert service.reloads == 0
        assert service.saved[-1]["web_ui_password_hash"] == "old-hash"

    def test_rejected_password_aborts_before_anything_is_written(self, channel_saves, password_changes):
        service = FakeConfigService()
        form = {"new_web_ui_password": "short", "confirm_web_ui_password": "short",
                "status_channel_id_1": VALID_CHANNEL_ID}

        _, success, message = _process(form, {"web_ui_password_hash": "old-hash"}, service)

        assert success is False
        assert "at least 12 characters" in message
        assert service.saved == []
        assert channel_saves == []

    def test_mismatched_confirmation_aborts(self, channel_saves, password_changes):
        service = FakeConfigService()
        form = {"new_web_ui_password": NEW_PASSWORD, "confirm_web_ui_password": NEW_PASSWORD + "x"}

        _, success, message = _process(form, {}, service)

        assert success is False
        assert "do not match" in message
        assert password_changes == []
        assert service.saved == []

    def test_plaintext_password_stored_by_older_versions_is_purged(self, channel_saves, password_changes):
        service = FakeConfigService()
        current = {"web_ui_password_hash": "h", "new_web_ui_password": "leaked-in-cleartext"}

        _process({"language": "en"}, current, service)

        assert "new_web_ui_password" not in service.saved[-1]


# --------------------------------------------------------------------------- D1-3


class TestCatchAllFilter:

    def test_protected_derived_and_junk_fields_are_ignored(self, channel_saves, password_changes):
        current = {"web_ui_password_hash": "real-hash", "web_ui_user": "admin", "bot_token": "enc"}
        service = FakeConfigService()
        form = {
            # protected / derived / structured
            "web_ui_password_hash": "attacker-hash",
            "web_ui_user": "evil",
            "bot_token_decrypted_for_usage": "x",
            "encrypted_bot_token": "x",
            "servers": "junk", "channel_permissions": "junk",
            "heartbeat": "junk", "advanced_settings": "junk",
            "csrf_token": "tok",
            # unnamed checkboxes are posted under an empty key
            "": "0",
            # task editor fields
            "container": "nginx", "action": "start", "cycle": "daily", "time": "10:00",
            "year": "2026", "month": "9", "day": "1", "weekday": "1", "cron_string": "* * * * *",
            "task_id": "t-1", "is_active": "1",
            # request option and container info (saved to containers/*.json separately)
            "config_split_enabled": "1",
            "info_protected_password_nginx": "secret", "info_enabled": "1",
            # legit settings
            "language": "de", "timezone": "Europe/Vienna", "timezone_str": "Europe/Vienna",
            "guild_id": "123456789012345678", "ui_language": "de",
        }

        updated, success, _ = _process(form, current, service)

        assert success is True
        saved = service.saved[-1]
        assert saved["web_ui_password_hash"] == "real-hash"
        assert saved["web_ui_user"] == "admin"
        assert saved["bot_token"] == "enc"
        for key in ("bot_token_decrypted_for_usage", "encrypted_bot_token", "csrf_token", "",
                    "container", "action", "cycle", "time", "year", "month", "day", "weekday",
                    "cron_string", "task_id", "is_active", "config_split_enabled",
                    "info_protected_password_nginx", "info_enabled"):
            assert key not in saved, key
        assert isinstance(saved["heartbeat"], dict)
        assert saved.get("servers") != "junk"
        assert saved.get("channel_permissions") != "junk"
        assert saved.get("advanced_settings") != "junk"
        assert saved["language"] == "de"
        assert saved["timezone"] == "Europe/Vienna"
        assert saved["timezone_str"] == "Europe/Vienna"  # read by cogs/status_handlers.py
        assert saved["guild_id"] == "123456789012345678"
        assert saved["ui_language"] == "de"

    def test_empty_bot_token_keeps_existing_token(self, channel_saves, password_changes):
        service = FakeConfigService()
        _process({"bot_token": "   "}, {"bot_token": "enc-token"}, service)
        assert service.saved[-1]["bot_token"] == "enc-token"

    def test_new_bot_token_is_still_accepted(self, channel_saves, password_changes):
        service = FakeConfigService()
        _process({"bot_token": " new.token.value "}, {"bot_token": "enc-token"}, service)
        assert service.saved[-1]["bot_token"] == "new.token.value"

    def test_loaded_decrypted_token_is_not_written_back(self, channel_saves, password_changes):
        service = FakeConfigService()
        current = {"bot_token": "enc", "bot_token_decrypted_for_usage": "plain-token"}
        _process({"language": "en"}, current, service)
        assert "bot_token_decrypted_for_usage" not in service.saved[-1]


# --------------------------------------------------------------------------- D1-4


def test_config_save_error_returns_clean_failure(channel_saves, password_changes):
    service = FakeConfigService(save_exc=ConfigSaveError(
        "Configuration save failed (I/O error): [Errno 28] No space left on device"))

    current = {"language": "en"}
    returned, success, message = _process({"language": "de"}, current, service)

    assert success is False
    assert "No space left on device" in message
    assert returned is current


# --------------------------------------------------------------------------- D1-5


class TestZeroChannels:

    def test_explicit_zero_channels_are_saved(self, channel_saves, password_changes):
        service = FakeConfigService()
        current = {"channel_permissions": {VALID_CHANNEL_ID: {"name": "old"}}}

        updated, success, _ = _process({"channel_tables_submitted": "1"}, current, service)

        assert success is True
        assert channel_saves == [{}]
        assert updated["channel_permissions"] == {}
        assert "channel_tables_submitted" not in service.saved[-1]

    def test_form_without_channel_tables_leaves_channels_alone(self, channel_saves, password_changes):
        service = FakeConfigService()
        current = {"channel_permissions": {VALID_CHANNEL_ID: {"name": "old"}}}

        updated, _, _ = _process({"language": "en"}, current, service)

        assert channel_saves == []
        assert updated["channel_permissions"] == {VALID_CHANNEL_ID: {"name": "old"}}

    @pytest.mark.parametrize("channels, allow_empty", [
        ({}, True),
        ({VALID_CHANNEL_ID: {"name": "x"}}, False),
    ])
    def test_empty_dict_is_passed_as_explicit_removal(self, monkeypatch, channels, allow_empty):
        channel_service = MagicMock()
        channel_service.save_all_channels.return_value = True
        monkeypatch.setattr(
            "services.config.channel_config_service.get_channel_config_service",
            lambda: channel_service,
        )

        ConfigFormParserService._save_channel_permissions(channels)

        channel_service.save_all_channels.assert_called_once_with(channels, allow_empty=allow_empty)


# --------------------------------------------------------------------------- D1-6


def test_duplicate_channel_ids_save_with_warning(channel_saves, password_changes):
    service = FakeConfigService()
    form = {"status_channel_id_1": VALID_CHANNEL_ID, "control_channel_id_1": VALID_CHANNEL_ID}

    updated, success, message = _process(form, {}, service)

    assert success is True
    assert "Warning" in message and VALID_CHANNEL_ID in message
    assert updated["channel_permissions"][VALID_CHANNEL_ID]["commands"]["control"] is True
