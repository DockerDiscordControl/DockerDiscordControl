# -*- coding: utf-8 -*-
"""A failed channel lookup is not a Discord server without channels.

THE FINDING (review D23, pass 2, section 31 F5): `/api/automation/channels`
answers three different situations with the same shape and the same status:

    bot not ready   -> 200 {'channels': [], 'warning': 'Bot not ready'}
    no guilds yet   -> 200 {'channels': [], 'warning': '...'}
    anything raised -> 200 {'channels': [], 'error': 'Failed to fetch channels'}

The first two are deliberate: the panel should show an empty list while the
bot is still connecting. The third is a failure, and a caller reading only
`channels` cannot tell it from "this server has no channels I may read".
Every other route in this file answers a failure with a status of its own.

Nothing in the panel calls this endpoint today - it is an API route behind
the login with no current consumer - so this repairs a trap rather than a
symptom. The next consumer would have inherited it.
"""

from types import SimpleNamespace

import pytest
from flask import Flask

from app.blueprints.automation_routes import automation_bp


@pytest.fixture
def client(monkeypatch):
    import app.auth as auth_module
    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    def _with_bot(bot):
        import services.scheduling.donation_message_service as donation_module
        monkeypatch.setattr(donation_module, "get_bot_instance", lambda: bot)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-d23"
    app.register_blueprint(automation_bp)
    return app.test_client(), _with_bot


class _Exploding:
    @property
    def guilds(self):
        raise RuntimeError("the gateway went away mid-read")


def test_a_failure_is_not_answered_with_200(client):
    http, with_bot = client
    with_bot(_Exploding())

    response = http.get("/api/automation/channels")

    assert response.status_code >= 500, (
        f"a failed lookup answered {response.status_code}, the same as "
        f"'this server has no channels'"
    )


def test_a_bot_that_is_not_ready_still_answers_200(client):
    """Counter-check: the deliberate empty answer must stay an ordinary one."""
    http, with_bot = client
    with_bot(None)

    response = http.get("/api/automation/channels")

    assert response.status_code == 200
    assert response.get_json()["channels"] == []
    assert response.get_json().get("warning")


def test_a_bot_without_guilds_still_answers_200(client):
    """Counter-check: still connecting is not a failure either."""
    http, with_bot = client
    with_bot(SimpleNamespace(guilds=[]))

    response = http.get("/api/automation/channels")

    assert response.status_code == 200
    assert response.get_json().get("warning")


def test_a_working_lookup_is_unaffected(client):
    """Counter-check: answering 500 to everything would pass the test above."""
    http, with_bot = client
    with_bot(SimpleNamespace(guilds=[]))

    assert http.get("/api/automation/channels").status_code == 200
