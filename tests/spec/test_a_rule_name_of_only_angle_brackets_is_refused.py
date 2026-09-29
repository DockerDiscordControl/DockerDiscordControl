# -*- coding: utf-8 -*-
"""A rule name that is empty once cleaned is refused, not saved nameless.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F11): the name
was checked raw and cleaned afterwards. "<>" passed "Rule name is required",
lost both characters to the cleaning and was stored as "" - the panel showed
a nameless rule and had reported success.

THE CONTRACT: the name is judged as it will be stored.

HOW THIS TEST CAN FAIL: "<>" is accepted again.

COUNTER-CHECK (2026-09-29): red before the change; a real name is accepted
before and after.
"""

import pytest

from services.automation.auto_action_config_service import validate_rule_data


def _rule(name):
    return {"name": name, "enabled": True,
            "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["update"]},
            "actions": [{"container": "vrising", "action": "restart"}]}


@pytest.mark.parametrize("name", ["<>", " < > "])
def test_a_name_that_cleans_to_nothing_is_refused(name):
    valid, message, _ = validate_rule_data(_rule(name))
    assert not valid and "Rule name is required" in message, message


def test_a_real_name_is_accepted():
    assert validate_rule_data(_rule("Restart <Valheim>"))[0]
