# -*- coding: utf-8 -*-
"""Saving the bot token in the Web UI is not a problem, so it is not a warning.

THE OPERATOR (2026-09-25): "does every message make sense now?" This one did
not, and it is the one that quietly damaged all the others:

    WARNING  ⚠️  Environment variable DISCORD_BOT_TOKEN not found,
                 falling back to config file

It was the ONLY warning in 579 lines of his log. And it describes the normal,
documented, recommended-by-the-panel way of running DDC: you type the token
into the Web UI, and the Web UI saves it to config.json. There is no fault
here, nothing to fix, and nothing he could have done differently - the second
path is not a fallback from a failure, it is the other supported option.

WHY THIS MATTERS MORE THAN ONE LINE. A warning is a promise that something
wants attention. When the only warning a log ever shows is the normal case,
the promise is broken in the one direction that cannot be recovered: the next
warning, the one about a token that really cannot be decrypted, arrives looking
exactly like the one he has learned to ignore. Today's other findings were all
noise or untruth; this one taught him to skip the level that matters.

THE RULE: a configuration DDC supports does not warn. Warnings are kept for
the states an operator can and should act on - and the function still has one,
for a stored token that cannot be decrypted, which says what to do about it.

HOW THIS TEST CAN FAIL: a supported way of supplying the token starts warning,
or the genuinely broken case stops.

COUNTER-CHECK (2026-09-25): red before - the case that resolves a token from
the config caught one WARNING record.
"""

import logging
from types import SimpleNamespace

import pytest

from app.bot.token import get_decrypted_bot_token


@pytest.fixture
def runtime(monkeypatch):
    """A BotRuntime stand-in, with no token in the environment."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    return lambda config, factory=None: SimpleNamespace(
        logger=logging.getLogger("ddc_token_under_test"),
        config=config,
        dependencies=SimpleNamespace(config_service_factory=factory))


def _levels(caplog):
    return {record.levelno for record in caplog.records}


def test_a_token_from_the_web_ui_raises_no_warning(runtime, caplog):
    """THE FINDING. This is how almost every installation is configured."""
    with caplog.at_level(logging.DEBUG, logger="ddc_token_under_test"):
        token = get_decrypted_bot_token(
            runtime({"bot_token_decrypted_for_usage": "a-token-from-the-panel"}))

    assert token == "a-token-from-the-panel"
    assert logging.WARNING not in _levels(caplog), (
        "the normal way of configuring DDC still warns: "
        f"{[r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]}")


def test_a_token_from_the_environment_raises_no_warning(runtime, caplog, monkeypatch):
    """Counter-check: the other supported path must stay quiet too, or the
    rule would just have moved rather than been applied."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-token-from-the-environment")
    with caplog.at_level(logging.DEBUG, logger="ddc_token_under_test"):
        token = get_decrypted_bot_token(runtime({}))

    assert token == "a-token-from-the-environment"
    assert logging.WARNING not in _levels(caplog)


def test_it_still_says_which_source_was_used(runtime, caplog):
    """The point is not silence. Somebody debugging a login needs to know
    WHICH of the two supplied the token - that answer is safe and useful."""
    with caplog.at_level(logging.DEBUG, logger="ddc_token_under_test"):
        get_decrypted_bot_token(runtime({"bot_token_decrypted_for_usage": "t"}))

    assert any("config" in record.getMessage().lower() for record in caplog.records), (
        [r.getMessage() for r in caplog.records])


def test_a_token_that_cannot_be_decrypted_still_warns(runtime, caplog):
    """THE CASE THE LEVEL EXISTS FOR, and the reason this is not simply
    "turn the warnings down". A stored token that will not decrypt - a restored
    backup, a half-finished password change - is something the operator must
    act on, and the message says where."""
    def _broken_service():
        raise RuntimeError("stored token and password hash do not belong together")

    with caplog.at_level(logging.DEBUG, logger="ddc_token_under_test"):
        get_decrypted_bot_token(runtime({}, factory=_broken_service))

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]

    assert warnings, "a token that cannot be decrypted now passes in silence"
    assert any("Web UI" in message for message in warnings), warnings
