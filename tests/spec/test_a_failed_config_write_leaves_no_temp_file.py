# -*- coding: utf-8 -*-
"""A config.json write that fails while encoding leaves no temp file behind.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F8):
save_config writes a temp file and renames it. When json.dump raised
TypeError/ValueError (a value that is not JSON), the cleanup only handled
IOError/OSError, so .config_XXXX.json.tmp stayed in config/ - one per
failed save. Its sibling _save_json_file cleans up on every error.

THE CONTRACT: the save fails, and no temp file is left.

HOW THIS TEST CAN FAIL: the temp file stays again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

import json

import pytest

import services.config.config_service as cs_mod
from services.exceptions import ConfigSaveError


def test_no_temp_file_after_a_failed_encoding(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cs_mod.ConfigService, "_instance", None)
    (tmp_path / "config.json").write_text(json.dumps({"guild_id": "1"}), encoding="utf-8")
    service = cs_mod.ConfigService()

    try:
        result = service.save_config({"guild_id": "1", "bad": {1, 2}})
        assert not result.success
    except ConfigSaveError:
        pass

    left = [p.name for p in tmp_path.glob(".config_*.tmp")] + [p.name for p in tmp_path.glob("*.json.tmp")]
    assert not left, f"a failed save left {left}"
