# -*- coding: utf-8 -*-
"""A decay.json the operator broke does not decay every level at 100 cents.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F3): when the
operator's config/mech/decay.json existed but could not be parsed (a bad
hand edit), get_decay_config_data fell back to {'default': 100} - not to
the shipped table. Every level, the immortal level 11 (table: 0) included,
was stamped with 100 cents a day at the next power event or level-up, and
for levels 1-10 the wrong rate was folded into the power for good. The
comment in that function itself calls this the bug the shipped file was
meant to remove.

THE CONTRACT: a failed read keeps the last good table if there is one,
else the shipped one; the flat 100 only when both are missing.

HOW THIS TEST CAN FAIL: level 11 decays again after a bad edit, or a good
own table read a moment ago is replaced by the shipped one.

COUNTER-CHECK (2026-09-30): red before the change (100 for every level).
"""

import importlib

import pytest


@pytest.fixture
def module(tmp_path, monkeypatch):
    """progress_service as it is now, its decay config read from tmp_path.

    Not the fixture of test_a_new_release_refuels_an_empty_mech: that one
    replaces get_decay_config_data with a constant, the very function under
    test here. The config dir is read at call time (resolve_mech_file).
    """
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    progress_service = importlib.import_module("services.mech.progress_service")
    monkeypatch.setitem(progress_service._decay_config_cache, "data", None)
    monkeypatch.setitem(progress_service._decay_config_cache, "last_load", 0)
    return progress_service


def _own_file(tmp_path):
    path = tmp_path / "ddc_config" / "mech" / "decay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _expire(module):
    module._decay_config_cache["last_load"] = 0


def test_a_broken_own_file_falls_back_to_the_shipped_table(module, tmp_path):
    _own_file(tmp_path).write_text("{not json", encoding="utf-8")
    module._decay_config_cache["data"] = None
    _expire(module)
    assert module.decay_per_day(11) == 0, "the immortal level decays"
    assert module.decay_per_day(10) == 200


def test_the_last_good_own_table_outlives_a_bad_edit(module, tmp_path):
    own = _own_file(tmp_path)
    own.write_text('{"default": 50, "levels": {"10": 70, "11": 0}}', encoding="utf-8")
    module._decay_config_cache["data"] = None
    _expire(module)
    assert module.decay_per_day(10) == 70

    own.write_text("{not json", encoding="utf-8")
    _expire(module)
    assert module.decay_per_day(10) == 70, "the operator's own table was dropped"
