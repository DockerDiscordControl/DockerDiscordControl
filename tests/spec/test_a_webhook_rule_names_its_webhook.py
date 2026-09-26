# -*- coding: utf-8 -*-
"""A "webhook only" auto-action rule names the webhook it trusts.

THE FINDING (Discord-input audit, 2026-09-26): "Only trigger on Webhook
messages" sounds like a source filter and is none. Any webhook in the
channel - one a moderator made for a bot, one a leaked URL lets anybody post
through - satisfies it, under any name it likes. A rule "webhook only,
keyword 'restart', action RESTART vrising" restarted vrising for whoever held
any webhook URL of that channel. And the username fallback made it worse:
a webhook sets its display name per message, so an allowed username vouched
for nothing.

THE OPERATOR'S DECISION (2026-09-26): a webhook-only rule must name the
webhook's ID (a webhook message carries it as the author id). An ACTIVE rule
without one is refused on save; switching such a rule OFF still works, and
the panel marks existing ones.

HOW THIS TEST CAN FAIL: it validates rules with and without an ID, active and
inactive, and it hands the pre-filter a webhook message whose name matches
an allowed username but whose id does not.

COUNTER-CHECK (2026-09-26): red before on the refusal and on the spoofed
name; the rule with an ID, the switched-off rule and the person matched by
username stayed green on both sides.
"""

from services.automation.auto_action_config_service import AutoActionRule, validate_rule_data
from services.automation.automation_service import AutomationService, TriggerContext

CHANNEL = "123456789012345678"
WEBHOOK = "223456789012345678"


def _rule(*, ids=(), usernames=(), enabled=True):
    return {
        "id": "r1",
        "name": "webhook rule",
        "enabled": enabled,
        "trigger": {
            "channel_ids": [CHANNEL],
            "keywords": ["restart"],
            "source_filter": {"allowed_user_ids": list(ids),
                              "allowed_usernames": list(usernames),
                              "is_webhook": True},
        },
        "action": {"type": "NOTIFY", "containers": []},
    }


def test_an_active_webhook_rule_without_an_id_is_refused():
    valid, message, _ = validate_rule_data(_rule())
    assert not valid, "a webhook-only rule without a webhook ID was accepted"
    assert "webhook" in message.lower(), message


def test_a_webhook_rule_with_an_id_is_accepted():
    valid, message, _ = validate_rule_data(_rule(ids=[WEBHOOK]))
    assert valid, message


def test_switching_an_old_rule_off_still_works():
    valid, message, _ = validate_rule_data(_rule(enabled=False))
    assert valid, f"an operator could not switch off the rule they must fix: {message}"


def _ctx(*, user_id, username, is_webhook):
    return TriggerContext(message_id="1", channel_id=CHANNEL, guild_id="9",
                          user_id=user_id, username=username, is_webhook=is_webhook,
                          content="restart", embeds_text="")


def _passes(rule_dict, ctx):
    service = AutomationService.__new__(AutomationService)
    return bool(service._pre_filter_rules([AutoActionRule.from_dict(rule_dict)], ctx))


def test_a_webhook_cannot_borrow_an_allowed_name():
    rule = _rule(ids=[WEBHOOK], usernames=["GitHub"])
    spoof = _ctx(user_id="999999999999999999", username="GitHub", is_webhook=True)
    assert not _passes(rule, spoof), (
        "another webhook, posting as 'GitHub', passed the webhook ID filter")


def test_the_named_webhook_still_triggers():
    rule = _rule(ids=[WEBHOOK], usernames=["GitHub"])
    assert _passes(rule, _ctx(user_id=WEBHOOK, username="anything", is_webhook=True))


def test_a_person_still_matches_by_username():
    rule = _rule(ids=["323456789012345678"], usernames=["alice"])
    rule["trigger"]["source_filter"]["is_webhook"] = None
    assert _passes(rule, _ctx(user_id="1", username="alice", is_webhook=False)), (
        "the username fallback for people is untouched by this rule")
