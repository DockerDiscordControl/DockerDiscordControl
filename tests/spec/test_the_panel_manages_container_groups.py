# -*- coding: utf-8 -*-
"""The panel can create, change and delete container groups.

The operator's groups (services/config/group_service.py) need a way in. These
are the routes the page uses, and the promises they make:

* a group is saved and comes back with the containers it was given;
* a refusal from the service - a name twice, an empty name - reaches the page
  as an error with a reason, not as a 500 and not as a silent success;
* a group that names containers DDC no longer has says so when it is read, so
  the page can show it instead of the operator finding out when a task acts on
  five of seven containers;
* every route needs the login, like the rest of the panel.

COUNTER-CHECK (2026-09-23): red before - there were no routes. Each test says
what it alone would let through.
"""

import base64
import json

import pytest
from flask import Flask

AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test").decode()}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The group blueprint on a minimal app, with a throwaway config directory."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "alpha"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from app import auth as auth_module
    from app.blueprints.group_routes import group_bp
    from services.config import group_service

    group_service.reset_group_service()
    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="groups", WTF_CSRF_ENABLED=False)
    app.register_blueprint(group_bp)
    return app.test_client()


def test_a_group_is_saved_and_listed(client):
    created = client.post("/api/groups", json={"name": "Gameserver",
                                               "containers": ["Valheim", "alpha"]},
                          headers=AUTH)

    assert created.status_code == 200, created.get_data(as_text=True)
    listed = client.get("/api/groups", headers=AUTH).get_json()

    assert [g["name"] for g in listed["groups"]] == ["Gameserver"]
    assert listed["groups"][0]["containers"] == ["Valheim", "alpha"]


def test_a_refused_name_comes_back_with_its_reason(client):
    client.post("/api/groups", json={"name": "Gameserver", "containers": []}, headers=AUTH)

    answer = client.post("/api/groups", json={"name": "gameserver", "containers": []},
                         headers=AUTH)

    assert answer.status_code == 400
    assert "Gameserver" in answer.get_json()["error"], answer.get_json()


def test_a_group_reports_containers_ddc_no_longer_has(client):
    client.post("/api/groups", json={"name": "Gameserver",
                                     "containers": ["Valheim", "Enshrouded"]}, headers=AUTH)

    listed = client.get("/api/groups", headers=AUTH).get_json()["groups"][0]

    assert listed["missing"] == ["Enshrouded"], (
        "the page cannot warn about a group that shrank if the route does not say so")
    assert listed["containers"] == ["Valheim", "Enshrouded"], "the group keeps what was written"


def test_a_group_can_be_deleted(client):
    client.post("/api/groups", json={"name": "Gameserver", "containers": ["Valheim"]},
                headers=AUTH)

    assert client.delete("/api/groups/Gameserver", headers=AUTH).status_code == 200
    assert client.get("/api/groups", headers=AUTH).get_json()["groups"] == []


def test_deleting_a_group_that_is_not_there_is_not_a_success(client):
    """Counter-check: a 200 here would tell the page a group vanished that never was."""
    answer = client.delete("/api/groups/nothing", headers=AUTH)

    assert answer.status_code == 404


def test_the_routes_need_the_login(client):
    """Counter-check: the panel's groups are not public."""
    assert client.get("/api/groups").status_code == 401
    assert client.post("/api/groups", json={"name": "x", "containers": []}).status_code == 401
    assert client.delete("/api/groups/x").status_code == 401


def test_the_routes_are_registered_in_the_real_panel():
    """A blueprint nobody registers is a set of routes nobody can call.

    COUNTER-CHECK: red before - group_bp existed and app/web/blueprints.py did
    not know it, so every test above passed against an app the operator never
    reaches.
    """
    from app.web import blueprints

    source = (blueprints.__file__ or "")
    with open(source, "r", encoding="utf-8") as f:
        text = f.read()

    assert "group_bp" in text, "the group routes are not registered with the panel"
