# -*- coding: utf-8 -*-
"""Required and ignore keywords of a rule are bounded like its trigger keywords.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 3 F2): the
limits of 50 keywords and 100 characters each applied to trigger.keywords
only. required_keywords and ignore_keywords - matched against every message
the same way - were saved unbounded, any count, any length.

THE CONTRACT: all three lists have the same limits.

HOW THIS TEST CAN FAIL: an over-long or over-full required or ignore list is
accepted again.

COUNTER-CHECK (2026-09-29): the required/ignore cases red before the change;
a rule within the limits is accepted before and after.
"""

import pytest

from services.automation.auto_action_config_service import (MAX_KEYWORD_LENGTH, MAX_KEYWORDS,
                                                            validate_rule_data)

CHANNEL = "123456789012345678"


def _rule(**trigger):
    return {"name": "rule", "enabled": True,
            "trigger": {"channel_ids": [CHANNEL], "keywords": ["update"], **trigger},
            "actions": [{"container": "vrising", "action": "restart"}]}


@pytest.mark.parametrize("field", ["required_keywords", "ignore_keywords"])
def test_too_many_are_refused(field):
    valid, message, _ = validate_rule_data(_rule(**{field: [f"k{n}" for n in range(MAX_KEYWORDS + 1)]}))
    assert not valid and "Too many" in message, message


@pytest.mark.parametrize("field", ["required_keywords", "ignore_keywords"])
def test_too_long_is_refused(field):
    valid, message, _ = validate_rule_data(_rule(**{field: ["x" * (MAX_KEYWORD_LENGTH + 1)]}))
    assert not valid and "too long" in message, message


def test_a_rule_within_the_limits_is_accepted():
    valid, message, _ = validate_rule_data(_rule(required_keywords=["now"], ignore_keywords=["test"]))
    assert valid, message
