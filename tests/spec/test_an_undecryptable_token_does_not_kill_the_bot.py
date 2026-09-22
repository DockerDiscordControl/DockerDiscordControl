# -*- coding: utf-8 -*-
"""A token that cannot be decrypted lets the bot retry, instead of killing it.

THE FINDING (review E7). `bot.py:294` is a retry loop, and its own log line
says what it is for:

    while True:
        token = get_decrypted_bot_token(runtime)
        if token:
            break
        runtime.logger.error("FATAL: Bot token not found or could not be decrypted.")
        ... wait DDC_TOKEN_RETRY_INTERVAL seconds and try again ...

So the operator can fix the token in the web panel and the bot picks it up by
itself, with no restart. There is no try/except around that call.

`get_decrypted_bot_token` asks `config_service.decrypt_token`, which raises
`TokenEncryptionError` when the stored token does not match the stored
password hash - a mismatched pair from a restored backup, a hand-edited
config, a password change that did not finish. Its two handlers list

    (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError)
    (RuntimeError)

and `TokenEncryptionError` descends from `ConfigServiceError` ->
`DDCBaseException` -> `Exception`. It is none of those. So the one error the
retry loop was written for is the one that escapes it, and the process dies
with a traceback instead of waiting for the operator.

Sixth time this shape has been found (C6, C33, D20, D25, E3): a narrow handler
that cannot catch what the call below it raises. Found by scanning for it
rather than by reading on - every try-block in the tree that calls a known
DDC-raising function without a handler able to catch it, eleven of them.

Worth recording next to the coverage ledger: this file reads
`pass1:s33:1-101` - a reviewer was handed all 101 lines of it and reported
nothing. "Handed to a reviewer" is not "read carefully", which is why that
caveat is in the ledger's header.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.bot.token as bot_token
from services.exceptions import TokenEncryptionError

ENCRYPTED = "gAAAAABmFakeCiphertext"
HASH = "pbkdf2:sha256:600000$abc$def"
# Deliberately NOT shaped like a Discord token. The first version of this
# file used a realistic-looking fake and GitHub's push protection blocked
# the push - correctly: a token-shaped string does not belong in a repo,
# invented or not. Nothing on this path validates the shape, so the value
# only has to be recognisable when it comes back.
RESOLVED_TOKEN = "a-token-this-test-made-up"


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("utils.config_paths.get_config_dir", lambda: tmp_path)

    service = MagicMock()
    service.get_config.return_value = {"bot_token": ENCRYPTED,
                                       "web_ui_password_hash": HASH}
    return SimpleNamespace(
        logger=MagicMock(),
        config={},
        dependencies=SimpleNamespace(config_service_factory=lambda: service),
    ), service


def test_a_mismatched_token_does_not_escape(runtime):
    """The finding: the retry loop above has no handler of its own."""
    rt, service = runtime
    service.decrypt_token.side_effect = TokenEncryptionError(
        "Invalid token or encryption key", error_code="TOKEN_DECRYPTION_INVALID_TOKEN")

    token = bot_token.get_decrypted_bot_token(rt)

    assert token is None, (
        "a token that cannot be decrypted must come back as 'no token', so the "
        "loop in bot.py logs it and waits for the operator"
    )


def test_the_reason_reaches_the_log(runtime):
    """It must not become silent either - the operator has to know what to fix."""
    rt, service = runtime
    service.decrypt_token.side_effect = TokenEncryptionError(
        "Invalid token or encryption key", error_code="TOKEN_DECRYPTION_INVALID_TOKEN")

    bot_token.get_decrypted_bot_token(rt)

    said = " ".join(str(call) for call in rt.logger.mock_calls)
    assert "decrypt" in said.lower() or "token" in said.lower(), said


def test_a_token_that_decrypts_is_still_returned(runtime):
    """The counter-case: refusing everything would satisfy the test above."""
    rt, service = runtime
    service.decrypt_token.return_value = RESOLVED_TOKEN

    assert bot_token.get_decrypted_bot_token(rt) == RESOLVED_TOKEN


def test_a_pre_decrypted_token_is_still_preferred(runtime):
    """A pin on the path that does not decrypt at all."""
    rt, service = runtime
    service.get_config.return_value = {"bot_token_decrypted_for_usage": RESOLVED_TOKEN}

    assert bot_token.get_decrypted_bot_token(rt) == RESOLVED_TOKEN
    service.decrypt_token.assert_not_called()


def test_the_manual_path_refuses_the_same_way(runtime, tmp_path):
    """The second handler, which the first one hides in every test above.

    Probe M2 removed it and nothing went red - because the ConfigService path
    catches first and never reaches this one. An untested handler is what this
    programme exists to find, so the manual decryption path gets its own case:
    the ConfigService yields nothing, and the token is read straight out of
    bot_config.json and web_config.json instead.
    """
    import json

    rt, service = runtime
    service.get_config.return_value = {}                    # nothing from the service
    service.decrypt_token.side_effect = TokenEncryptionError(
        "Invalid token or encryption key", error_code="TOKEN_DECRYPTION_INVALID_TOKEN")
    (tmp_path / "bot_config.json").write_text(json.dumps({"bot_token": ENCRYPTED}),
                                              encoding="utf-8")
    (tmp_path / "web_config.json").write_text(json.dumps({"web_ui_password_hash": HASH}),
                                              encoding="utf-8")

    assert bot_token.get_decrypted_bot_token(rt) is None
    said = " ".join(str(call) for call in rt.logger.mock_calls)
    assert "do not match" in said or "decrypt" in said.lower(), said
