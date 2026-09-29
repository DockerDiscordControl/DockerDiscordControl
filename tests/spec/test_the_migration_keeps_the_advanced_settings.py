# -*- coding: utf-8 -*-
"""The move to the modular configuration keeps the advanced settings.

THE FINDING (stage 4 review before v3.1.0, section 12, both passes,
verified 2026-09-29). On the automatic real-modular migration the
advanced settings of web_config.json were copied nowhere - web_ui.json
and config.json were built without them - and the cleanup then deleted
web_config.json, their only home. Every advanced setting (cache duration,
timeouts, ...) fell back to its default after that restart, while the log
said "advanced_settings kept in web_config.json".

THE CONTRACT: after the migration config.json holds the advanced settings
web_config.json had, and the configuration reads them.

HOW THIS TEST CAN FAIL: the migration drops them again.

It runs the real migration through ConfigService on a temp directory.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import importlib
import json


def test_advanced_settings_survive_the_migration(tmp_path, monkeypatch):
    def write(name, data):
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")

    write("bot_config.json", {"bot_token": None, "guild_id": "42", "language": "en"})
    write("docker_config.json", {"servers": [{"docker_name": "web", "name": "web"}]})
    write("channels_config.json", {"channel_permissions": {"111": {"commands": {"control": True}}}})
    write("web_config.json", {"web_ui_user": "admin",
                              "advanced_settings": {"DDC_DOCKER_CACHE_DURATION": "120"}})
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(module.ConfigService, "_instance", None)

    config = module.ConfigService().get_config(force_reload=True)

    assert (config.get("advanced_settings") or {}).get("DDC_DOCKER_CACHE_DURATION") == "120", (
        config.get("advanced_settings"))
    main = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert main.get("advanced_settings", {}).get("DDC_DOCKER_CACHE_DURATION") == "120"
