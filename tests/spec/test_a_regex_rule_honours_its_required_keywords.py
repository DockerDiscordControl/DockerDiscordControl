# -*- coding: utf-8 -*-
"""A regex rule still honours its required keywords.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F1, verified
2026-09-29). _check_match returned "matched" on a regex hit before it read
required_keywords (and a regex-only miss returned before them too). A rule
"regex 'update', required 'valheim', RESTART valheim" restarted Valheim for
"update available for minecraft" - the keyword the operator marked as
required was never asked. The panel's own rule tester checks the required
keywords first and showed NO MATCH for the same message, so the test and
the real run disagreed. Same shape as the ignore-list finding of 2026-09-26
(test_a_regex_rule_honours_its_ignore_list.py).

THE CONTRACT: required keywords are checked before the regex, like the
ignore list; a regex hit counts only when every required keyword is there.

HOW THIS TEST CAN FAIL: a regex hit returns before the required keywords again.

COUNTER-CHECK (2026-09-29): written before the fix and red then on the
first case; the second stays green (otherwise "never match" would pass).
"""

import asyncio

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.automation_service import AutomationService, TriggerContext


def _rule():
    return AutoActionRule.from_dict({
        "id": "r1", "name": "regex rule", "enabled": True,
        "trigger": {"channel_ids": ["1"], "regex_pattern": r"update",
                    "required_keywords": ["valheim"]},
        "action": {"type": "NOTIFY", "containers": []},
    })


def _matches(text):
    service = AutomationService.__new__(AutomationService)
    ctx = TriggerContext(message_id="1", channel_id="1", guild_id="9", user_id="2",
                         username="someone", is_webhook=False, content=text, embeds_text="")
    matched, _reason = asyncio.run(service._check_match(_rule(), ctx))
    return matched


def test_a_regex_hit_without_the_required_keyword_does_not_match():
    assert not _matches("update available for minecraft"), (
        "the regex matched and the required keyword 'valheim' was never read")


def test_a_regex_hit_with_the_required_keyword_matches():
    assert _matches("valheim update available")
