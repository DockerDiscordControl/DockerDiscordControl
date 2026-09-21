# -*- coding: utf-8 -*-
"""A failed read of the admin list must not look like "there are no admins".

THE FINDING (review E22, found while re-reading the container-assignment
feature): when `/api/admin-users` cannot read `admins.json` it answers

    jsonify({"success": False, "error": "An internal error occurred ..."})

with **HTTP 200**, because no status code is given. Review C21 put that answer
there, and it was an improvement on the unhandled 500 it replaced. What nobody
checked is what the panel does with it.

``fetch()`` does not reject on an HTTP error status, and it certainly does not
reject on a 200. So ``openAdminModal()`` runs its success path over an error
body:

    adminUsers      = data.discord_admin_users || [];   // -> []
    adminNotes      = data.admin_notes  || {};          // -> {}
    adminContainers = data.admin_containers || {};      // -> {}
    renderAdminUsers();                                 // "no users configured"
    modal.show();                                       // and it OPENS

The operator opens the Discord admin dialog, is told there are no admins,
probably adds themselves back - and presses Save. ``saveAdminUsers()`` then
POSTs that list, and the POST route writes the whole document:

**every admin is deleted, and every per-admin container assignment with them.**

A read error turning into a write that erases the thing that could not be read
is about the worst way round this can go, and neither half is obviously wrong
on its own. Both are fixed:

* the route answers a read failure with **500**, so a client can tell;
* the panel refuses to show or save an admin list it did not successfully
  load, rather than trusting the shape of a payload.

The second half is checked by reading the source, because the runtime image has
no JavaScript engine - the same limitation, and the same honesty about it, as
`test_the_page_scripts_are_parseable.py`.
"""

import json
from pathlib import Path

import pytest
from flask import Flask

from app.web import routes as routes_module

PROJECT = Path(__file__).resolve().parents[2]
CONFIG_UI_JS = PROJECT / "app" / "static" / "js" / "config-ui.js"


class _UnreadableAdminService:
    def get_admin_data(self, *_a, **_kw):
        raise OSError(13, "Permission denied")

    def save_admin_data(self, users, notes, admin_containers=None):
        return True


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    monkeypatch.setattr(routes_module.auth, "login_required", lambda f: f)
    routes_module.register_routes(app)
    monkeypatch.setattr(routes_module, "get_admin_service",
                        lambda: _UnreadableAdminService())
    return app.test_client()


def test_a_failed_read_is_not_answered_with_200(client):
    response = client.get("/api/admin-users")

    assert response.status_code >= 500, (
        f"the admin list could not be read and the panel was told 'OK' "
        f"({response.status_code}); fetch() does not reject on 200, so the "
        f"panel treats an error body as an empty admin list"
    )


def test_the_failed_read_still_explains_itself(client):
    """Counter-check: a status code must not replace the message (review C21)."""
    response = client.get("/api/admin-users")
    body = json.loads(response.data)

    assert body.get("success") is False
    assert body.get("error"), "no reason given with the failure"


def test_the_failed_read_does_not_look_like_an_empty_admin_list(client):
    """The shape matters as much as the status: no key, nothing to mistake."""
    body = json.loads(client.get("/api/admin-users").data)

    assert "discord_admin_users" not in body, (
        "the error body carries an empty admin list, which reads exactly like "
        "'there are no admins' to anything that does not check success first"
    )


def test_the_panel_refuses_to_save_a_list_it_never_loaded():
    """The JavaScript half. Source-read, because there is no JS engine here."""
    source = CONFIG_UI_JS.read_text(encoding="utf-8")

    assert "adminDataLoaded" in source, (
        "config-ui.js has no flag recording that the admin list was actually "
        "loaded, so saveAdminUsers() cannot tell a real empty list from a "
        "failed read"
    )
    save_at = source.index("function saveAdminUsers()")
    save_body = source[save_at:save_at + 1200]
    assert "adminDataLoaded" in save_body, (
        "saveAdminUsers() does not check that the list was loaded before it "
        "posts one - a failed load would write an empty admin list"
    )


def test_the_panel_checks_the_payload_before_showing_it():
    source = CONFIG_UI_JS.read_text(encoding="utf-8")
    open_at = source.index("function openAdminModal()")
    open_body = source[open_at:open_at + 1600]

    assert "success === false" in open_body or "!response.ok" in open_body, (
        "openAdminModal() populates its state from the payload without asking "
        "whether the payload is an answer or an error"
    )
