# -*- coding: utf-8 -*-
"""Unticking every container's Active box and saving makes them inactive.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F5, verified
2026-09-29). With no Active box ticked the browser posts no
selected_servers at all. The form parser then treated "no servers" as "the
table was not in the form" and kept the old list, and the save step
skipped the container files for an empty list - every container stayed
active, and the panel said "Configuration saved". The channel tables solved
the same problem with a hidden marker (channel_tables_submitted); the
container table had none.

THE CONTRACT: when the form carries the container table (marker
servers_table_submitted), an empty selection is saved - every container
inactive.

HOW THIS TEST CAN FAIL: an empty selection is dropped again.

It goes through ConfigurationSaveService.save_configuration, the panel's
save, on a temp config directory.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import importlib
import json

from werkzeug.datastructures import MultiDict


def test_an_empty_selection_saves_every_container_inactive(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "containers").mkdir()
    (tmp_path / "containers" / "a.json").write_text(json.dumps(
        {"container_name": "a", "docker_name": "a", "active": True,
         "allowed_actions": ["status"]}), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"guild_id": "1"}), encoding="utf-8")
    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(config_module.ConfigService, "_instance", None)
    from services.web.configuration_save_service import (ConfigurationSaveRequest,
                                                         ConfigurationSaveService)

    form = MultiDict({"server_order": "a", "servers_table_submitted": "1",
                      "channel_tables_submitted": "1"})
    ConfigurationSaveService().save_configuration(ConfigurationSaveRequest(form_data=form))

    saved = json.loads((tmp_path / "containers" / "a.json").read_text(encoding="utf-8"))
    assert saved["active"] is False, "the container stayed active although nothing was ticked"
