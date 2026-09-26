# -*- coding: utf-8 -*-
"""The healthcheck is not a way to guess the panel password without a brake.

THE FINDING (audit 2026-09-26). /health answers without a login, on purpose -
the container probe holds no credentials. But a caller who sends Basic auth
gets the detailed answer (version, container count) only when the password is
right, and init_limiter returned early for /health before its Authorization
check. So /health checked any number of passwords per minute, with nothing but
PBKDF2's cost in the way - which each try also charged to the server's CPU.

THE CONTRACT: a request that carries credentials counts against the same brake
on /health as everywhere else. The probe, which carries none, is not braked.

HOW THIS TEST CAN FAIL: /health still checks credentials after the limit is
reached, or the probe gets throttled.

COUNTER-CHECK (2026-09-26): red before the fix - request 101 with a wrong
password still got 200 and was still checked.
"""

import base64

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"


def _basic(password):
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache, setup_limiter, two_factor_limiter
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()
    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def test_guessing_passwords_on_health_is_braked(app):
    from app.auth import auth_limiter

    client = app.test_client()
    for number in range(auth_limiter.limit):
        client.get("/health", headers=_basic(f"guess-{number}"))

    answer = client.get("/health", headers=_basic(PASSWORD))

    assert answer.status_code == 429
    assert b"version" not in answer.data


def test_the_probe_is_never_braked(app):
    """Counter-case: the container healthcheck carries no credentials and runs
    every few seconds for the life of the container."""
    from app.auth import auth_limiter

    client = app.test_client()
    answers = [client.get("/health").status_code for _ in range(auth_limiter.limit + 20)]

    assert 429 not in answers, answers
