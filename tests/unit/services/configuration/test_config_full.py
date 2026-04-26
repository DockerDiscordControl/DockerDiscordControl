# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Full Config Services Unit Tests                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Functional unit tests for the DDC config services cluster.

Targets:
    * services.config.channel_config_service       (load/save/validate/permissions)
    * services.config.container_config_save_service (atomic save/delete)
    * services.config.config_form_parser_service   (form parsing)
    * services.config.config_service               (gap fill)
    * services.config.config_migration_service     (migration paths)
    * services.config.server_config_service        (server-list mgmt)

Notes:
    * Uses ``tmp_path`` only for isolation - no ``sys.modules`` manipulation.
    * Singletons are redirected by patching their internal Path attributes.
    * Werkzeug's MultiDict is used to simulate Flask form data faithfully.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
from werkzeug.datastructures import MultiDict

# ---------------------------------------------------------------------------
# Imports - SUTs
# ---------------------------------------------------------------------------
from services.config.channel_config_service import (
    ChannelConfigService,
    get_channel_config_service,
    reset_channel_config_service,
)
from services.config.container_config_save_service import (
    ContainerConfigSaveService,
    get_container_config_save_service,
    reset_container_config_save_service,
)
from services.config.config_form_parser_service import ConfigFormParserService
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import (
    ConfigService,
    GetConfigRequest,
    ValidateDonationKeyRequest,
    GetEvolutionModeRequest,
    get_config_service,
    load_config,
    save_config as legacy_save_config,
    update_config_fields as legacy_update_config_fields,
)
from services.config.config_loader_service import ConfigLoaderService
from services.config.server_config_service import (
    ServerConfigService,
    get_server_config_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CHANNEL_ID = "123456789012345678"   # 18 digits
ANOTHER_VALID_ID = "987654321098765432"   # 18 digits
SHORT_INVALID_ID = "12345"                 # too short


def _make_channel_service(tmp_path: Path) -> ChannelConfigService:
    """Construct a ChannelConfigService rooted at ``tmp_path``.

    Bypasses ``__init__`` so we don't depend on the real project root layout.
    Mirrors the production attribute set so all methods work as-is.
    """
    svc = ChannelConfigService.__new__(ChannelConfigService)
    svc.base_dir = tmp_path
    svc.channels_dir = tmp_path / "config" / "channels"
    svc.config_file = tmp_path / "config" / "config.json"
    svc.channels_dir.mkdir(parents=True, exist_ok=True)
    return svc


def _make_container_save_service(tmp_path: Path) -> ContainerConfigSaveService:
    svc = ContainerConfigSaveService.__new__(ContainerConfigSaveService)
    svc.base_dir = tmp_path
    svc.containers_dir = tmp_path / "config" / "containers"
    svc.containers_dir.mkdir(parents=True, exist_ok=True)
    return svc


def _redirect_config_service(service: ConfigService, config_dir: Path) -> ConfigService:
    """Point the singleton ConfigService at ``config_dir`` and refresh helpers."""
    service.config_dir = config_dir
    service.channels_dir = config_dir / "channels"
    service.containers_dir = config_dir / "containers"

    service.main_config_file = config_dir / "config.json"
    service.auth_config_file = config_dir / "auth.json"
    service.heartbeat_config_file = config_dir / "heartbeat.json"
    service.web_ui_config_file = config_dir / "web_ui.json"
    service.docker_settings_file = config_dir / "docker_settings.json"

    service.bot_config_file = config_dir / "bot_config.json"
    service.docker_config_file = config_dir / "docker_config.json"
    service.web_config_file = config_dir / "web_config.json"
    service.channels_config_file = config_dir / "channels_config.json"

    service._loader_service = ConfigLoaderService(
        service.config_dir,
        service.channels_dir,
        service.containers_dir,
        service.main_config_file,
        service.auth_config_file,
        service.heartbeat_config_file,
        service.web_ui_config_file,
        service.docker_settings_file,
        service.bot_config_file,
        service.docker_config_file,
        service.web_config_file,
        service.channels_config_file,
        service._load_json_file,
        service._validation_service,
    )

    service._cache_service.invalidate_cache()
    service._cache_service.clear_token_cache()
    return service


# ---------------------------------------------------------------------------
# ChannelConfigService
# ---------------------------------------------------------------------------

class TestChannelConfigService:
    """Tests for ChannelConfigService - manages /config/channels/*.json."""

    def test_save_and_get_channel_roundtrip(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        cfg = {"name": "Status", "commands": {"serverstatus": True}}

        assert svc.save_channel(VALID_CHANNEL_ID, cfg) is True

        loaded = svc.get_channel(VALID_CHANNEL_ID)
        assert loaded == cfg

    def test_save_rejects_invalid_channel_id(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        assert svc.save_channel(SHORT_INVALID_ID, {"name": "x"}) is False
        # Nothing should have been written.
        assert list(svc.channels_dir.glob("*.json")) == []

    def test_save_rejects_path_traversal_via_id(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # `..` characters are not digits => fails the strict 17-19 digit check.
        assert svc.save_channel("../etc/passwd", {}) is False

    def test_get_channel_returns_none_for_missing(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        assert svc.get_channel(VALID_CHANNEL_ID) is None

    def test_get_channel_rejects_invalid_id(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        assert svc.get_channel("not-a-snowflake") is None

    def test_delete_channel_removes_file(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.save_channel(VALID_CHANNEL_ID, {"name": "x"})
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

        assert svc.delete_channel(VALID_CHANNEL_ID) is True
        assert not (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

    def test_delete_channel_rejects_invalid_id(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        assert svc.delete_channel("../bad") is False

    def test_delete_missing_channel_succeeds(self, tmp_path):
        # Idempotent delete: returns True if the file is already absent.
        svc = _make_channel_service(tmp_path)
        assert svc.delete_channel(VALID_CHANNEL_ID) is True

    def test_get_all_channels_skips_invalid_filename_without_id(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # File whose name is not a Discord ID and whose body has no valid id either.
        bad = svc.channels_dir / "Control.json"
        bad.write_text(json.dumps({"name": "Some Label", "commands": {}}))

        result = svc.get_all_channels()
        assert result == {}

    def test_get_all_channels_auto_migrates_via_channel_id_field(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # Filename is invalid, but the body's `channel_id` is a valid Snowflake.
        bad = svc.channels_dir / "ControlChannel.json"
        bad.write_text(json.dumps({
            "channel_id": VALID_CHANNEL_ID,
            "name": "Control",
        }))

        result = svc.get_all_channels()
        assert VALID_CHANNEL_ID in result
        # File should have been renamed to <id>.json.
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()
        assert not bad.exists()

    def test_get_all_channels_handles_invalid_json(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # A correctly-named file, but with corrupt content.
        bad = svc.channels_dir / f"{VALID_CHANNEL_ID}.json"
        bad.write_text("{ not valid json")
        # Should not raise; just logs and returns empty dict.
        assert svc.get_all_channels() == {}

    def test_get_all_channels_loads_multiple(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.save_channel(VALID_CHANNEL_ID, {"name": "A"})
        svc.save_channel(ANOTHER_VALID_ID, {"name": "B"})

        result = svc.get_all_channels()
        assert set(result.keys()) == {VALID_CHANNEL_ID, ANOTHER_VALID_ID}

    def test_save_all_channels_writes_and_deletes(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # Pre-existing channel that should be removed by save_all_channels.
        svc.save_channel(VALID_CHANNEL_ID, {"name": "old"})

        new_channels = {ANOTHER_VALID_ID: {"name": "new"}}
        assert svc.save_all_channels(new_channels) is True

        assert (svc.channels_dir / f"{ANOTHER_VALID_ID}.json").exists()
        assert not (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

    def test_save_all_channels_refuses_to_delete_when_empty_input(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.save_channel(VALID_CHANNEL_ID, {"name": "old"})

        # Empty dict should NOT wipe the existing file (safety guard).
        assert svc.save_all_channels({}) is False
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

    def test_save_channel_updates_main_config(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.config_file.parent.mkdir(parents=True, exist_ok=True)
        # Pre-seed with some unrelated setting.
        svc.config_file.write_text(json.dumps({"language": "de"}))

        svc.save_channel(VALID_CHANNEL_ID, {"name": "Status"})

        data = json.loads(svc.config_file.read_text())
        assert data["language"] == "de"
        assert VALID_CHANNEL_ID in data["channel_permissions"]

    def test_remove_from_main_config_on_delete(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.save_channel(VALID_CHANNEL_ID, {"name": "x"})

        svc.delete_channel(VALID_CHANNEL_ID)

        data = json.loads(svc.config_file.read_text())
        assert VALID_CHANNEL_ID not in data.get("channel_permissions", {})

    def test_sync_from_main_config(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        svc.config_file.parent.mkdir(parents=True, exist_ok=True)
        svc.config_file.write_text(json.dumps({
            "channel_permissions": {
                VALID_CHANNEL_ID: {"name": "fromMain"},
                ANOTHER_VALID_ID: {"name": "alsoMain"},
            }
        }))

        assert svc.sync_from_main_config() is True
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()
        assert (svc.channels_dir / f"{ANOTHER_VALID_ID}.json").exists()

    def test_sync_from_main_config_with_no_file(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # config.json doesn't exist - should still succeed.
        assert svc.sync_from_main_config() is True

    def test_get_all_channels_extracts_id_from_name_field(self, tmp_path):
        """If body's `name` is itself a Snowflake, it's used as the id."""
        svc = _make_channel_service(tmp_path)
        bad = svc.channels_dir / "Misnamed.json"
        bad.write_text(json.dumps({"name": VALID_CHANNEL_ID}))

        result = svc.get_all_channels()
        assert VALID_CHANNEL_ID in result

    def test_save_all_channels_failure_path_for_invalid_id(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        # Mix valid + invalid ids.
        result = svc.save_all_channels({
            VALID_CHANNEL_ID: {"name": "ok"},
            "BOGUS": {"name": "bad"},
        })
        # Returns False because at least one failed to save.
        assert result is False
        # The valid one was still saved.
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()

    def test_is_valid_discord_id_edge_cases(self, tmp_path):
        svc = _make_channel_service(tmp_path)
        assert svc._is_valid_discord_id("12345678901234567") is True   # 17 digits
        assert svc._is_valid_discord_id("1234567890123456789") is True  # 19 digits
        assert svc._is_valid_discord_id("1234567890123456") is False   # 16 digits
        assert svc._is_valid_discord_id("12345678901234567890") is False  # 20 digits
        assert svc._is_valid_discord_id("abc") is False
        assert svc._is_valid_discord_id("") is False
        assert svc._is_valid_discord_id(None) is False  # type: ignore

    def test_singleton_helper_returns_same_instance(self, tmp_path, monkeypatch):
        # ChannelConfigService.__init__ derives its base_dir from
        # Path(__file__).parents[2] which on this dev box points at the
        # SMB-mounted project root with permission-restricted ``config/``.
        # Force the constructor to use tmp_path instead.
        from services.config import channel_config_service as ccs_mod
        original_init = ccs_mod.ChannelConfigService.__init__

        def patched_init(self):
            self.base_dir = tmp_path
            self.channels_dir = tmp_path / "config" / "channels"
            self.config_file = tmp_path / "config" / "config.json"
            self.channels_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(ccs_mod.ChannelConfigService, "__init__", patched_init)
        reset_channel_config_service()
        try:
            a = get_channel_config_service()
            b = get_channel_config_service()
            assert a is b
        finally:
            reset_channel_config_service()
            monkeypatch.setattr(ccs_mod.ChannelConfigService, "__init__", original_init)


# ---------------------------------------------------------------------------
# ContainerConfigSaveService
# ---------------------------------------------------------------------------

class TestContainerConfigSaveService:
    """Tests for ContainerConfigSaveService - atomic /config/containers/*.json writes."""

    def test_save_writes_json_atomically(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        cfg = {"docker_name": "nginx", "active": True, "order": 1}

        assert svc.save_container_config("nginx", cfg) is True

        path = svc.containers_dir / "nginx.json"
        assert path.exists()
        assert json.loads(path.read_text()) == cfg
        # No leftover .tmp files.
        assert list(svc.containers_dir.glob("*.tmp")) == []

    def test_save_rejects_invalid_name(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        # The safe-name regex rejects `..` paths; service raises ValueError
        # because the catch list does NOT include ValueError.
        with pytest.raises(ValueError):
            svc.save_container_config("../escape", {"x": 1})
        assert list(svc.containers_dir.glob("*.json")) == []

    def test_save_rejects_path_traversal(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        with pytest.raises(ValueError):
            svc.save_container_config("foo/bar", {})

    def test_save_rejects_dotfile_name(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        # Must start with alphanumeric per regex.
        with pytest.raises(ValueError):
            svc.save_container_config(".hidden", {})

    def test_save_overwrites_existing(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        svc.save_container_config("nginx", {"v": 1})
        svc.save_container_config("nginx", {"v": 2})

        loaded = json.loads((svc.containers_dir / "nginx.json").read_text())
        assert loaded == {"v": 2}

    def test_delete_existing_container(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        svc.save_container_config("nginx", {"v": 1})
        assert (svc.containers_dir / "nginx.json").exists()

        assert svc.delete_container_config("nginx") is True
        assert not (svc.containers_dir / "nginx.json").exists()

    def test_delete_missing_returns_true(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        # Idempotent; returns True even if nothing to delete.
        assert svc.delete_container_config("ghost") is True

    def test_delete_rejects_invalid_name(self, tmp_path):
        svc = _make_container_save_service(tmp_path)
        # Same as save: ValueError propagates from _validate_path_safety
        # because delete's except clause doesn't list ValueError.
        with pytest.raises(ValueError):
            svc.delete_container_config("../bad")

    def test_save_handles_unserializable_data(self, tmp_path):
        """A non-JSON-serializable value triggers the broad except clause."""
        svc = _make_container_save_service(tmp_path)

        class NotJsonable:
            pass

        # TypeError from json.dump is NOT caught (only IOError/OSError/etc.).
        # We just verify the function returns False or raises - both indicate
        # save failure handled within the catch list.
        try:
            result = svc.save_container_config("nginx", {"bad": NotJsonable()})
            assert result is False
        except TypeError:
            # Acceptable: TypeError isn't in the except list, so it propagates.
            # This still exercises the cleanup path on the error branch.
            pass

    def test_singleton_helper(self, tmp_path, monkeypatch):
        # Like ChannelConfigService, ContainerConfigSaveService.__init__
        # derives base_dir from __file__.parents[2]. Redirect __init__ to
        # a tmp-path so the singleton constructor doesn't blow up on the
        # SMB-mounted dev project root.
        from services.config import container_config_save_service as mod

        original_init = mod.ContainerConfigSaveService.__init__

        def patched_init(self):
            self.base_dir = tmp_path
            self.containers_dir = tmp_path / "config" / "containers"
            self.containers_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(mod.ContainerConfigSaveService, "__init__", patched_init)
        reset_container_config_save_service()
        try:
            a = get_container_config_save_service()
            b = get_container_config_save_service()
            assert a is b
        finally:
            reset_container_config_save_service()
            monkeypatch.setattr(mod.ContainerConfigSaveService, "__init__", original_init)

    def test_save_cleans_up_temp_file_on_failure(self, tmp_path, monkeypatch):
        """Verify the temp-file cleanup branch executes on a write error."""
        svc = _make_container_save_service(tmp_path)

        # Force os.fsync to fail so the cleanup branch runs.
        import services.config.container_config_save_service as ccss
        original_fsync = ccss.os.fsync

        def boom(_):
            raise OSError("synthetic fsync failure")

        monkeypatch.setattr(ccss.os, "fsync", boom)
        try:
            result = svc.save_container_config("nginx", {"x": 1})
            # Save fails, but no exception escapes.
            assert result is False
        finally:
            monkeypatch.setattr(ccss.os, "fsync", original_fsync)

        # Temp file should have been cleaned up.
        assert list(svc.containers_dir.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# ConfigFormParserService
# ---------------------------------------------------------------------------

class TestConfigFormParserService:
    """Tests for ConfigFormParserService - parses Web-UI form submissions."""

    def test_parse_servers_basic(self):
        form = MultiDict([
            ("selected_servers", "nginx"),
            ("display_name_nginx", "NGINX Web"),
            ("allow_status_nginx", "on"),
            ("allow_start_nginx", "on"),
            ("order_nginx", "5"),
        ])
        servers = ConfigFormParserService.parse_servers_from_form(form)
        assert len(servers) == 1
        s = servers[0]
        assert s["docker_name"] == "nginx"
        assert s["display_name"] == "NGINX Web"
        assert "status" in s["allowed_actions"]
        assert "start" in s["allowed_actions"]
        assert "stop" not in s["allowed_actions"]
        assert s["order"] == 5

    def test_parse_servers_multiple(self):
        form = MultiDict([
            ("selected_servers", "nginx"),
            ("selected_servers", "mysql"),
            ("allow_status_nginx", "1"),
            ("allow_restart_mysql", "true"),
            ("order_nginx", "1"),
            ("order_mysql", "2"),
        ])
        servers = ConfigFormParserService.parse_servers_from_form(form)
        names = [s["docker_name"] for s in servers]
        assert names == ["nginx", "mysql"]

    def test_parse_servers_dedupe(self):
        form = MultiDict([
            ("selected_servers", "nginx"),
            ("selected_servers", "nginx"),
        ])
        servers = ConfigFormParserService.parse_servers_from_form(form)
        assert len(servers) == 1

    def test_parse_servers_invalid_order_falls_back_to_999(self):
        form = MultiDict([
            ("selected_servers", "nginx"),
            ("order_nginx", "not-a-number"),
        ])
        servers = ConfigFormParserService.parse_servers_from_form(form)
        assert servers[0]["order"] == 999

    def test_parse_servers_skips_empty_name(self):
        form = MultiDict([
            ("selected_servers", ""),
            ("selected_servers", "nginx"),
        ])
        servers = ConfigFormParserService.parse_servers_from_form(form)
        assert len(servers) == 1
        assert servers[0]["docker_name"] == "nginx"

    def test_parse_servers_empty_form(self):
        assert ConfigFormParserService.parse_servers_from_form(MultiDict()) == []

    def test_parse_display_name_from_stringified_list(self):
        result = ConfigFormParserService._parse_display_name(
            "['Pretty Name', 'Other']", fallback="x"
        )
        assert result == "Pretty Name"

    def test_parse_display_name_fallback_when_empty(self):
        assert ConfigFormParserService._parse_display_name("", "fallback") == "fallback"

    def test_parse_display_name_from_actual_list(self):
        # Form data sometimes arrives as a real Python list.
        assert ConfigFormParserService._parse_display_name(["First", "Second"], "fb") == "First"

    def test_parse_form_checkbox_truthy_variants(self):
        for val in ("1", "on", "true", "True", True):
            form = {"k": val}
            assert ConfigFormParserService._parse_form_checkbox(form, "k") is True

    def test_parse_form_checkbox_false_when_missing(self):
        assert ConfigFormParserService._parse_form_checkbox({}, "missing") is False

    def test_parse_channel_permissions_status_and_control(self):
        form = MultiDict([
            ("status_channel_id_1", VALID_CHANNEL_ID),
            ("status_channel_name_1", "Status Room"),
            ("status_post_initial_1", "on"),
            ("status_enable_auto_refresh_1", "on"),
            ("status_update_interval_minutes_1", "10"),
            ("control_channel_id_1", ANOTHER_VALID_ID),
            ("control_channel_name_1", "Control Room"),
        ])
        result = ConfigFormParserService.parse_channel_permissions_from_form(form)
        assert VALID_CHANNEL_ID in result
        assert ANOTHER_VALID_ID in result
        assert result[VALID_CHANNEL_ID]["name"] == "Status Room"
        assert result[VALID_CHANNEL_ID]["post_initial"] is True
        # Status channels grant only basic commands.
        assert result[VALID_CHANNEL_ID]["commands"]["control"] is False
        # Control channels grant full commands.
        assert result[ANOTHER_VALID_ID]["commands"]["control"] is True
        assert result[VALID_CHANNEL_ID]["update_interval_minutes"] == 10

    def test_parse_channels_skips_invalid_id(self):
        form = MultiDict([
            ("status_channel_id_1", "12345"),  # too short -> skipped
            ("status_channel_id_2", VALID_CHANNEL_ID),
        ])
        result = ConfigFormParserService.parse_channel_permissions_from_form(form)
        assert VALID_CHANNEL_ID in result
        assert "12345" not in result

    def test_parse_channels_handles_gaps(self):
        # Row 1 deleted (empty), but row 3 is populated.
        form = MultiDict([
            ("status_channel_id_1", ""),
            ("status_channel_id_3", VALID_CHANNEL_ID),
        ])
        result = ConfigFormParserService.parse_channel_permissions_from_form(form)
        assert VALID_CHANNEL_ID in result

    def test_parse_channels_empty_form(self):
        assert ConfigFormParserService.parse_channel_permissions_from_form(MultiDict()) == {}

    def test_parse_heartbeat_enabled(self):
        form = {
            "heartbeat_ping_url": "https://hc-ping.example/abc",
            "heartbeat_interval": "10",
        }
        hb = ConfigFormParserService._parse_heartbeat(form)
        assert hb == {"enabled": True, "ping_url": "https://hc-ping.example/abc", "interval": 10}

    def test_parse_heartbeat_clamps_interval(self):
        # Out-of-range values should clamp to [1,60].
        form = {"heartbeat_ping_url": "https://x.com/y", "heartbeat_interval": "9999"}
        hb = ConfigFormParserService._parse_heartbeat(form)
        assert hb["interval"] == 60

    def test_parse_heartbeat_rejects_non_https(self):
        # http (no s) URLs are dropped for security.
        form = {"heartbeat_ping_url": "http://insecure.example/x", "heartbeat_interval": "5"}
        hb = ConfigFormParserService._parse_heartbeat(form)
        assert hb["enabled"] is False

    def test_parse_heartbeat_disabled_by_default(self):
        hb = ConfigFormParserService._parse_heartbeat({})
        assert hb["enabled"] is False
        assert hb["ping_url"] == ""

    def test_process_config_form_full_payload(self, monkeypatch):
        """Drive the top-level form processor with a realistic payload."""
        captured = {}

        class FakeResult:
            def __init__(self, success=True, message="ok"):
                self.success = success
                self.message = message

        class FakeConfigService:
            def save_config(self, cfg):
                captured["cfg"] = cfg
                return FakeResult(success=True, message="saved")

        # _save_channel_permissions calls into the channel service singleton.
        # We patch it out so the test stays self-contained.
        monkeypatch.setattr(
            ConfigFormParserService, "_save_channel_permissions",
            staticmethod(lambda perms: None),
        )

        form = MultiDict([
            ("selected_servers", "nginx"),
            ("allow_status_nginx", "on"),
            ("status_channel_id_1", VALID_CHANNEL_ID),
            ("status_channel_name_1", "Status"),
            ("language", "de"),
            ("guild_id", "99999"),
            ("heartbeat_ping_url", "https://hc.example/x"),
            ("heartbeat_interval", "7"),
        ])

        updated, success, message = ConfigFormParserService.process_config_form(
            form, current_config={"existing_key": "kept"}, config_service=FakeConfigService()
        )

        assert success is True
        assert message == "saved"
        # Servers parsed.
        assert any(s["docker_name"] == "nginx" for s in updated["servers"])
        # Channel permissions parsed and stored.
        assert VALID_CHANNEL_ID in updated["channel_permissions"]
        # Other scalar fields passed through.
        assert updated["language"] == "de"
        assert updated["guild_id"] == "99999"
        # Heartbeat parsed.
        assert updated["heartbeat"]["enabled"] is True
        # Existing keys preserved.
        assert updated["existing_key"] == "kept"
        # Skip prefixes/keys NOT bled into top-level config.
        assert "selected_servers" not in updated
        assert "status_channel_id_1" not in updated
        # config_service.save_config was actually invoked with the merged dict.
        assert captured["cfg"]["language"] == "de"

    def test_process_config_form_handles_save_failure(self, monkeypatch):
        class FakeResult:
            success = False
            message = "boom"

        class FakeConfigService:
            def save_config(self, cfg):
                return FakeResult()

        monkeypatch.setattr(
            ConfigFormParserService, "_save_channel_permissions",
            staticmethod(lambda perms: None),
        )

        _, success, message = ConfigFormParserService.process_config_form(
            MultiDict([("selected_servers", "x")]),
            current_config={},
            config_service=FakeConfigService(),
        )
        assert success is False
        assert message == "boom"


# ---------------------------------------------------------------------------
# ConfigMigrationService
# ---------------------------------------------------------------------------

class TestConfigMigrationService:
    """Tests for ConfigMigrationService - legacy -> modular migration paths."""

    def _make(self, tmp_path: Path) -> ConfigMigrationService:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        return ConfigMigrationService(
            config_dir=config_dir,
            channels_dir=config_dir / "channels",
            containers_dir=config_dir / "containers",
        )

    def _save_json(self, path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def _load_json(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            return json.loads(path.read_text())
        except Exception:
            return dict(default)

    def test_needs_migration_true_when_legacy_present(self, tmp_path):
        svc = self._make(tmp_path)
        # Create a legacy file with no modular structure yet.
        self._save_json(svc.channels_config_file, {"channel_permissions": {}})
        assert svc.needs_real_modular_migration() is True

    def test_needs_migration_false_when_modular_exists(self, tmp_path):
        svc = self._make(tmp_path)
        self._save_json(svc.channels_config_file, {"channel_permissions": {}})
        # Create a real modular container file - should now skip migration.
        svc.containers_dir.mkdir(parents=True, exist_ok=True)
        (svc.containers_dir / "x.json").write_text("{}")
        assert svc.needs_real_modular_migration() is False

    def test_create_modular_directories(self, tmp_path):
        svc = self._make(tmp_path)
        svc.create_modular_directories()
        assert svc.channels_dir.is_dir()
        assert svc.containers_dir.is_dir()

    def test_migrate_channels_to_files(self, tmp_path):
        svc = self._make(tmp_path)
        svc.create_modular_directories()
        self._save_json(svc.channels_config_file, {
            "channel_permissions": {
                VALID_CHANNEL_ID: {"name": "Status", "commands": {}},
                ANOTHER_VALID_ID: {"name": "Control", "commands": {}},
                "BOGUS": {"name": "skip me"},  # invalid id - skipped
            }
        })
        svc.migrate_channels_to_files(self._load_json, self._save_json)

        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()
        assert (svc.channels_dir / f"{ANOTHER_VALID_ID}.json").exists()
        # Default file is always created.
        assert (svc.channels_dir / "default.json").exists()
        # Bad id was skipped.
        assert not (svc.channels_dir / "BOGUS.json").exists()

    def test_migrate_containers_to_files(self, tmp_path):
        svc = self._make(tmp_path)
        svc.create_modular_directories()
        self._save_json(svc.docker_config_file, {
            "servers": [
                {"docker_name": "nginx", "active": True},
                {"name": "mysql", "active": False},
                {"docker_name": "../bad"},  # invalid - skipped
            ],
            "docker_socket_path": "/tmp/sock",
            "container_command_cooldown": 7,
        })
        svc.migrate_containers_to_files(self._load_json, self._save_json)

        assert (svc.containers_dir / "nginx.json").exists()
        assert (svc.containers_dir / "mysql.json").exists()
        assert not (svc.containers_dir / "../bad.json").exists()

        # docker_settings.json is created with extracted values.
        settings = json.loads(svc.docker_settings_file.read_text())
        assert settings["docker_socket_path"] == "/tmp/sock"
        assert settings["container_command_cooldown"] == 7

    def test_migrate_system_configs_to_files(self, tmp_path):
        svc = self._make(tmp_path)
        self._save_json(svc.bot_config_file, {
            "language": "fr",
            "timezone": "Europe/Paris",
            "guild_id": "42",
            "bot_token": "abc",
        })
        svc.migrate_system_configs_to_files(self._load_json, self._save_json)

        main = json.loads(svc.main_config_file.read_text())
        assert main["language"] == "fr"
        assert main["timezone"] == "Europe/Paris"
        assert main["guild_id"] == "42"
        assert main["heartbeat"]["enabled"] is False

        auth = json.loads(svc.auth_config_file.read_text())
        assert auth["bot_token"] == "abc"
        assert auth["encryption_enabled"] is True

    def test_migrate_web_configs_to_files(self, tmp_path):
        svc = self._make(tmp_path)
        self._save_json(svc.web_config_file, {
            "web_ui_user": "tester",
            "web_ui_password_hash": "hash",
            "session_timeout": 1234,
        })
        svc.migrate_web_configs_to_files(self._load_json, self._save_json)

        ui = json.loads(svc.web_ui_config_file.read_text())
        assert ui["web_ui_user"] == "tester"
        assert ui["web_ui_password_hash"] == "hash"
        assert ui["session_timeout"] == 1234

    def test_create_migration_backup_copies_files(self, tmp_path):
        svc = self._make(tmp_path)
        self._save_json(svc.bot_config_file, {"x": 1})
        svc.create_migration_backup()

        # A backup directory was created with the timestamp prefix.
        backups = [d for d in svc.config_dir.iterdir()
                   if d.is_dir() and d.name.startswith("backup_")]
        assert len(backups) == 1
        assert (backups[0] / "bot_config.json").exists()

    def test_cleanup_legacy_files(self, tmp_path):
        svc = self._make(tmp_path)
        # Touch a few legacy files.
        for name in ("bot_config.json", "docker_config.json", "channels_config.json"):
            (svc.config_dir / name).write_text("{}")
        svc.cleanup_legacy_files_after_migration()
        for name in ("bot_config.json", "docker_config.json", "channels_config.json"):
            assert not (svc.config_dir / name).exists()

    def test_ensure_modular_structure_skips_when_not_needed(self, tmp_path):
        """If no legacy files exist, no migration runs."""
        svc = self._make(tmp_path)
        # No legacy files => needs_real_modular_migration() is False.
        called = {"perform": False}

        original_perform = svc.perform_real_modular_migration

        def spy(load_fn, save_fn):
            called["perform"] = True
            original_perform(load_fn, save_fn)

        svc.perform_real_modular_migration = spy
        svc.ensure_modular_structure(self._load_json, self._save_json)
        assert called["perform"] is False

    def test_ensure_modular_structure_runs_when_needed(self, tmp_path):
        """Legacy file present + no modular dir -> migration runs end-to-end."""
        svc = self._make(tmp_path)
        # Drop a legacy channels_config.json so migration is required.
        self._save_json(svc.channels_config_file, {
            "channel_permissions": {VALID_CHANNEL_ID: {"name": "x", "commands": {}}}
        })
        svc.ensure_modular_structure(self._load_json, self._save_json)
        # After migration, individual channel files exist.
        assert (svc.channels_dir / f"{VALID_CHANNEL_ID}.json").exists()
        # And the legacy file was cleaned up.
        assert not svc.channels_config_file.exists()

    def test_legacy_v1_migration_with_servers_in_config_json(self, tmp_path):
        """v1.1.x config.json (monolithic, with 'servers') is migrated to v2.0."""
        svc = self._make(tmp_path)

        # Define minimal extract functions like the real ConfigValidationService.
        def extract_bot(c):
            return {"bot_token": c.get("bot_token"), "guild_id": c.get("guild_id")}

        def extract_docker(c):
            return {"servers": c.get("servers", [])}

        def extract_web(c):
            return {"web_ui_password_hash": c.get("web_ui_password_hash")}

        def extract_channels(c):
            return {"channel_permissions": c.get("channel_permissions", {})}

        # Write a legacy monolithic config.json
        legacy_data = {
            "bot_token": "tok",
            "guild_id": "42",
            "servers": [{"docker_name": "nginx"}],
            "channel_permissions": {VALID_CHANNEL_ID: {"name": "x"}},
            "web_ui_password_hash": "hash",
        }
        svc.legacy_config_file.parent.mkdir(parents=True, exist_ok=True)
        svc.legacy_config_file.write_text(json.dumps(legacy_data))

        svc.migrate_legacy_v1_config_if_needed(
            self._load_json, self._save_json,
            extract_bot, extract_docker, extract_web, extract_channels,
        )

        # Legacy config.json renamed to a backup file.
        # Note: migrate_legacy_v1_config_if_needed also runs the legacy file
        # cleanup at the end, which removes bot_config/docker_config/web_config/
        # channels_config.json. So we verify the migration *ran* by checking
        # that the original was renamed to a backup file.
        backups = [p for p in svc.config_dir.iterdir()
                   if p.name.startswith("config.json.v1.1.x.backup_")]
        assert len(backups) == 1
        # And the original monolithic file is gone.
        assert not svc.legacy_config_file.exists()

    def test_legacy_v1_migration_skips_if_no_legacy(self, tmp_path):
        """If no legacy file exists, migrate_legacy_v1_config_if_needed is a no-op."""
        svc = self._make(tmp_path)
        # Make sure neither legacy file exists.
        for f in (svc.legacy_config_file, svc.legacy_alt_config):
            if f.exists():
                f.unlink()
        # Should not raise even with broken extract funcs - they aren't called.
        svc.migrate_legacy_v1_config_if_needed(
            self._load_json, self._save_json,
            None, None, None, None,
        )
        # No modular files generated.
        assert not svc.bot_config_file.exists()


# ---------------------------------------------------------------------------
# ServerConfigService
# ---------------------------------------------------------------------------

class TestServerConfigService:
    """Tests for ServerConfigService - reads /config/containers/*.json."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path, monkeypatch):
        """Create modular config and redirect ConfigService at it."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(json.dumps({"language": "de"}))
        (config_dir / "channels").mkdir()
        containers = config_dir / "containers"
        containers.mkdir()

        # Redirect ConfigService so load_config() works against tmp_path.
        # ServerConfigService also derives its containers_dir from
        # __file__.parents[2], so we must redirect that too via monkeypatch.
        _redirect_config_service(get_config_service(), config_dir)

        return config_dir

    def _patch_server_service_paths(self, monkeypatch, tmp_path):
        """Make ``Path(__file__).parents[2]`` inside server_config_service
        resolve to ``tmp_path`` so the *real* _load_container_configs body
        executes (not a re-implementation), giving us real coverage.
        """
        from services.config import server_config_service as scs_mod

        # Ensure the directory layout the real code expects exists under tmp.
        fake_module_dir = tmp_path / "services" / "config"
        fake_module_dir.mkdir(parents=True, exist_ok=True)
        # The module computes parents[2] from __file__, so __file__ must live
        # 3 levels deep inside tmp_path.
        fake_file = fake_module_dir / "server_config_service.py"
        fake_file.write_text("# placeholder for tests\n")

        monkeypatch.setattr(scs_mod, "__file__", str(fake_file))

    def test_get_all_servers_returns_only_active(self, tmp_path, temp_config_dir, monkeypatch):
        self._patch_server_service_paths(monkeypatch, tmp_path)
        containers = temp_config_dir / "containers"
        (containers / "nginx.json").write_text(json.dumps({
            "container_name": "nginx", "active": True, "order": 1,
        }))
        (containers / "mysql.json").write_text(json.dumps({
            "container_name": "mysql", "active": False, "order": 2,
        }))

        svc = ServerConfigService()
        servers = svc.get_all_servers()
        assert len(servers) == 1
        assert servers[0]["docker_name"] == "nginx"

    def test_get_ordered_servers(self, tmp_path, temp_config_dir, monkeypatch):
        self._patch_server_service_paths(monkeypatch, tmp_path)
        containers = temp_config_dir / "containers"
        (containers / "a.json").write_text(json.dumps({
            "container_name": "a", "order": 5,
        }))
        (containers / "b.json").write_text(json.dumps({
            "container_name": "b", "order": 1,
        }))
        (containers / "c.json").write_text(json.dumps({
            "container_name": "c", "order": 3,
        }))

        svc = ServerConfigService()
        ordered = svc.get_ordered_servers()
        assert [s["docker_name"] for s in ordered] == ["b", "c", "a"]

    def test_get_server_by_docker_name(self, tmp_path, temp_config_dir, monkeypatch):
        self._patch_server_service_paths(monkeypatch, tmp_path)
        containers = temp_config_dir / "containers"
        (containers / "nginx.json").write_text(json.dumps({
            "container_name": "nginx",
        }))

        svc = ServerConfigService()
        assert svc.get_server_by_docker_name("nginx")["docker_name"] == "nginx"
        assert svc.get_server_by_docker_name("ghost") is None

    def test_get_valid_containers_filters(self, tmp_path, temp_config_dir, monkeypatch):
        self._patch_server_service_paths(monkeypatch, tmp_path)
        containers = temp_config_dir / "containers"
        (containers / "nginx.json").write_text(json.dumps({"container_name": "nginx"}))
        (containers / "mysql.json").write_text(json.dumps({"container_name": "mysql"}))

        svc = ServerConfigService()
        valid = svc.get_valid_containers()
        names = {c["docker_name"] for c in valid}
        assert names == {"nginx", "mysql"}
        # All entries have both keys set.
        assert all(set(c.keys()) == {"display", "docker_name"} for c in valid)

    def test_validate_server_config(self):
        svc = ServerConfigService()
        assert svc.validate_server_config({"docker_name": "x"}) is True
        assert svc.validate_server_config({"docker_name": ""}) is False
        assert svc.validate_server_config({"name": "x"}) is False  # missing docker_name
        assert svc.validate_server_config("not-a-dict") is False
        assert svc.validate_server_config(None) is False

    def test_get_base_directory_default(self, tmp_path, temp_config_dir, monkeypatch):
        # No base_dir in config => default '/app'.
        svc = ServerConfigService()
        assert svc.get_base_directory() == "/app"

    def test_singleton_helper(self):
        a = get_server_config_service()
        b = get_server_config_service()
        assert a is b


# ---------------------------------------------------------------------------
# ConfigService gap fill - service-pattern API + legacy wrappers
# ---------------------------------------------------------------------------

class TestConfigServiceGapFill:
    """Targets uncovered branches in config_service.py."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(json.dumps({
            "language": "de",
            "guild_id": "42",
        }))
        (config_dir / "channels").mkdir()
        containers_dir = config_dir / "containers"
        containers_dir.mkdir()
        # Drop a placeholder so has_real_modular_structure() returns True
        # and the loader actually reads config.json instead of falling back
        # to the virtual modular path (which expects bot_config.json etc.).
        (containers_dir / "_placeholder.json").write_text(json.dumps({
            "container_name": "_placeholder",
            "active": False,
        }))
        return config_dir

    def test_get_config_service_request_result(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        result = svc.get_config_service(GetConfigRequest(force_reload=True))
        assert result.success is True
        assert result.config is not None
        assert result.config.get("language") == "de"

    def test_save_config_then_reload(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        result = svc.save_config({"language": "en", "guild_id": "99"})
        assert result.success is True
        assert result.message
        # Reload preserves saved fields.
        cfg = svc.get_config(force_reload=True)
        assert cfg["language"] == "en"
        assert cfg["guild_id"] == "99"

    def test_save_config_preserves_critical_fields(self, temp_config_dir):
        """Partial save should preserve bot_token / guild_id from existing config."""
        # Seed config.json with a bot_token already.
        (temp_config_dir / "config.json").write_text(json.dumps({
            "bot_token": "ENCRYPTED_TOKEN_DO_NOT_LOSE",
            "guild_id": "12345",
            "language": "de",
        }))
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        # Save a partial config that would otherwise wipe critical fields.
        result = svc.save_config({"language": "en"})
        assert result.success is True

        on_disk = json.loads((temp_config_dir / "config.json").read_text())
        assert on_disk["bot_token"] == "ENCRYPTED_TOKEN_DO_NOT_LOSE"
        assert on_disk["guild_id"] == "12345"
        assert on_disk["language"] == "en"

    def test_update_config_fields_merges(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        result = svc.update_config_fields({"new_field": "added"})
        assert result.success is True

        on_disk = json.loads((temp_config_dir / "config.json").read_text())
        assert on_disk["new_field"] == "added"
        assert on_disk["language"] == "de"  # untouched
        assert on_disk["guild_id"] == "42"  # untouched

    def test_validate_donation_key_invalid(self, temp_config_dir, monkeypatch):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        # Patch the donation key list to a known set.
        monkeypatch.setattr(
            "utils.key_crypto.get_valid_donation_keys",
            lambda: ["DDC-VALID-KEY-001"],
        )
        result = svc.validate_donation_key_service(
            ValidateDonationKeyRequest(key="not-a-real-key")
        )
        assert result.success is True
        assert result.is_valid is False

    def test_validate_donation_key_valid(self, temp_config_dir, monkeypatch):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        monkeypatch.setattr(
            "utils.key_crypto.get_valid_donation_keys",
            lambda: ["DDC-VALID-KEY-001"],
        )
        result = svc.validate_donation_key_service(
            ValidateDonationKeyRequest(key="ddc-valid-key-001")  # case-insensitive
        )
        assert result.success is True
        assert result.is_valid is True

    def test_get_evolution_mode_defaults(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        result = svc.get_evolution_mode_service(GetEvolutionModeRequest())
        # No evolution_mode.json on disk -> defaults returned.
        assert result.success is True
        assert result.use_dynamic is True
        assert result.difficulty_multiplier == 1.0

    def test_get_evolution_mode_from_file(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        (temp_config_dir / "evolution_mode.json").write_text(
            json.dumps({"use_dynamic": False, "difficulty_multiplier": 2.5})
        )
        result = svc.get_evolution_mode_service(GetEvolutionModeRequest())
        assert result.success is True
        assert result.use_dynamic is False
        assert result.difficulty_multiplier == 2.5

    def test_legacy_load_config_wrapper(self, temp_config_dir):
        _redirect_config_service(get_config_service(), temp_config_dir)
        cfg = load_config()
        assert cfg["language"] == "de"

    def test_legacy_save_config_wrapper(self, temp_config_dir):
        _redirect_config_service(get_config_service(), temp_config_dir)
        assert legacy_save_config({"language": "en", "guild_id": "1"}) is True

    def test_legacy_update_config_fields_wrapper(self, temp_config_dir):
        _redirect_config_service(get_config_service(), temp_config_dir)
        assert legacy_update_config_fields({"x": "y"}) is True
        on_disk = json.loads((temp_config_dir / "config.json").read_text())
        assert on_disk["x"] == "y"

    def test_decrypt_token_if_needed_returns_plaintext_unchanged(self, temp_config_dir):
        """If token already looks like a Discord token, no decryption is attempted."""
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        # looks_like_discord_token only requires >50 chars containing a dot;
        # build a clearly-fake string so secret scanners don't false-positive.
        plain = ("x" * 30) + "." + ("y" * 30)
        assert svc._decrypt_token_if_needed(plain, "any_hash") == plain

    def test_decrypt_token_if_needed_returns_none_for_empty(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        assert svc._decrypt_token_if_needed("", "any_hash") is None

    def test_decrypt_token_if_needed_failure_returns_none(self, temp_config_dir):
        """If decryption fails (TokenEncryptionError), helper returns None."""
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        # A short non-Discord-shaped string + a valid-format hash forces
        # decrypt_token to be called and fail. _decrypt_token_if_needed
        # catches the error and returns None.
        result = svc._decrypt_token_if_needed("not-a-token", "pbkdf2:sha256$abc$" + "0" * 64)
        assert result is None

    def test_encrypt_token_with_no_password_returns_none(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        assert svc.encrypt_token("token", "") is None

    def test_decrypt_token_with_no_password_returns_none(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        assert svc.decrypt_token("token", "") is None

    def test_encrypt_token_invalid_input_raises_token_error(self, temp_config_dir):
        """Encrypting with mismatched types raises TokenEncryptionError."""
        from services.exceptions import TokenEncryptionError

        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        with pytest.raises(TokenEncryptionError):
            # Pass an int as token => triggers TypeError inside encrypt path,
            # which is wrapped as TokenEncryptionError.
            svc.encrypt_token(12345, "valid_hash_string")  # type: ignore

    def test_load_json_file_invalid_json_returns_default(self, temp_config_dir):
        """_load_json_file swallows JSONDecodeError and returns default."""
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        bad_path = temp_config_dir / "broken.json"
        bad_path.write_text("{not json}")
        result = svc._load_json_file(bad_path, {"fallback": "yes"})
        assert result == {"fallback": "yes"}

    def test_load_json_file_missing_returns_default(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        result = svc._load_json_file(temp_config_dir / "ghost.json", {"x": 1})
        assert result == {"x": 1}

    def test_save_json_file_atomic_write(self, temp_config_dir):
        svc = _redirect_config_service(get_config_service(), temp_config_dir)
        target = temp_config_dir / "out.json"
        svc._save_json_file(target, {"hello": "world"})

        assert target.exists()
        assert json.loads(target.read_text()) == {"hello": "world"}
        # No leftover .tmp files.
        assert list(temp_config_dir.glob("*.tmp")) == []

    def test_get_config_service_with_invalid_dir_returns_dict(self, tmp_path):
        """Get config from a dir without modular structure - returns empty-ish dict."""
        bare = tmp_path / "bare"
        bare.mkdir()
        svc = _redirect_config_service(get_config_service(), bare)

        # Should not raise; loader returns an empty config gracefully.
        result = svc.get_config_service(GetConfigRequest(force_reload=True))
        assert result.success is True
        assert isinstance(result.config, dict)
