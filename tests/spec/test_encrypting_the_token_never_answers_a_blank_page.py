# -*- coding: utf-8 -*-
"""Pressing "encrypt token" gets an answer, not a blank 500.

THE FINDING (review E11, scan hits 2 and 9 of 9 - one chain). The panel's
token-encryption button walks through three layers, and `TokenEncryptionError`
- which is what `encrypt_token` raises - passes all three:

    utils/token_security.py:69      (OSError, ValueError, AttributeError,
                                     TypeError, RuntimeError)
    services/web/security_service.py:134
                                    (ImportError, AttributeError, KeyError,
                                     TypeError, ValueError, RuntimeError)
    app/blueprints/security_routes.py:99
                                    (ImportError, AttributeError, RuntimeError),
                                    (ValueError, TypeError, KeyError)

TokenEncryptionError descends from ConfigServiceError -> DDCBaseException ->
Exception and is in none of them. So it reaches Flask, and the operator
presses a security button and gets a blank error page.

The innermost handler states the intent it does not achieve, in its own
comment: *"The migration is optional - never let it break the startup."*

Seventh time for this shape in this programme (C6, C33, D20, D25, E3, E7).
It keeps happening because the handlers were written by reading the code
below them, and the exception is raised three calls further down.
"""

from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.blueprints.security_routes import security_bp
from services.exceptions import TokenEncryptionError

# The blueprint carries url_prefix="/api", so the button posts to
# /api/encrypt-token. Posting to /encrypt-token answers 404 in HTML and
# every case goes red for the wrong reason.
ROUTE = "/api/encrypt-token"


@pytest.fixture
def client(monkeypatch):
    """The route with auth stubbed and the encryption to order."""
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    manager = MagicMock()
    monkeypatch.setattr("utils.token_security.TokenSecurityManager", lambda: manager)

    app = Flask(__name__)
    app.config["TESTING"] = True
    # The point is the ANSWER the panel receives, not whether the exception
    # reaches the test.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.register_blueprint(security_bp)
    return app.test_client(), manager


def test_a_failed_encryption_is_answered_in_json(client):
    """The finding: the operator pressed a button and got a blank page."""
    http, manager = client
    manager.encrypt_existing_plaintext_token.side_effect = TokenEncryptionError(
        "Invalid input for token encryption", error_code="TOKEN_ENCRYPTION_INVALID_INPUT")

    response = http.post(ROUTE)

    assert response.mimetype == "application/json", (
        f"the panel receives {response.mimetype} and parses it as JSON"
    )
    assert (response.get_json() or {}).get("success") is False, response.get_json()


def test_the_answer_says_it_was_the_token(client):
    """Not just "an error" - the operator has to know what failed."""
    http, manager = client
    manager.encrypt_existing_plaintext_token.side_effect = TokenEncryptionError(
        "Invalid input for token encryption", error_code="TOKEN_ENCRYPTION_INVALID_INPUT")

    payload = http.post(ROUTE).get_json() or {}

    assert payload.get("error"), "told it failed and not why"
    assert "token" in str(payload.get("error")).lower(), payload


def test_the_migration_itself_answers_false_instead_of_raising(monkeypatch):
    """The innermost layer, whose comment already promises exactly this."""
    from utils.token_security import TokenSecurityManager

    manager = TokenSecurityManager.__new__(TokenSecurityManager)
    manager.config_service = MagicMock()
    # A plaintext token and a password hash, delivered the way the ConfigService
    # delivers them since review E55 - from config.json. This used to redirect
    # the config directory to a pair of v1 files (bot_config.json and
    # web_config.json), which no running v2.4 installation has.
    manager.config_service.get_config.return_value = {
        "bot_token": "NOT-A-REAL-TOKEN.for-tests-only.padded-past-fifty-chars",
        "web_ui_password_hash": "pbkdf2:sha256:600000$abc$def",
    }
    manager.config_service.encrypt_token.side_effect = TokenEncryptionError(
        "Invalid input for token encryption", error_code="TOKEN_ENCRYPTION_INVALID_INPUT")

    assert manager.encrypt_existing_plaintext_token() is False
    manager.config_service.update_config_fields.assert_not_called()



def test_an_encryption_that_works_still_reports_success(client):
    """The counter-case: refusing everything would satisfy the tests above."""
    http, manager = client
    manager.encrypt_existing_plaintext_token.return_value = True

    payload = http.post(ROUTE).get_json() or {}

    assert payload.get("success") is True, payload


def test_the_route_answers_even_when_the_service_itself_falls_over(monkeypatch):
    """The outermost handler, reached on purpose.

    The two layers below now catch TokenEncryptionError, so the route's own
    handler is unreachable through them - which would make fixing it an
    untested change, and untested handlers are what this programme is about.
    Here the service FACTORY raises instead, which reaches the route directly.
    """
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    def _explode():
        raise TokenEncryptionError("the encryption key could not be derived",
                                   error_code="TOKEN_ENCRYPTION_INVALID_INPUT")

    monkeypatch.setattr("services.web.security_service.get_security_service", _explode)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.register_blueprint(security_bp)

    response = app.test_client().post(ROUTE)

    assert response.mimetype == "application/json", response.mimetype
    payload = response.get_json() or {}
    assert payload.get("success") is False, payload
    assert "token" in str(payload.get("error")).lower(), payload


def test_the_service_layer_answers_when_the_manager_cannot_even_be_built(monkeypatch):
    """The middle handler, reached on purpose.

    Probe M2 removed this layer's fix and nothing went red: the layer below
    catches first, so the change sat there untested - exactly what this
    programme keeps finding in other people's code. Here the MANAGER's
    constructor raises, which is inside the service's try and outside
    token_security's, so the middle handler is the one that has to answer.
    """
    from services.web.security_service import SecurityService, TokenEncryptionRequest

    def _explode():
        raise TokenEncryptionError("the encryption key could not be derived",
                                   error_code="TOKEN_ENCRYPTION_INVALID_INPUT")

    monkeypatch.setattr("utils.token_security.TokenSecurityManager", _explode)

    service = SecurityService.__new__(SecurityService)
    service.logger = MagicMock()

    result = service.encrypt_token(TokenEncryptionRequest())

    assert result.success is False
    assert result.error, "the service returned a failure with no reason"
