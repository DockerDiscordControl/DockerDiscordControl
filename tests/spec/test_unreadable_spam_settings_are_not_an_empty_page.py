# -*- coding: utf-8 -*-
"""Spam settings that could not be read are not spam settings with no values.

THE FINDING (review D9, pass 2, section 32 F1): the GET route for
/api/spam-protection does

    settings = result.data.to_dict() if result.success else {}
    return jsonify(settings)

so a failure of `get_config()` - the configuration file unreadable, the
section unusable - answers HTTP 200 with `{}`. The panel then draws its
spam-protection form from an empty object, showing its own HTML start values,
and the operator reads them as the settings in force. Nothing says otherwise.

Its POST sibling in the same file answers 400 or 500 with a reason, so the
two halves of one form disagree about what a failure looks like.
"""

from types import SimpleNamespace

import pytest
from flask import Flask

from app.blueprints.main_routes import main_bp


class _Config:
    @staticmethod
    def to_dict():
        return {"command_cooldowns": {"control": 7},
                "global_settings": {"enabled": True}}


@pytest.fixture
def client(monkeypatch):
    """The route, with auth stubbed and the service answering to order."""
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    def _answer(result):
        # main_routes binds the name at import time (line 22), so the patch has
        # to go there rather than at the service's own module.
        monkeypatch.setattr("app.blueprints.main_routes.get_spam_protection_service",
                            lambda: SimpleNamespace(get_config=lambda: result))

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-d9"
    app.register_blueprint(main_bp)
    return app.test_client(), _answer


def test_an_unreadable_configuration_is_not_a_page_of_defaults(client):
    http, answer = client
    answer(SimpleNamespace(success=False, data=None,
                           error="channels_config.json is unreadable"))

    response = http.get("/api/spam-protection")

    assert response.status_code >= 500, (
        f"the settings could not be read and the panel is told {response.status_code} "
        f"with {response.get_data(as_text=True)[:60]}"
    )


def test_the_reason_comes_with_it(client):
    http, answer = client
    answer(SimpleNamespace(success=False, data=None,
                           error="channels_config.json is unreadable"))

    payload = http.get("/api/spam-protection").get_json()

    assert payload.get("error"), "the panel is told it failed and not why"


def test_readable_settings_still_come_through(client):
    """Counter-check: refusing everything would pass the tests above."""
    http, answer = client
    answer(SimpleNamespace(success=True, data=_Config(), error=None))

    response = http.get("/api/spam-protection")

    assert response.status_code == 200
    assert response.get_json()["command_cooldowns"]["control"] == 7
