# -*- coding: utf-8 -*-
"""An action log that exists but cannot be opened is answered, not a 500 page.

THE FINDING (stage 4 review before v3.1.0, section 32 pass 4): the
download route caught only FileNotFoundError; a log that could not be
opened (PermissionError, another OSError) raised out of the route, and the
operator got Flask's bare 500 page instead of the message and the way
back. Its sibling /action-log already handles these.

THE CONTRACT: an unreadable log is flashed as such and redirects to the
panel, as a missing one does.

HOW THIS TEST CAN FAIL: the error escapes the route again.

COUNTER-CHECK (2026-09-30): red before the change (500).
"""

import pytest

from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("I/O error")])
def test_the_operator_is_sent_back_with_a_message(panel, monkeypatch, error):  # noqa: F811
    def refuse(*args, **kwargs):
        raise error
    monkeypatch.setattr("app.blueprints.action_log_routes.send_file", refuse)

    client = panel.test_client()
    response = client.get("/action_log_bp/download-action-log", headers=basic_auth())

    assert response.status_code == 302
    with client.session_transaction() as session:
        messages = [text for _kind, text in session.get("_flashes", [])]
    assert any("could not be read" in text for text in messages), messages
