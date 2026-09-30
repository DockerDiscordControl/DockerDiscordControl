# -*- coding: utf-8 -*-
"""An unauthenticated probe does not count as someone using the panel.

THE FINDING (stage 4 review before v3.1.0, section 34 pass 4): every
request but static files and /health counted as a person using the panel,
unauthenticated ones included. An uptime monitor or a reverse-proxy check
of "/" or "/login" more often than every 300 s kept panel_is_active() true
forever, and the worker asked Docker every 30 s around the clock - the
on-demand refresh decided on 2026-09-28, silently undone. A common
homelab setup.

THE CONTRACT: only an answered request counts - a 2xx that is not the
login or setup page and not a HEAD. A refused one (401, a redirect to the
login) does not.

HOW THIS TEST CAN FAIL: a probe keeps the panel "open" again, or a logged-in
page view no longer does.

COUNTER-CHECK (2026-09-30): red before the change (active after the probes).
"""

import pytest

import app.utils.web_helpers as wh
from tests.spec.panel_client import basic_auth, panel  # noqa: F401 - fixture


@pytest.fixture
def idle(monkeypatch):
    monkeypatch.setattr(wh, "last_panel_request", 0.0)


def test_probes_do_not_open_the_panel(panel, idle):  # noqa: F811
    client = panel.test_client()
    client.get("/login")
    client.get("/")
    client.head("/", headers=basic_auth())
    assert not wh.panel_is_active(), "a probe kept the panel 'open'"


def test_a_logged_in_page_view_does(panel, idle, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.blueprints.main_routes.render_template", lambda *a, **k: "panel")
    answer = panel.test_client().get("/", headers=basic_auth())
    assert answer.status_code == 200
    assert wh.panel_is_active()
