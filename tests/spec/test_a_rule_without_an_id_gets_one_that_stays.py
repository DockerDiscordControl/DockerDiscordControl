# -*- coding: utf-8 -*-
"""A rule written without an id gets one id, kept, so the panel can act on it.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F9): a rule in
auto_actions.json without an "id" (written by hand) got a fresh uuid on every
read. The panel listed it under a changing id; toggle, edit and delete
answered "Rule not found"; its trigger count was never kept - and yet it
fired, because the message handler runs whatever get_rules() returns.

THE CONTRACT: the first read gives such a rule an id and writes it down;
every later read sees the same id.

HOW THIS TEST CAN FAIL: the id changes between reads again, or the rule
cannot be deleted by the id the panel shows.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import json

import services.automation.auto_action_config_service as aacs

RULE = {"name": "hand-written", "enabled": True,
        "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["update"]},
        "action": {"type": "RESTART", "containers": ["vrising"]}}


def test_the_rule_keeps_the_id_it_is_shown_with(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "auto_actions.json").write_text(json.dumps(
        {"global_settings": {"enabled": True}, "auto_actions": [RULE]}), encoding="utf-8")
    service = aacs.AutoActionConfigService()

    shown = service.get_rules()[0].id
    assert service.get_rules()[0].id == shown, "the id changed between two reads"
    assert service.get_rule(shown) is not None
    assert service.delete_rule(shown).success, "the rule the panel shows cannot be deleted"
