# -*- coding: utf-8 -*-
"""Two lines of the operator's log that said something else than what happened.

READ ON THE OPERATOR'S LOG, 2026-09-28, after the Mac was restarted:

1. "Direct Cog Periodic message update finished" and "... No messages were due
   for update" took turns, minute after minute - with both channels set to
   refresh every minute. The edit loop ticks once a minute (at :31), and the
   time of the last update is taken when the edit is done (:32), so the next
   tick found 59.x seconds and waited another minute. "Every minute" updated
   the messages - and their "Last update" - every two minutes.

2. "WARNING in auth: Failed login attempt for user: " with an empty name,
   followed by "GET / 302": a browser opening the panel sends no credentials
   before the login prompt is answered. Nobody attempted anything, and a
   warning for it every time the panel is opened trains the reader to ignore
   the line that matters.

COUNTER-CHECK (2026-09-28): with UPDATE_DUE_GRACE_SECONDS at 0, the 59-second
case went red; without the empty-credentials return, the no-credentials case
did. The counter-cases (a real wrong password still warns, a message updated
50 s ago still waits) stayed green in both.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from services.discord.status_overview_service import StatusOverviewService, StatusOverviewUpdateConfig


def _decision(seconds_ago):
    service = StatusOverviewService()
    config = StatusOverviewUpdateConfig(update_interval_minutes=1, recreate_messages_on_inactivity=False,
                                        inactivity_timeout_minutes=10, enable_auto_refresh=True)
    service._get_channel_update_config = lambda channel_id, global_config: config
    return service.make_update_decision(channel_id=1, global_config={},
                                        last_update_time=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
                                        force_recreate=False, last_channel_activity=None)


def test_a_message_updated_59_seconds_ago_is_due_on_the_minute():
    assert _decision(59.2).should_update, "the loop's drift turned every minute into every two"


def test_a_message_updated_50_seconds_ago_still_waits():
    assert not _decision(50).should_update


@pytest.fixture
def app(monkeypatch):
    from werkzeug.security import generate_password_hash
    import app.auth as auth_module
    from app.web import create_app

    monkeypatch.setattr(auth_module, "load_config", lambda: {
        "web_ui_user": "admin", "web_ui_password_hash": generate_password_hash("right")})
    return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})


def _verify(app, username, password, caplog):
    from app.auth import verify_password
    with app.app_context(), caplog.at_level(logging.WARNING):
        result = verify_password(username, password)
    return result, [r.getMessage() for r in caplog.records if "Failed login" in r.getMessage()]


def test_no_credentials_are_no_failed_attempt(app, caplog):
    result, warned = _verify(app, "", "", caplog)
    assert result is None and warned == [], "opening the panel was logged as a failed login"


def test_a_wrong_password_still_warns(app, caplog):
    result, warned = _verify(app, "admin", "wrong", caplog)
    assert result is None and warned == ["Failed login attempt for user: admin"]
