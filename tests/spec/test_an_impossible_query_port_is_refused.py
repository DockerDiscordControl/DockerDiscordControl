# -*- coding: utf-8 -*-
"""A game-query port outside 1-65535 is refused with a message, not saved as 0.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F7): the query
port typed in the container modal reaches the form unchecked (config-ui.js
copies the raw value past the input's min/max), and sanitize_query_config
turned 70000 into 0 - "auto-discover" - while the panel said "Configuration
saved". The operator never learned the port was not taken.

THE OPERATOR (2026-09-29): refuse it with a message, like the difficulty
multiplier and B14.

THE CONTRACT: a query port that is not a whole number from 0 to 65535 (0 and
empty mean auto-discover) stops the save before anything is written, and the
message names the container and the value.

HOW THIS TEST CAN FAIL: the port is clamped in silence again; or a valid port
or an empty field is refused.

It goes through ConfigurationSaveService.save_configuration, the panel's save,
on a temp config directory.

COUNTER-CHECK (2026-09-29): the first case red before the change, the second
green before and after.
"""

import importlib
import json

import pytest
from werkzeug.datastructures import MultiDict


@pytest.fixture
def save(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "containers").mkdir()
    (tmp_path / "containers" / "a.json").write_text(json.dumps(
        {"container_name": "a", "docker_name": "a", "active": True, "query_port": 2457,
         "allowed_actions": ["status"]}), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"guild_id": "1"}), encoding="utf-8")
    monkeypatch.setattr(importlib.import_module("services.config.config_service").ConfigService,
                        "_instance", None)
    monkeypatch.setattr(importlib.import_module("services.config.container_config_save_service"),
                        "_container_config_save_service_instance", None)
    from services.web.configuration_save_service import (ConfigurationSaveRequest,
                                                         ConfigurationSaveService)

    def _save(port):
        form = MultiDict({"server_order": "a", "servers_table_submitted": "1",
                          "channel_tables_submitted": "1", "selected_servers": "a",
                          "allow_status_a": "1", "query_enabled_a": "1",
                          "query_port_a": port})
        result = ConfigurationSaveService().save_configuration(ConfigurationSaveRequest(form_data=form))
        stored = json.loads((tmp_path / "containers" / "a.json").read_text(encoding="utf-8"))
        return result, stored
    return _save


def test_a_port_above_65535_is_refused(save):
    result, stored = save("70000")
    assert not result.success, "70000 was accepted as a query port"
    text = f"{result.message} {getattr(result, 'error', '')}"
    assert "70000" in text and "a" in text, f"the refusal does not say what was wrong: {text}"
    assert stored["query_port"] == 2457, "the refused save changed the container anyway"


@pytest.mark.parametrize("port", ["27015", "", "0"])
def test_a_valid_port_or_auto_is_saved(save, port):
    result, stored = save(port)
    assert result.success, f"{port!r} was refused: {result.message}"
    assert stored["query_port"] == int(port or 0)
