# -*- coding: utf-8 -*-
"""A token that could not be decrypted must not be passed off as one that was.

THE FINDING (review E26, services/config/config_service.py):
``_decrypt_token_if_needed`` ends with a bare ``return token``, and that line
is reached in two ways that are not "the token was already plaintext":

1. there is **no** ``web_ui_password_hash``, so the decryption branch is
   skipped entirely and the ENCRYPTED token is returned as if usable;
2. the decryption ran, raised nothing, and produced something that is not a
   Discord token.

``get_config`` then does:

    if decrypted_token:
        logger.info("Successfully decrypted token for usage")
        config['bot_token_decrypted_for_usage'] = decrypted_token

So the ciphertext is handed to the bot as its login token, and the log line
says the opposite of what happened. The operator sees Discord reject the token
with "Improper token has been passed" and a DDC log that reports a successful
decryption - which sends them looking for a wrong token instead of a missing
password.

A config with an encrypted token and no password hash is not hypothetical:
``_repair_bot_token`` exists for exactly that state and handles it on SAVE
(`:414`) and in the legacy fold (`:933`). The READ path had nothing.

The fix is the smallest honest one: a token that does not look like a Discord
token and could not be turned into one is **not a token**, and ``None`` is the
answer. The paths above it already handle "no usable token" properly - that is
what reviews E7, E10 and E11 were about.

Measured before changing it, because the risk of the heuristic being too
strict is a bot that cannot log in: a Discord bot token is three dot-separated
parts (`looks_like_discord_token` accepts on `'.' in token and len > 50`), and
a Fernet ciphertext is dotless base64url starting `gAAAAA`. The two do not
overlap.
"""

import logging

import pytest


ENCRYPTED = "gAAAAABn" + "x" * 80          # Fernet-shaped: no dots, long
PLAINTEXT = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl." + "m" * 40   # Discord-shaped


@pytest.fixture
def service():
    from services.config.config_service import ConfigService
    from services.config.config_validation_service import ConfigValidationService

    instance = ConfigService.__new__(ConfigService)
    instance._validation_service = ConfigValidationService
    return instance


def test_the_heuristic_tells_the_two_apart(service):
    """The whole fix rests on this, so it is measured and not assumed."""
    looks_like = service._validation_service.looks_like_discord_token

    assert looks_like(PLAINTEXT) is True, "a real-shaped bot token was rejected"
    assert looks_like(ENCRYPTED) is False, "a Fernet ciphertext passed as a token"


def test_an_encrypted_token_without_a_password_is_not_returned(service, caplog):
    with caplog.at_level(logging.DEBUG):
        result = service._decrypt_token_if_needed(ENCRYPTED, None)

    assert result is None, (
        "the encrypted token was handed back as the bot's login token; Discord "
        "answers 'Improper token has been passed' and DDC's log claims the "
        "decryption succeeded"
    )


def test_the_reason_is_named(service, caplog):
    """'Decryption failed' and 'there is no password' are different problems."""
    with caplog.at_level(logging.DEBUG):
        service._decrypt_token_if_needed(ENCRYPTED, None)

    messages = " ".join(r.getMessage() for r in caplog.records
                        if r.levelno >= logging.WARNING)
    assert messages, "nothing was logged at all"
    assert "password" in messages.lower(), (
        f"the operator is not told that the missing piece is the Web UI "
        f"password, so they go looking for a wrong token: {messages!r}"
    )


def test_a_plaintext_token_is_still_returned(service):
    """Counter-check, and the one that matters: do not break a working bot."""
    assert service._decrypt_token_if_needed(PLAINTEXT, None) == PLAINTEXT
    assert service._decrypt_token_if_needed(PLAINTEXT, "some-hash") == PLAINTEXT


def test_no_token_is_still_no_token(service):
    assert service._decrypt_token_if_needed("", "some-hash") is None
    assert service._decrypt_token_if_needed(None, "some-hash") is None
