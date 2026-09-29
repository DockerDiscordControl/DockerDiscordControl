# -*- coding: utf-8 -*-
"""A config.json that cannot be read is not replaced by the few keys being saved.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F1, verified
2026-09-29). ConfigService._load_json_file never raises: a config.json that
exists but is broken JSON or unreadable comes back as {} (the read error is
only recorded). update_config_fields merged its updates into that {} and
save_config's "critical field protection" merged against {} too - so the
atomic rename REPLACED config.json with just the updated keys: bot token,
guild id, password hash and channel rights gone, answered success=True.
The unguarded way in is scripts/reset_password.py -> change_web_ui_password,
exactly what an operator runs when the panel says "Configuration
Unreadable". The except branches meant for read errors were dead code.

THE CONTRACT: when config.json exists but cannot be read as a JSON object,
a partial save refuses and leaves the file as it is.

HOW THIS TEST CAN FAIL: a save merges into an empty document again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import importlib

import pytest

BROKEN = '{"bot_token": "abc", "guild_id": "42", "web_ui_password_hash": "h",'


def _fresh_service(tmp_path, monkeypatch):
    """A ConfigService on tmp_path. It is a singleton: the instance is reset for
    this test and put back afterwards, so no other test sees this directory."""
    module = importlib.import_module("services.config.config_service")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(module.ConfigService, "_instance", None)
    return module.ConfigService()


@pytest.fixture
def service(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(BROKEN, encoding="utf-8")
    return _fresh_service(tmp_path, monkeypatch), tmp_path / "config.json"


def test_a_field_update_does_not_replace_an_unreadable_config(service):
    config_service, path = service

    result = config_service.update_config_fields({"ui_language": "de"})

    assert not result.success, "the save reported success over an unreadable config.json"
    assert path.read_text(encoding="utf-8") == BROKEN, "config.json was replaced"


def test_the_password_reset_refuses_instead_of_wiping(service):
    from services.config.config_service import ConfigSaveError
    config_service, path = service

    with pytest.raises(ConfigSaveError):
        config_service.change_web_ui_password("A-long-enough-password-1")

    assert path.read_text(encoding="utf-8") == BROKEN


def test_a_readable_config_keeps_its_other_fields(tmp_path, monkeypatch):
    """Counter-check: the ordinary partial save still merges and succeeds."""
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"guild_id": "42", "language": "en"}), encoding="utf-8")

    result = _fresh_service(tmp_path, monkeypatch).update_config_fields({"language": "de"})

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert result.success and saved["guild_id"] == "42" and saved["language"] == "de"
