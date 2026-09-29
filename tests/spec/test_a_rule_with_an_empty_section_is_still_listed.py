# -*- coding: utf-8 -*-
"""A rule with a null section is still listed and run, with the section's defaults.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F13): a rule
whose "trigger", "action", "safety" or "source_filter" was null (a hand
edit) made from_dict raise AttributeError; get_rules dropped it with only a
log line. The panel showed one rule fewer and automation never ran it,
while the rule stayed in the file.

THE CONTRACT: a null section is an empty one - its defaults apply.

HOW THIS TEST CAN FAIL: the rule vanishes from the list again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import json

import pytest

import services.automation.auto_action_config_service as aacs

GOOD = {"id": "a", "name": "good", "enabled": True,
        "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["update"]},
        "action": {"type": "NOTIFY"}}


@pytest.mark.parametrize("section", ["safety", "action"])
def test_a_null_section_does_not_hide_the_rule(monkeypatch, tmp_path, section):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    odd = dict(GOOD, id="b", name="odd", **{section: None})
    (tmp_path / "auto_actions.json").write_text(json.dumps(
        {"global_settings": {"enabled": True}, "auto_actions": [GOOD, odd]}), encoding="utf-8")

    rules = aacs.AutoActionConfigService().get_rules()

    assert [r.id for r in rules] == ["a", "b"], f"a rule with a null {section} vanished"


def test_a_null_source_filter_does_not_hide_the_rule(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    odd = dict(GOOD, id="b", trigger=dict(GOOD["trigger"], source_filter=None))
    (tmp_path / "auto_actions.json").write_text(json.dumps(
        {"global_settings": {"enabled": True}, "auto_actions": [GOOD, odd]}), encoding="utf-8")

    assert len(aacs.AutoActionConfigService().get_rules()) == 2
