# -*- coding: utf-8 -*-
"""A hand-written "use_dynamic": "false" means static pricing, not dynamic.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F9): the
evolution mode is read without a type check, and the string "false" is
truthy - with a hand-edited evolution_mode.json the mech kept dynamic
pricing while the file said static. The panel writes a bool, so only a hand
edit gets there; the multiplier beside it is already checked on read.

THE CONTRACT: a bool is taken as it is, "true"/"false" as what they say,
anything else falls back to dynamic with a warning.

HOW THIS TEST CAN FAIL: "false" means dynamic again.

COUNTER-CHECK (2026-09-30): the "false" case red before the change.
"""

import json

import pytest

import services.config.config_service as cs_mod


@pytest.mark.parametrize("stored,expected", [("false", False), ("FALSE", False), ("true", True),
                                             (False, False), (True, True), ("maybe", True)])
def test_the_stored_value_means_what_it_says(monkeypatch, tmp_path, stored, expected):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cs_mod.ConfigService, "_instance", None)
    (tmp_path / "evolution_mode.json").write_text(json.dumps(
        {"use_dynamic": stored, "difficulty_multiplier": 2.0}), encoding="utf-8")

    result = cs_mod.ConfigService().get_evolution_mode_service(cs_mod.GetEvolutionModeRequest())

    assert result.use_dynamic is expected
