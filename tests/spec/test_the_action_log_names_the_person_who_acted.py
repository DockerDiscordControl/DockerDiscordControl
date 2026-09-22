# -*- coding: utf-8 -*-
"""The action log names the person who acted, not "System".

THE FINDING: log_user_action defaults its user to "System", and the web
panel's own call sites do not pass one: saving the spam-protection settings,
booking a manual donation, creating, editing or deleting a schedule, changing
the mech difficulty. In the log the operator reads - the one place that
answers "who did this?" - a person booking a $50 donation is indistinguishable
from an automated system action. The one site that does pass a user reads
session['user'], which nothing in the tree ever sets, so it writes "Unknown".

The name is taken from the request the action came in on: DDC authenticates
every panel route with Basic auth, so the verified user name is right there.
Outside a request - the bot, the scheduler - nothing changes.

COUNTER-CHECK (2026-09-22): red before - the entry said "System"; the
explicit-user and no-request cases are the two counter-checks.
"""

from unittest.mock import patch

import pytest


@pytest.fixture
def recorder(monkeypatch):
    written = []

    class _Service:
        def log_action(self, action, target, user, source, details):
            written.append({"action": action, "target": target, "user": user,
                            "source": source, "details": details})
            return type("R", (), {"success": True, "error": None})()

    monkeypatch.setattr("services.infrastructure.action_logger.get_action_log_service",
                        lambda: _Service())
    return written


def _app():
    from flask import Flask

    return Flask("t")


def test_a_panel_action_carries_the_logged_in_name(recorder):
    from services.infrastructure.action_logger import log_user_action

    app = _app()
    with app.test_request_context("/api/spam-protection", method="POST",
                                  headers={"Authorization": "Basic YWRtaW46c2VjcmV0"}):
        log_user_action(action="SAVE", target="spam protection", source="Web UI")

    assert recorder[0]["user"] == "admin", recorder[0]


def test_an_explicit_name_still_wins(recorder):
    """Counter-check: the scheduler names itself, and that must stand."""
    from services.infrastructure.action_logger import log_user_action

    app = _app()
    with app.test_request_context("/", headers={"Authorization": "Basic YWRtaW46c2VjcmV0"}):
        log_user_action(action="START", target="web", user="Scheduled Task", source="Scheduler")

    assert recorder[0]["user"] == "Scheduled Task"


def test_outside_a_request_it_is_still_system(recorder):
    """Counter-check: the bot's own actions are not attributed to a person."""
    from services.infrastructure.action_logger import log_user_action

    log_user_action(action="STOP", target="web", source="Auto-Action")

    assert recorder[0]["user"] == "System"
