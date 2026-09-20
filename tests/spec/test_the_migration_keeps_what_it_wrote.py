# -*- coding: utf-8 -*-
"""Migrating a v1 configuration leaves the files it just wrote in place.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage C, section 12 F1, re-checked 2026-09-20):
``migrate_legacy_v1_config_if_needed`` splits a v1.1.x config.json into
bot_config.json, docker_config.json, web_config.json and
channels_config.json, renames the old file to a backup, logs "migration
completed successfully" - and then calls
``cleanup_legacy_files_after_migration()``, whose list is exactly those four
names. It deletes what it has just written.

The list is right for the OTHER caller: ``perform_real_modular_migration``
moves those four files into channels/ and containers/, and there they really
are the leftovers. One cleanup list, two migrations, opposite meanings.

What an operator upgrading from v1.1.x is left with is the renamed backup
and nothing else - DDC then starts with an empty configuration: no
containers, no channel permissions.
"""

import json

import pytest

from services.config.config_migration_service import ConfigMigrationService

LEGACY = {
    "bot_token": "a-token",
    "language": "de",
    "servers": [{"docker_name": "vrising", "name": "V-Rising"}],
    "web_ui_password_hash": "hash",
    "channel_permissions": {"123456789012345678": {"commands": {"control": True}}},
}
WRITTEN = ("bot_config.json", "docker_config.json", "web_config.json",
           "channels_config.json")


def _save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def service(tmp_path):
    return ConfigMigrationService(tmp_path, tmp_path / "channels", tmp_path / "containers")


def _migrate(service, config_dir):
    (config_dir / "config.json").write_text(json.dumps(LEGACY), encoding="utf-8")
    service.migrate_legacy_v1_config_if_needed(
        _load, _save,
        lambda cfg: {"bot_token": cfg.get("bot_token"), "language": cfg.get("language")},
        lambda cfg: {"servers": cfg.get("servers", [])},
        lambda cfg: {"web_ui_password_hash": cfg.get("web_ui_password_hash")},
        lambda cfg: cfg.get("channel_permissions", {}),
    )


def test_the_migration_runs_at_all(service, tmp_path):
    """Premise: the legacy file is recognised and backed up."""
    _migrate(service, tmp_path)

    backups = list(tmp_path.glob("config.json.v1.1.x.backup_*"))
    assert backups, sorted(p.name for p in tmp_path.iterdir())


def test_the_written_files_are_still_there(service, tmp_path):
    _migrate(service, tmp_path)

    missing = [name for name in WRITTEN if not (tmp_path / name).exists()]
    assert not missing, (
        f"the migration deleted the files it had just written: {missing}"
    )


def test_the_migrated_settings_survive(service, tmp_path):
    _migrate(service, tmp_path)

    assert _load(tmp_path / "docker_config.json")["servers"][0]["docker_name"] == "vrising"
    assert _load(tmp_path / "bot_config.json")["language"] == "de"


def test_the_other_migration_still_cleans_up(service, tmp_path):
    """Counter-check: for the modular migration those four ARE the leftovers."""
    for name in WRITTEN:
        (tmp_path / name).write_text("{}", encoding="utf-8")

    service.cleanup_legacy_files_after_migration()

    assert not [name for name in WRITTEN if (tmp_path / name).exists()]
