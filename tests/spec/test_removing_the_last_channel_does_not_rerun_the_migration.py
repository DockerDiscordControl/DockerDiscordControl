# -*- coding: utf-8 -*-
"""Removing the last channel does not make the migration run again.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F2, verified
2026-09-29). _modular_structure_is_complete asked whether channels/ holds
a *.json - and ignored ALL_CHANNELS_REMOVED_MARKER, which the loader
honours. On an install that still had channels_config.json and no
completion marker, removing the last channel made the next start run the
whole migration again: the removed channels came back from the legacy file
with their old rights, config.json was rebuilt from bot_config.json and
the old v1 password hash was folded over it.

THE CONTRACT: a channels/ directory holding the "all removed" marker is a
migrated one.

HOW THIS TEST CAN FAIL: the check reads an empty channels/ as unmigrated again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import importlib
import json

CHANNEL = "123456789012345678"


def test_the_removed_channels_do_not_come_back(tmp_path, monkeypatch):
    def write(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    write("channels_config.json", {"channel_permissions": {CHANNEL: {"commands": {"control": True}}}})
    write("docker_config.json", {"servers": [{"docker_name": "a", "name": "a"}]})
    write("bot_config.json", {"guild_id": "1"})
    write("config.json", {"guild_id": "1", "language": "de"})
    write("containers/a.json", {"docker_name": "a", "container_name": "a"})
    (tmp_path / "channels").mkdir(exist_ok=True)
    (tmp_path / "channels" / ".all_channels_removed").write_text("x", encoding="utf-8")

    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(module.ConfigService, "_instance", None)

    config = module.ConfigService().get_config(force_reload=True)

    assert not (tmp_path / "channels" / f"{CHANNEL}.json").exists(), "the removed channel came back"
    assert config.get("channel_permissions") in ({}, None), config.get("channel_permissions")
