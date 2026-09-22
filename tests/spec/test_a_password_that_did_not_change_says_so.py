# -*- coding: utf-8 -*-
"""A password change that failed says it was the password.

THE FINDING (review E10, scan hit 3 of 9). `process_config_form` asks
`change_web_ui_password`, whose own docstring lists what it raises:

    Raises:
        ValueError: If the password is empty or too short (user-readable message).
        TokenEncryptionError: If the token cannot be re-encrypted.
        ConfigSaveError: If the new configuration cannot be persisted.

and catches the first one only:

    except ValueError as e:
        return current_config, False, f"Web UI password not changed: {e}. Nothing was saved."

The other two escape the form parser. They are caught further out, by
`save_config_api`'s `except ConfigServiceError` (review D25), and turned into
"Error saving configuration" - which is true and useless. The operator typed a
new password, the disk was full, and they are told something about the
configuration, with no answer to the only question that matters: **is my
password changed or not?**

Nothing is lost either way: ConfigSaveError means the write did not happen and
TokenEncryptionError is raised before it, so the stored hash and the stored
token stay as they were. What was wrong is only what the operator is told -
the same principle as D25 and E3, one layer up.
"""

from unittest.mock import MagicMock

import pytest

from services.config.config_form_parser_service import ConfigFormParserService
from services.exceptions import ConfigSaveError, TokenEncryptionError

# The form field is new_web_ui_password; with the wrong name the branch under
# test is never entered and every case goes red for nothing.
FORM = {"new_web_ui_password": "Sehr-Gut-1234",
        "confirm_web_ui_password": "Sehr-Gut-1234"}


@pytest.fixture
def parser(monkeypatch):
    """The form path with the password change to order.

    process_config_form takes the config service as its third argument - it is
    not looked up inside. The first version of this file called it with two and
    every case failed on a TypeError, which is a red for the wrong reason.
    """
    import services.config.config_service as config_service

    service = MagicMock()
    service.get_config.return_value = {"servers": []}

    def _set(behaviour):
        def _change(password, **kwargs):
            if isinstance(behaviour, BaseException):
                raise behaviour
            return None
        monkeypatch.setattr(config_service, "change_web_ui_password", _change)
        return service

    return _set


def _run(service, form=None):
    return ConfigFormParserService.process_config_form(
        dict(form or FORM), {"servers": []}, service)


@pytest.mark.parametrize("error", [
    ConfigSaveError("config.json: read-only file system"),
    TokenEncryptionError("the bot token could not be re-encrypted"),
])
def test_a_failed_change_is_reported_as_a_password_problem(parser, error):
    """The finding: the operator asked about a password and hears about config."""
    service = parser(error)

    _config, ok, message = _run(service)

    assert ok is False
    assert "password" in message.lower(), (
        f"the password could not be changed and the answer is: {message!r}"
    )


@pytest.mark.parametrize("error", [
    ConfigSaveError("config.json: read-only file system"),
    TokenEncryptionError("the bot token could not be re-encrypted"),
])
def test_it_says_that_nothing_was_saved(parser, error):
    """The only other question: is my password changed now, or not?"""
    service = parser(error)

    _config, _ok, message = _run(service)

    assert "nothing was saved" in message.lower(), message


def test_a_password_that_is_refused_still_says_why(parser):
    """A pin on the handler that was already there."""
    service = parser(ValueError("Password must be at least 12 characters long"))

    _config, ok, message = _run(service)

    assert ok is False
    assert "12 characters" in message, message


def test_a_change_that_works_is_not_reported_as_a_failure(parser):
    """The counter-case: refusing everything would satisfy the tests above."""
    service = parser(None)

    _config, ok, message = _run(service)

    assert ok is not False or "password" not in (message or "").lower(), (
        f"a working password change was reported as: {message!r}"
    )
