# -*- coding: utf-8 -*-
"""A retried config migration keeps what the operator saved since the first attempt.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F3): the move to
the modular configuration is retried at every start until it has finished
(review C28). Each retry rebuilt config.json from the legacy bot_config.json
- six keys - and rewrote channels/<id>.json, default.json, web_ui.json and
docker_settings.json from the legacy files, discarding everything the
operator had saved in between. channels/ and containers/ were not backed up.

THE CONTRACT: a retry fills in only what is missing - existing files and
existing keys win - and the backup takes channels/ and containers/ too.

HOW THIS TEST CAN FAIL: a retry overwrites a saved setting again.

COUNTER-CHECK (2026-09-30): red before the change. The legacy case below was red
with the first version of the fix, which filled in config.json unconditionally.
"""

import json
from pathlib import Path

from services.config.config_migration_service import ConfigMigrationService

CHANNEL = "123456789012345678"


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save(path, data):
    Path(path).write_text(json.dumps(data), encoding="utf-8")


def test_a_retry_keeps_the_saved_settings(tmp_path):
    (tmp_path / "bot_config.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    (tmp_path / "docker_config.json").write_text(json.dumps(
        {"servers": [{"docker_name": "web"}]}), encoding="utf-8")
    (tmp_path / "channels_config.json").write_text(json.dumps(
        {"channel_permissions": {CHANNEL: {"name": "legacy name"}}}), encoding="utf-8")
    channels, containers = tmp_path / "channels", tmp_path / "containers"
    channels.mkdir(); containers.mkdir()
    # What the operator saved after the first attempt died:
    (tmp_path / "config.json").write_text(json.dumps(
        {"language": "de", "heartbeat": {"enabled": True, "ping_url": "https://hc-ping.com/x",
                                         "interval": 5}}), encoding="utf-8")
    (channels / f"{CHANNEL}.json").write_text(json.dumps({"name": "renamed since"}), encoding="utf-8")

    ConfigMigrationService(tmp_path, channels, containers).perform_real_modular_migration(_load, _save)

    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert config["language"] == "de", "the retry put the legacy language back"
    assert config["heartbeat"]["ping_url"] == "https://hc-ping.com/x", "the heartbeat was wiped"
    channel = json.loads((channels / f"{CHANNEL}.json").read_text(encoding="utf-8"))
    assert channel["name"] == "renamed since", "the retry put the legacy channel back"
    assert (containers / "web.json").exists(), "the missing container was not migrated"
    backups = list(tmp_path.glob("backup_*"))
    assert backups and (backups[0] / "channels" / f"{CHANNEL}.json").exists(), (
        "channels/ was not in the backup")


def test_a_monolithic_legacy_config_is_still_replaced(tmp_path):
    """Counter-case: the v1.1.x config.json (it carries "servers") is not kept key by key -
    kept, it would look like a legacy file on every read and be migrated again."""
    (tmp_path / "bot_config.json").write_text(json.dumps({"language": "fr"}), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps(
        {"language": "en", "servers": [{"docker_name": "web"}]}), encoding="utf-8")
    channels, containers = tmp_path / "channels", tmp_path / "containers"
    channels.mkdir(); containers.mkdir()

    ConfigMigrationService(tmp_path, channels, containers).perform_real_modular_migration(_load, _save)

    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "servers" not in config and config["language"] == "fr", config
