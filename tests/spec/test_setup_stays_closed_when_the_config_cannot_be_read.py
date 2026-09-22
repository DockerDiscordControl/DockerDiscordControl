# -*- coding: utf-8 -*-
"""A configuration that cannot be read does not reopen first-time setup.

THE FINDING: app/auth.py refuses the admin/setup first-run LOGIN when the
configuration carries config_read_errors - a missing password hash has two
causes that look the same, a fresh install and a config that could not be
read (tests/spec/test_read_error_is_not_a_fresh_install.py). The /setup
ROUTES, which are what actually writes a new password, never got that guard:
they ask only whether a hash is there.

So on an established installation whose config/web_ui.json becomes
unreadable or truncated, an unauthenticated client can POST /setup with a
password of its choosing, and update_config_fields writes it: the panel then
belongs to whoever sent that request. One request is enough, so the 5/min
rate limit does not help, and the CSRF token can be fetched from GET /setup.

Both routes now refuse while a read error stands, and say so in the log.

COUNTER-CHECK (2026-09-22): red before - the POST answered success and the
hash was written. A real fresh install must still work (third test).
"""

from unittest.mock import patch

import pytest


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from app.auth import auth_limiter, setup_limiter, clear_credential_cache
    from app.web import create_app

    for limiter in (auth_limiter, setup_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    yield app
    for limiter in (auth_limiter, setup_limiter):
        limiter.ip_dict.clear()


GOOD_PASSWORD = "Sehr-Sicher-2026!"


def _post_setup(app, config):
    written = {}

    def _update(fields):
        written.update(fields)
        return True

    with patch("app.blueprints.main_routes.load_config", return_value=config), \
         patch("app.blueprints.main_routes.update_config_fields", side_effect=_update):
        answer = app.test_client().post("/setup", data={"password": GOOD_PASSWORD,
                                                        "confirm_password": GOOD_PASSWORD})
    return answer, written


def test_a_read_error_does_not_let_anyone_set_a_password(panel):
    config = {"web_ui_password_hash": None,
              "config_read_errors": ["config/web_ui.json: Permission denied"]}

    answer, written = _post_setup(panel, config)

    assert "web_ui_password_hash" not in written, "an unauthenticated request set the panel password"
    assert answer.status_code in (403, 409, 503) or answer.get_json().get("success") is False


def test_the_setup_page_is_not_offered_either(panel):
    config = {"web_ui_password_hash": None,
              "config_read_errors": ["config/web_ui.json: Permission denied"]}

    with patch("app.blueprints.main_routes.load_config", return_value=config):
        answer = panel.test_client().get("/setup")

    assert answer.status_code in (302, 403, 503), answer.status_code
    assert b"<form" not in answer.data.lower() or answer.status_code != 200


def test_a_real_fresh_install_still_works(panel):
    """Counter-check: the guard must not close the door for a new installation."""
    answer, written = _post_setup(panel, {"web_ui_password_hash": None})

    assert answer.get_json()["success"] is True
    assert written.get("web_ui_password_hash", "").startswith("pbkdf2:sha256")


def test_a_configured_panel_is_still_refused(panel):
    """Counter-check, the other side: setup stays closed once a hash exists."""
    answer, written = _post_setup(panel, {"web_ui_password_hash": "pbkdf2:sha256:600000$x$y"})

    assert answer.get_json()["success"] is False
    assert written == {}
