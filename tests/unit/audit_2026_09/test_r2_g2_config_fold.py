# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, release review, package G2 - config upgrade path.

R1-2   one-time fold of the legacy settings files into config.json (v2.3 values kept),
       bot token self-repair instead of dropping the decrypted copy
R1-9b  an explicitly emptied channel set wins over the legacy channels_config.json fallback
"""

import json
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import services.config.config_service as cs_mod
from services.config.channel_config_service import ALL_CHANNELS_REMOVED_MARKER, ChannelConfigService
from services.config.config_cache_service import ConfigCacheService
from services.config.config_loader_service import LEGACY_FOLD_MARKER, ConfigLoaderService
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import ConfigService, get_config_service

# Shaped like real Discord bot tokens (looks_like_discord_token() -> True)
TOKEN = "MTA" + "a" * 23 + "." + "b" * 6 + "." + "c" * 38
OTHER_TOKEN = "MTQ" + "z" * 23 + "." + "y" * 6 + "." + "x" * 38
CHANNEL_ID = "123456789012345678"
OTHER_CHANNEL_ID = "987654321098765432"


def _hash(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256:1000")


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data))


def _read(path: Path):
    return json.loads(path.read_text())


@pytest.fixture(autouse=True)
def _fast_kdf(monkeypatch):
    """Token key derivation with 600k PBKDF2 rounds is slow; the logic is identical."""
    monkeypatch.setattr(cs_mod, "_PBKDF2_ITERATIONS", 1000)


@pytest.fixture
def svc(tmp_path):
    """The ConfigService singleton pointed at tmp_path/config (restored afterwards)."""
    service = get_config_service()
    saved_state = dict(service.__dict__)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
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
    service._migration_service = ConfigMigrationService(config_dir, service.channels_dir, service.containers_dir)
    service._cache_service = ConfigCacheService()
    service._loader_service = ConfigLoaderService(
        config_dir, service.channels_dir, service.containers_dir,
        service.main_config_file, service.auth_config_file, service.heartbeat_config_file,
        service.web_ui_config_file, service.docker_settings_file, service.bot_config_file,
        service.docker_config_file, service.web_config_file, service.channels_config_file,
        service._load_json_file, service._validation_service,
    )
    yield service

    service.__dict__.clear()
    service.__dict__.update(saved_state)


def _modular_layout(config_dir: Path) -> None:
    (config_dir / "containers").mkdir(exist_ok=True)
    _write(config_dir / "containers" / "web.json", {"docker_name": "web", "active": True})


# ---------------------------------------------------------------------------
# R1-2: real modular layout (auth.json / web_ui.json / docker_settings.json)
# ---------------------------------------------------------------------------

class TestFoldModularLayout:

    def test_env_password_install_keeps_a_working_token(self, svc):
        """Reviewer scenario S3: v1 install still on admin/admin, DDC_ADMIN_PASSWORD set at
        v2.3 -> config.json holds the env hash, but the token is encrypted with the admin hash
        (still in web_ui.json). v2.3 used web_ui.json; after one save the token was dead."""
        cd = svc.config_dir
        h_admin, h_env = _hash("admin"), _hash("envpass")
        t_admin = svc.encrypt_token(TOKEN, h_admin)
        _modular_layout(cd)
        _write(cd / "config.json", {"language": "de", "web_ui_password_hash": h_env, "bot_token": t_admin,
                                    "bot_token_decrypted_for_usage": TOKEN})
        _write(cd / "auth.json", {"bot_token": t_admin, "encryption_enabled": True})
        _write(cd / "web_ui.json", {"web_ui_user": "admin", "web_ui_password_hash": h_admin})
        _write(cd / "docker_settings.json", {"docker_api_timeout": 45})

        # Before the fold the v2.3 precedence applies (legacy files win)
        before = svc.get_config(force_reload=True)
        assert before["web_ui_password_hash"] == h_admin
        assert before["bot_token_decrypted_for_usage"] == TOKEN

        assert svc._fold_legacy_settings_once() is True

        on_disk = _read(cd / "config.json")
        assert on_disk["web_ui_password_hash"] == h_admin
        assert on_disk["docker_api_timeout"] == 45
        assert on_disk["language"] == "de"
        assert "bot_token_decrypted_for_usage" not in on_disk
        assert svc.decrypt_token(on_disk["bot_token"], h_admin) == TOKEN

        for name in ("auth.json", "web_ui.json", "docker_settings.json"):
            assert not (cd / name).exists()
            assert len(list(cd.glob(name + ".folded-*"))) == 1
        backups = list(cd.glob("backup_*_settings_fold"))
        assert len(backups) == 1
        assert {p.name for p in backups[0].iterdir()} == {
            "config.json", "auth.json", "web_ui.json", "docker_settings.json"}
        assert _read(backups[0] / "config.json")["web_ui_password_hash"] == h_env  # untouched copy
        assert _read(cd / LEGACY_FOLD_MARKER)["mode"] == "real"

        after = svc.get_config(force_reload=True)
        assert after["web_ui_password_hash"] == h_admin
        assert after["bot_token_decrypted_for_usage"] == TOKEN
        svc.save_config(after)
        assert svc.get_config(force_reload=True)["bot_token_decrypted_for_usage"] == TOKEN

        # The startup env step then switches to the env password with a re-encrypted token
        cs_mod.change_web_ui_password("envpass", enforce_min_length=False)
        final = svc.get_config(force_reload=True)
        assert check_password_hash(final["web_ui_password_hash"], "envpass")
        assert final["bot_token_decrypted_for_usage"] == TOKEN

        assert svc._fold_legacy_settings_once() is False  # runs once

    def test_null_in_legacy_file_does_not_destroy_the_real_value(self, svc):
        """Scenario S4: web_ui.json has no hash, /setup wrote one to config.json at v2.3, which
        shadowed it at runtime (first-time setup mode).

        V1 review: the fold must NOT write that null back into config.json - it would destroy
        the last usable copy of the hash (same for a null bot_token in auth.json), and the old
        remedy "delete the legacy file" no longer works once it is renamed away. The real value
        wins and becomes effective after the fold.
        """
        cd = svc.config_dir
        _modular_layout(cd)
        real_hash = _hash("SetupPass-2025")
        _write(cd / "config.json", {"web_ui_password_hash": real_hash, "web_ui_user": "admin"})
        _write(cd / "auth.json", {"bot_token": TOKEN, "encryption_enabled": True})
        _write(cd / "web_ui.json", {"web_ui_user": "admin", "web_ui_password_hash": None})

        assert svc._fold_legacy_settings_once() is True

        # after the fold the real hash survives on disk and becomes effective
        assert _read(cd / "config.json")["web_ui_password_hash"] == real_hash
        config = svc.get_config(force_reload=True)
        assert config["web_ui_password_hash"] == real_hash
        assert config["bot_token_decrypted_for_usage"] == TOKEN

    def test_failed_rename_does_not_fold_again(self, svc, monkeypatch):
        cd = svc.config_dir
        _modular_layout(cd)
        _write(cd / "config.json", {"language": "en"})
        _write(cd / "web_ui.json", {"web_ui_password_hash": "legacy-hash"})

        def refuse(self, target):
            raise OSError("read-only")

        monkeypatch.setattr(Path, "rename", refuse)
        assert svc._fold_legacy_settings_once() is True
        monkeypatch.undo()
        assert (cd / "web_ui.json").exists()

        svc.update_config_fields({"web_ui_password_hash": "changed-later"})
        assert svc._fold_legacy_settings_once() is False
        # After the fold config.json wins; the leftover legacy file only fills gaps
        assert svc.get_config(force_reload=True)["web_ui_password_hash"] == "changed-later"

    def test_nothing_to_fold_without_legacy_files(self, svc):
        cd = svc.config_dir
        _modular_layout(cd)
        _write(cd / "config.json", {"language": "en"})
        assert svc._fold_legacy_settings_once() is False
        assert not (cd / LEGACY_FOLD_MARKER).exists()
        assert not list(cd.glob("backup_*"))

    def test_monolithic_v1_config_is_left_to_its_migration(self, svc):
        cd = svc.config_dir
        _modular_layout(cd)
        monolithic = {"servers": [{"docker_name": "web"}], "language": "en"}
        _write(cd / "config.json", monolithic)
        _write(cd / "web_ui.json", {"web_ui_password_hash": "legacy-hash"})
        assert svc._fold_legacy_settings_once() is False
        assert _read(cd / "config.json") == monolithic

    def test_fold_runs_at_service_start(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(ConfigService, "_instance", None)
        _modular_layout(tmp_path)
        _write(tmp_path / "config.json", {"language": "en", "web_ui_password_hash": "live"})
        _write(tmp_path / "web_ui.json", {"web_ui_password_hash": "legacy"})

        ConfigService()

        assert _read(tmp_path / "config.json")["web_ui_password_hash"] == "legacy"
        assert (tmp_path / LEGACY_FOLD_MARKER).exists()
        assert not (tmp_path / "web_ui.json").exists()


# ---------------------------------------------------------------------------
# R1-2: virtual layout (v1 split files)
# ---------------------------------------------------------------------------

class TestFoldVirtualLayout:

    def _v1_files(self, svc, t_old, h_old):
        cd = svc.config_dir
        _write(cd / "bot_config.json", {"bot_token": t_old, "guild_id": "42", "language": "de"})
        _write(cd / "web_config.json", {"web_ui_password_hash": h_old,
                                        "advanced_settings": {"A": "legacy", "B": "legacy"}})
        _write(cd / "docker_config.json", {"servers": [{"docker_name": "web", "active": True}]})

    def test_v1_values_win_until_the_fold_then_config_json(self, svc):
        """Scenario S6: a stale config.json from a v2.3 targeted write next to the v1 files."""
        cd = svc.config_dir
        h_old = _hash("OldUserPass-99")
        t_old = svc.encrypt_token(TOKEN, h_old)
        self._v1_files(svc, t_old, h_old)
        _write(cd / "config.json", {"web_ui_password_hash": _hash("envpass"), "language": "en",
                                    "timezone": "Europe/Berlin", "advanced_settings": {"B": "live", "C": "live"}})
        assert not svc._loader_service.has_real_modular_structure()

        before = svc.get_config(force_reload=True)
        assert before["web_ui_password_hash"] == h_old
        assert before["language"] == "de"
        assert before["timezone"] == "Europe/Berlin"  # bot_config.json lacks it: config.json fills
        assert before["advanced_settings"] == {"A": "legacy", "B": "legacy", "C": "live"}
        assert before["bot_token_decrypted_for_usage"] == TOKEN

        assert svc._fold_legacy_settings_once() is True
        assert _read(cd / LEGACY_FOLD_MARKER)["mode"] == "virtual"
        assert (cd / "bot_config.json").exists()  # v1 files also hold containers/channels
        on_disk = _read(cd / "config.json")
        assert on_disk["web_ui_password_hash"] == h_old
        assert on_disk["language"] == "de"
        assert on_disk["bot_token"] == t_old

        after = svc.get_config(force_reload=True)
        for key in ("web_ui_password_hash", "language", "timezone", "advanced_settings",
                    "bot_token_decrypted_for_usage"):
            assert after[key] == before[key], key
        assert len(after["servers"]) == 1

        # From now on a change saved to config.json takes effect
        svc.update_config_fields({"language": "fr"})
        assert svc.get_config(force_reload=True)["language"] == "fr"

    def test_without_config_json_only_the_marker_is_written(self, svc):
        cd = svc.config_dir
        h_old = _hash("OldUserPass-99")
        self._v1_files(svc, svc.encrypt_token(TOKEN, h_old), h_old)

        assert svc._fold_legacy_settings_once() is False
        assert (cd / LEGACY_FOLD_MARKER).exists()
        assert not (cd / "config.json").exists()
        assert svc.get_config(force_reload=True)["web_ui_password_hash"] == h_old

        svc.update_config_fields({"web_ui_password_hash": "new-hash"})
        assert svc.get_config(force_reload=True)["web_ui_password_hash"] == "new-hash"


# ---------------------------------------------------------------------------
# R1-2: bot token self-repair on save
# ---------------------------------------------------------------------------

class TestBotTokenSelfRepair:

    def _setup(self, svc, **config):
        _modular_layout(svc.config_dir)
        _write(svc.main_config_file, config)

    def test_save_reencrypts_the_decrypted_copy(self, svc):
        h_cur = _hash("Current-Pass-1")
        foreign = svc.encrypt_token(TOKEN, _hash("Other-Pass-22"))
        self._setup(svc, web_ui_password_hash=h_cur, bot_token=foreign, bot_token_decrypted_for_usage=TOKEN)

        config = svc.get_config(force_reload=True)  # decryption fails, the stale copy is still there
        svc.save_config(config)

        text = svc.main_config_file.read_text()
        assert TOKEN not in text and "bot_token_decrypted_for_usage" not in text
        assert svc.decrypt_token(_read(svc.main_config_file)["bot_token"], h_cur) == TOKEN
        assert svc.get_config(force_reload=True)["bot_token_decrypted_for_usage"] == TOKEN

    def test_copy_on_disk_is_used_when_the_caller_dropped_it(self, svc):
        h_cur = _hash("Current-Pass-1")
        foreign = svc.encrypt_token(TOKEN, _hash("Other-Pass-22"))
        self._setup(svc, web_ui_password_hash=h_cur, bot_token=foreign, bot_token_decrypted_for_usage=TOKEN)

        svc.save_config({"web_ui_password_hash": h_cur, "bot_token": foreign, "language": "en"})

        assert svc.decrypt_token(_read(svc.main_config_file)["bot_token"], h_cur) == TOKEN

    def test_without_password_hash_the_copy_is_kept_in_plaintext(self, svc):
        foreign = svc.encrypt_token(TOKEN, _hash("Other-Pass-22"))
        self._setup(svc, bot_token=foreign, bot_token_decrypted_for_usage=TOKEN)

        svc.save_config(svc.get_config(force_reload=True))

        on_disk = _read(svc.main_config_file)
        assert on_disk["bot_token"] == TOKEN
        assert "bot_token_decrypted_for_usage" not in on_disk

    def test_working_token_is_not_replaced_by_a_stale_copy(self, svc):
        h_cur = _hash("Current-Pass-1")
        encrypted = svc.encrypt_token(TOKEN, h_cur)
        self._setup(svc, web_ui_password_hash=h_cur, bot_token=encrypted,
                    bot_token_decrypted_for_usage=OTHER_TOKEN)

        svc.save_config({"web_ui_password_hash": h_cur, "bot_token": encrypted})

        assert _read(svc.main_config_file)["bot_token"] == encrypted

    def test_undecryptable_token_without_copy_is_kept(self, svc):
        h_cur = _hash("Current-Pass-1")
        foreign = svc.encrypt_token(TOKEN, _hash("Other-Pass-22"))
        self._setup(svc, web_ui_password_hash=h_cur, bot_token=foreign)

        svc.save_config(svc.get_config(force_reload=True))

        assert _read(svc.main_config_file)["bot_token"] == foreign


# ---------------------------------------------------------------------------
# R1-9b: removing the last channel sticks
# ---------------------------------------------------------------------------

class TestExplicitlyEmptiedChannels:

    @pytest.fixture
    def channel_service(self, svc, monkeypatch):
        """ChannelConfigService on the same temp dir as svc (never the real config/)."""
        service = ChannelConfigService.__new__(ChannelConfigService)
        service.base_dir = svc.config_dir.parent
        service.channels_dir = svc.channels_dir
        service.config_file = svc.main_config_file
        service.channels_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("services.config.channel_config_service.get_channel_config_service",
                            lambda: service)
        return service

    def _layout(self, svc):
        _modular_layout(svc.config_dir)
        _write(svc.main_config_file, {"language": "en"})
        _write(svc.channels_config_file, {"channel_permissions": {CHANNEL_ID: {"name": "legacy"}}})

    def test_removed_last_channel_is_not_restored_from_legacy_file(self, svc, channel_service):
        self._layout(svc)
        channel_service.save_channel(CHANNEL_ID, {"name": "control"})
        assert set(svc.get_config(force_reload=True)["channel_permissions"]) == {CHANNEL_ID}

        assert channel_service.save_all_channels({}, allow_empty=True) is True
        assert (svc.channels_dir / ALL_CHANNELS_REMOVED_MARKER).exists()

        assert svc.get_config(force_reload=True)["channel_permissions"] == {}
        assert not (svc.channels_dir / f"{CHANNEL_ID}.json").exists()  # no auto-migration either

        channel_service.save_channel(OTHER_CHANNEL_ID, {"name": "new"})
        assert not (svc.channels_dir / ALL_CHANNELS_REMOVED_MARKER).exists()
        assert set(svc.get_config(force_reload=True)["channel_permissions"]) == {OTHER_CHANNEL_ID}

    def test_lost_channel_files_are_still_recovered(self, svc, channel_service):
        """Without the marker the legacy fallback keeps working (e.g. files lost)."""
        self._layout(svc)
        assert set(svc.get_config(force_reload=True)["channel_permissions"]) == {CHANNEL_ID}
        assert (svc.channels_dir / f"{CHANNEL_ID}.json").exists()  # auto-migrated
