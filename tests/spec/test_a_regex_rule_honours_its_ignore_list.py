# -*- coding: utf-8 -*-
"""A regex rule still honours its ignore keywords.

THE FINDING (Discord-input audit, 2026-09-26, F6): ``_check_match`` tried the
regex first and returned "matched" on a hit - before it ever read
``ignore_keywords``. A rule "regex 'server.*update', ignore 'test', RESTART
vrising" restarted vrising for "test: server update"; the ignore list, the
operator's brake against exactly such messages, applied only to keyword rules.

HOW THIS TEST CAN FAIL: it matches a regex rule against a message that holds
an ignore keyword, and against one that does not. The second must still
match, otherwise "never match" would pass the first.

COUNTER-CHECK (2026-09-26): red before on the ignored message, the plain
message green on both sides.
"""

import asyncio

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.automation_service import AutomationService, TriggerContext


def _rule():
    return AutoActionRule.from_dict({
        "id": "r1", "name": "regex rule", "enabled": True,
        "trigger": {"channel_ids": ["1"], "regex_pattern": r"server.*update",
                    "ignore_keywords": ["test"]},
        "action": {"type": "NOTIFY", "containers": []},
    })


def _matches(text):
    service = AutomationService.__new__(AutomationService)
    ctx = TriggerContext(message_id="1", channel_id="1", guild_id="9", user_id="2",
                         username="someone", is_webhook=False, content=text, embeds_text="")
    matched, _reason = asyncio.run(service._check_match(_rule(), ctx))
    return matched


def test_an_ignore_keyword_stops_a_regex_hit():
    assert not _matches("test: server update"), (
        "the regex matched and the ignore keyword 'test' was never read")


def test_a_plain_regex_hit_still_matches():
    assert _matches("server update available")
