# -*- coding: utf-8 -*-
"""
THE FINDING (review C45, section 30 F3): the bot token is encrypted, and the
operator is shown a crash.

`encrypt_token` calls `security_manager.encrypt_existing_plaintext_token()` -
which does the work - and then `_log_security_action()` to write the audit
entry. Both catch `except (RuntimeError)` and nothing else. The audit helper
imports `action_logger` and `flask.session` inside itself, so an ImportError or
an AttributeError from that import or call passes both clauses and leaves the
service entirely. The client gets an unhandled exception where a
`SecurityResult` was meant to be returned - for an operation that had already
SUCCEEDED.

The same shape as review C26, in a different place: work is done, the report
says it failed.

Two things, not one. Writing the audit entry is not what the operation is for,
so a failure there must never undo it - `_log_security_action` swallows and
warns. And the method's own clause is a superset of what its callee can raise,
so a genuine failure still comes back as a SecurityResult instead of a
traceback.

The counter-checks keep both ends: a real encryption failure is still reported
as a failure, and the audit entry is still written when it can be.
"""

import sys
import types

import pytest

from services.web.security_service import (
    SecurityService,
    TokenEncryptionRequest,
)


@pytest.fixture
def service():
    """Inside a request context, because `flask.session` raises RuntimeError
    outside one - which the OLD narrow clause already caught, hiding the
    finding behind a different error."""
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = "spec"
    with app.test_request_context("/"):
        yield SecurityService()


def _token_manager(monkeypatch, succeeds=True):
    module = types.ModuleType("utils.token_security")

    class _Manager:
        @staticmethod
        def encrypt_existing_plaintext_token():
            return succeeds

    module.TokenSecurityManager = _Manager
    monkeypatch.setitem(sys.modules, "utils.token_security", module)


def _broken_action_logger(monkeypatch, error):
    module = types.ModuleType("services.infrastructure.action_logger")

    def _log_user_action(**kwargs):
        raise error

    module.log_user_action = _log_user_action
    monkeypatch.setitem(sys.modules, "services.infrastructure.action_logger", module)


@pytest.mark.parametrize("failure", [
    ImportError("action_logger is gone"),
    AttributeError("no session"),
    KeyError("user"),
])
def test_a_broken_audit_log_does_not_break_the_encryption(service, monkeypatch, failure):
    """THE FINDING: the token was encrypted - say so."""
    _token_manager(monkeypatch, succeeds=True)
    _broken_action_logger(monkeypatch, failure)

    result = service.encrypt_token(TokenEncryptionRequest())

    assert result.success is True, result.error


def test_a_real_encryption_failure_is_still_a_failure(service, monkeypatch):
    """COUNTER-CHECK: not every answer becomes a success."""
    _token_manager(monkeypatch, succeeds=False)

    result = service.encrypt_token(TokenEncryptionRequest())

    assert result.success is False
    assert result.status_code == 400


def test_the_audit_entry_is_still_written_when_it_can_be(service, monkeypatch):
    """COUNTER-CHECK: swallowing the failure is not skipping the entry."""
    written = []
    module = types.ModuleType("services.infrastructure.action_logger")
    module.log_user_action = lambda **kwargs: written.append(kwargs)
    monkeypatch.setitem(sys.modules, "services.infrastructure.action_logger", module)
    _token_manager(monkeypatch, succeeds=True)

    service.encrypt_token(TokenEncryptionRequest())

    assert written and written[0]["action"] == "TOKEN_ENCRYPT"
