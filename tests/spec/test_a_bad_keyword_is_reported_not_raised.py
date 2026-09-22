# -*- coding: utf-8 -*-
"""A keyword the panel should reject is reported, not raised.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 10 F5, re-checked 2026-09-20):
``validate_rule_data`` measures a keyword with ``len(str(kw))`` - so a number
is measured, not refused - and then builds the error message with
``kw[:20]``. Slicing something that is not a string raises TypeError, which
leaves the validator instead of the "Keyword too long" it was about to
report. The validator is what stands between the web panel and
``auto_actions.json``: whoever sends a rule whose keyword is a very large
number gets a raw traceback rather than an answer.
"""

import pytest

from services.automation.auto_action_config_service import (MAX_KEYWORD_LENGTH,
                                                            validate_rule_data)

CHANNEL = "123456789012345678"


def _rule(keywords):
    return {
        "name": "test rule",
        "enabled": True,
        "trigger": {"channel_ids": [CHANNEL], "keywords": keywords},
        "actions": [{"container": "vrising", "action": "restart"}],
    }


# validate_rule_data returns (is_valid, error_message, warnings) - the errors
# are joined into the message, the third value carries warnings.


def test_a_sound_rule_is_accepted():
    """Premise: an ordinary keyword passes."""
    valid, message, _warnings = validate_rule_data(_rule(["restart please"]))

    assert valid, message


def test_a_long_keyword_is_reported():
    """Premise: the length limit itself works, for a string."""
    valid, message, _warnings = validate_rule_data(_rule(["x" * (MAX_KEYWORD_LENGTH + 1)]))

    assert not valid
    assert "too long" in message.lower(), message


def test_a_keyword_that_is_not_text_is_reported():
    valid, message, _warnings = validate_rule_data(_rule([10 ** (MAX_KEYWORD_LENGTH + 5)]))

    assert not valid, "a keyword of 105 digits is not a keyword"
    assert "too long" in message.lower(), message
