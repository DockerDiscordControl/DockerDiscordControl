# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for the verified-credential cache in app/auth.py.

HTTP Basic Auth sends the credentials with every request, so verify_password() ran the full
key derivation each time (measured in production: 85.6 ms, against 2.2 ms for an
unauthenticated request). The cache stores only ALREADY verified credentials.

These tests pin both directions on purpose. "Fewer key derivations" is also what a broken
authentication looks like, so every speed-up test here has a matching test proving that wrong
credentials are still rejected and still pay the full price.
"""

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app import auth as auth_module

# Cheap iteration count: these tests care about how OFTEN the derivation runs, not how long it
# takes. The production method (600,000 iterations) is unchanged and asserted in
# tests/security/test_security_sast.py.
PASSWORD = "correct-horse-battery"
WRONG_PASSWORD = "wrong-horse-battery"


def _hash(password):
    return generate_password_hash(password, method="pbkdf2:sha256:1")


@pytest.fixture
def auth_env(monkeypatch):
    """App context + stubbed config + a counter for the key derivation."""
    app = Flask(__name__)
    # Needed by the first-time-setup branch: it writes session['setup_mode'], and Flask refuses
    # to touch a session without a signing key ("The session is unavailable because no secret
    # key was set"). Only the test app needs this; production gets its key from FLASK_SECRET_KEY.
    app.secret_key = "test-secret-credential-cache"

    config_state = {
        "web_ui_user": "admin",
        "web_ui_password_hash": _hash(PASSWORD),
    }
    monkeypatch.setattr("app.auth.load_config", lambda: config_state)

    calls = []
    real_check = auth_module.check_password_hash

    def counting_check(stored_hash, password):
        calls.append(password)
        return real_check(stored_hash, password)

    monkeypatch.setattr("app.auth.check_password_hash", counting_check)

    auth_module.clear_credential_cache()
    with app.app_context():
        yield type("Env", (), {"config": config_state, "calls": calls, "app": app})
    auth_module.clear_credential_cache()


def test_repeated_login_derives_the_key_only_once(auth_env):
    """The point of the cache: the second and third request skip the derivation."""
    assert auth_module.verify_password("admin", PASSWORD) == "admin"
    assert auth_module.verify_password("admin", PASSWORD) == "admin"
    assert auth_module.verify_password("admin", PASSWORD) == "admin"

    assert len(auth_env.calls) == 1, "key derivation should have run exactly once"


def test_wrong_password_is_never_cached_and_always_pays_full_price(auth_env):
    """The security property: an attacker gains nothing from the cache."""
    for _ in range(3):
        assert auth_module.verify_password("admin", WRONG_PASSWORD) is None

    assert len(auth_env.calls) == 3, "every wrong attempt must run the derivation"


def test_wrong_password_still_rejected_after_a_successful_login(auth_env):
    """A populated cache must not make a wrong password pass."""
    assert auth_module.verify_password("admin", PASSWORD) == "admin"
    assert auth_module.verify_password("admin", WRONG_PASSWORD) is None
    assert auth_module.verify_password("admin", "") is None
    assert auth_module.verify_password("admin", PASSWORD) == "admin"


def test_password_change_invalidates_immediately(auth_env):
    """The core of the design: the stored hash is part of the cache key.

    No invalidation hook has to fire - a new hash simply makes the old entry unreachable.
    """
    assert auth_module.verify_password("admin", PASSWORD) == "admin"

    new_password = "a-completely-new-password"
    auth_env.config["web_ui_password_hash"] = _hash(new_password)

    # The old password must stop working AT ONCE, not after the TTL.
    assert auth_module.verify_password("admin", PASSWORD) is None
    assert auth_module.verify_password("admin", new_password) == "admin"


def test_entry_expires_after_its_lifetime(auth_env, monkeypatch):
    """With a lifetime of zero every request derives again."""
    monkeypatch.setattr("app.auth._CREDENTIAL_CACHE_TTL_SECONDS", 0.0)

    assert auth_module.verify_password("admin", PASSWORD) == "admin"
    assert auth_module.verify_password("admin", PASSWORD) == "admin"

    assert len(auth_env.calls) == 2, "an expired entry must not be reused"


def test_wrong_username_is_not_cached(auth_env):
    assert auth_module.verify_password("intruder", PASSWORD) is None
    assert auth_module.verify_password("intruder", PASSWORD) is None
    assert len(auth_module._credential_cache) == 0


def test_cache_size_is_bounded(auth_env):
    """Guessing attempts must not be able to grow the cache without limit."""
    limit = auth_module._CREDENTIAL_CACHE_MAX_ENTRIES
    for index in range(limit + 10):
        password = f"pw-{index}"
        auth_env.config["web_ui_password_hash"] = _hash(password)
        assert auth_module.verify_password("admin", password) == "admin"

    assert len(auth_module._credential_cache) <= limit


def test_the_password_itself_is_never_kept(auth_env):
    """Entries are HMAC fingerprints, not credentials."""
    assert auth_module.verify_password("admin", PASSWORD) == "admin"
    assert len(auth_module._credential_cache) == 1

    for key in auth_module._credential_cache:
        assert PASSWORD.encode("utf-8") not in key
        assert b"admin" not in key


def test_first_time_setup_still_works_without_a_hash(auth_env):
    """No configured password: admin/setup must keep working, and nothing may be cached.

    The setup branch writes ``session['setup_mode']``, which needs a REQUEST context - an app
    context alone raises "Working outside of request context". That is a property of the
    production path, which only ever runs inside a request, so the test supplies one instead of
    the code dropping the session write to suit the test.
    """
    auth_env.config["web_ui_password_hash"] = None

    with auth_env.app.test_request_context():
        assert auth_module.verify_password("admin", "setup") == "admin"
        assert auth_module.verify_password("admin", "anything-else") is None

    assert len(auth_module._credential_cache) == 0
