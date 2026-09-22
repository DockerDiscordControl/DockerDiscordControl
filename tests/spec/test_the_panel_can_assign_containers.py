# -*- coding: utf-8 -*-
"""The panel can hand out container assignments, and refuses a name nobody has.

The maintenance half of the operator's request (review F5; F1 built the rule,
F2 and F4 enforce it). `POST /api/admin-users` knew `discord_admin_users` and
`admin_notes` and nothing else, so the assignment had no author but a text
editor.

WHY A NAME IS CHECKED AGAINST THE CONFIGURED CONTAINERS: a typo in a container
name does not fail, it means "this admin may control nothing on that one", and
nothing would ever say so. Of all the ways to get this wrong, a silent one is
the worst, because the admin is simply refused later and nobody connects it to
a letter. So an unknown name is refused at the door, by name.

An id in the assignment that is not on the admin list is refused too: the
mapping narrows a right, and writing one for somebody who has no right at all
is a statement nobody can act on.
"""

import json

import pytest
from flask import Flask

import app.web.routes as routes


@pytest.fixture
def client(monkeypatch):
    """The route with auth stubbed, the service recording, and two containers."""
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    saved = {}

    class _Service:
        @staticmethod
        def get_admin_data():
            return {"discord_admin_users": ["1"], "admin_notes": {},
                    "admin_containers": {"1": ["valheim"]}}

        @staticmethod
        def save_admin_data(admin_users, admin_notes=None, admin_containers=None):
            saved.update({"users": admin_users, "notes": admin_notes,
                          "containers": admin_containers})
            return True

    monkeypatch.setattr(routes, "get_admin_service", lambda: _Service())
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: type("S", (), {"get_all_servers": staticmethod(
            lambda: [{"docker_name": "valheim"}, {"docker_name": "nginx"}])})())

    app = Flask(__name__)
    app.config["TESTING"] = True
    routes.register_routes(app)
    return app.test_client(), saved


def _post(http, payload):
    return http.post("/api/admin-users", json=payload)


def test_an_assignment_reaches_the_service(client):
    http, saved = client

    response = _post(http, {"discord_admin_users": ["1", "2"],
                            "admin_notes": {"1": "Luigi"},
                            "admin_containers": {"1": ["valheim"]}})

    assert response.get_json() == {"success": True}, response.get_json()
    assert saved["containers"] == {"1": ["valheim"]}, (
        f"the assignment never reached the service: {saved}"
    )


def test_a_container_nobody_has_is_refused_by_name(client):
    """A typo means 'may control nothing' and would never say so."""
    http, saved = client

    payload = _post(http, {"discord_admin_users": ["1"],
                           "admin_containers": {"1": ["valheim", "valhiem"]}}).get_json()

    assert payload.get("success") is False, payload
    assert "valhiem" in payload.get("error", ""), (
        f"refused without naming the container: {payload}"
    )
    assert saved == {}, "it was saved anyway"


def test_an_assignment_for_somebody_who_is_not_an_admin_is_refused(client):
    http, saved = client

    payload = _post(http, {"discord_admin_users": ["1"],
                           "admin_containers": {"999": ["valheim"]}}).get_json()

    assert payload.get("success") is False, payload
    assert "999" in payload.get("error", ""), payload
    assert saved == {}


def test_an_empty_assignment_is_allowed(client):
    """'This admin may control nothing' is a statement somebody may want to make."""
    http, saved = client

    payload = _post(http, {"discord_admin_users": ["1"],
                           "admin_containers": {"1": []}}).get_json()

    assert payload.get("success") is True, payload
    assert saved["containers"] == {"1": []}


def test_a_save_without_an_assignment_still_works(client):
    """The counter-case: every existing caller passes no assignment at all.

    It must not become required, and it must not be turned into an empty
    mapping either - that would delete what is on disk. None means "leave it
    alone", which is what the service does with it.
    """
    http, saved = client

    payload = _post(http, {"discord_admin_users": ["1"], "admin_notes": {}}).get_json()

    assert payload == {"success": True}
    assert saved["containers"] is None, saved


def test_the_read_hands_the_assignment_out(client):
    """The panel has to be able to show what is set."""
    http, _ = client

    payload = http.get("/api/admin-users").get_json()

    assert payload["admin_containers"] == {"1": ["valheim"]}


def test_the_read_also_names_the_containers_to_choose_from(client):
    """From the same source the validation uses, so the two cannot disagree.

    The panel has to offer names, and offering a name the save would then
    refuse is the sort of thing that makes people distrust a form.
    """
    http, _ = client

    payload = http.get("/api/admin-users").get_json()

    assert payload["available_containers"] == ["nginx", "valheim"], payload


def test_containers_that_cannot_be_read_do_not_break_the_page(client, monkeypatch):
    """The admin list is the point of this route; the choices are an extra."""
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")))
    http, _ = client

    payload = http.get("/api/admin-users").get_json()

    assert payload["discord_admin_users"] == ["1"]
    assert payload["available_containers"] == []


def test_an_unreadable_container_list_refuses_without_its_details(client, monkeypatch, caplog):
    """CodeQL #64 (py/stack-trace-exposure): the refusal carried the exception
    text into the HTTP answer. An OSError names paths on the host; that belongs
    in the log. The answer still refuses, and still says why in plain words."""
    import logging
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: (_ for _ in ()).throw(OSError("/app/config/channels_config.json: Permission denied")))
    http, saved = client

    with caplog.at_level(logging.DEBUG):
        payload = _post(http, {"discord_admin_users": ["1"],
                               "admin_containers": {"1": ["valheim"]}}).get_json()

    assert payload.get("success") is False, payload
    assert "could not be read" in payload.get("error", ""), payload
    assert "/app/config" not in payload.get("error", ""), payload
    assert saved == {}, "it was saved anyway"
    assert any("/app/config/channels_config.json" in r.getMessage() for r in caplog.records), \
        "the details must still reach the log"
