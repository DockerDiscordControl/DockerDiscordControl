# -*- coding: utf-8 -*-
"""A container the operator puts in a group gets a configuration of its own.

THE GAP, measured on his server (2026-09-24): 26 containers on the host, 8
with a file under config/containers/. A group resolves against those files, so
the other 18 were reported as containers DDC "no longer has" - while the group
dialog offers all 26 to choose from. He could build a group of five and have
DDC act on none of them, with a red warning about containers that are sitting
right there.

HIS DECISION, asked as a choice between closing the gap and reporting it
louder: close it. A container that joins a group gets a configuration written
for it - INACTIVE, with no permissions of its own. It is then steerable
through its group, which is the whole point of the group being decoupled from
the single-container control, and it shows up in the container table the way
any switched-off container does.

INACTIVE AND WITH NOTHING TICKED is the careful half of that. Joining a group
must not hand a container the four single-container buttons in Discord; the
operator granted the GROUP, not the container. What the group may do is the
group's own list (test_a_group_decides_what_it_may_do.py).

IT HAPPENS IN THE ROUTE, not in the group service, and that is not an
accident: only the panel can tell whether a name is a container the host
actually has. Writing a file for every name would make "this member is gone"
impossible to report, because the report is exactly "DDC has no configuration
for it" - a typo in a group would quietly become a container.

HOW THIS TEST CAN FAIL: not writing the file, writing it active, writing it
with permissions, or writing one for a name the host does not have.

COUNTER-CHECK (2026-09-24): red before - saving a group wrote groups.json and
nothing else, and the member stayed missing.
"""

import json

import pytest

AUTH = {"Authorization": "Basic YWRtaW46YWRtaW4="}   # admin:admin


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The group route, a config directory with ONE configured container, and a
    host that has three."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "Valheim.json").write_text(json.dumps(
        {"container_name": "Valheim", "docker_name": "Valheim", "active": True,
         "allowed_actions": ["status", "restart"]}), encoding="utf-8")

    from flask import Flask

    from app import auth as auth_module
    from app.blueprints import group_routes
    from services.config import (container_config_save_service, group_service)

    group_service.reset_group_service()
    container_config_save_service.reset_container_config_save_service()
    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)
    # What the host has. "Ghost" is in neither list, so it is the name that
    # must NOT get a file.
    monkeypatch.setattr(group_routes, "containers_on_the_host",
                        lambda: ["Valheim", "alpha", "beta"])

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="groups", WTF_CSRF_ENABLED=False)
    app.register_blueprint(group_routes.group_bp)
    return app.test_client()


def _config(tmp_path, name):
    path = tmp_path / "containers" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_a_new_member_gets_a_configuration(client, tmp_path):
    """THE GAP: 18 of his 26 containers could be grouped and not acted on."""
    answer = client.post("/api/groups", json={"name": "Gameserver",
                                              "containers": ["Valheim", "alpha"]},
                         headers=AUTH)

    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert _config(tmp_path, "alpha") is not None, (
        "the container joined a group and DDC still has no configuration for it")


def test_it_is_written_switched_off_and_without_permissions(client, tmp_path):
    """The operator granted the GROUP. Joining one must not hand the container
    its own four buttons in Discord."""
    client.post("/api/groups", json={"name": "Gameserver", "containers": ["alpha"]},
                headers=AUTH)
    written = _config(tmp_path, "alpha")

    assert written["active"] is False
    assert written["allowed_actions"] == []
    assert written["container_name"] == "alpha"


def test_the_group_can_then_reach_it(client):
    """The point of the file: the member is no longer reported as gone."""
    client.post("/api/groups", json={"name": "Gameserver",
                                     "containers": ["Valheim", "alpha"]}, headers=AUTH)
    shown = client.get("/api/groups", headers=AUTH).get_json()["groups"][0]

    assert shown["missing"] == [], "the member is still reported as one DDC does not have"
    assert shown["containers"] == ["Valheim", "alpha"]


def test_a_container_the_host_does_not_have_gets_nothing(client, tmp_path):
    """Otherwise a typo becomes a container, and "this member is gone" can
    never be reported again - the report IS "DDC has no configuration"."""
    client.post("/api/groups", json={"name": "Gameserver", "containers": ["Ghost"]},
                headers=AUTH)

    assert _config(tmp_path, "Ghost") is None, "a name the host does not have became a file"
    shown = client.get("/api/groups", headers=AUTH).get_json()["groups"][0]

    assert shown["missing"] == ["Ghost"], "the group no longer says the member is gone"


def test_an_existing_configuration_is_left_alone(client, tmp_path):
    """Valheim is active with two permissions. Adding it to a group must not
    quietly switch it off."""
    before = _config(tmp_path, "Valheim")
    client.post("/api/groups", json={"name": "Gameserver", "containers": ["Valheim"]},
                headers=AUTH)

    assert _config(tmp_path, "Valheim") == before, (
        "joining a group rewrote a container that was already configured")


def test_the_group_is_still_saved_when_the_host_cannot_be_asked(client, tmp_path,
                                                                monkeypatch):
    """A docker daemon that does not answer must not cost the operator the
    group he just typed. The members stay as they are - reported missing until
    the host can be asked again."""
    from app.blueprints import group_routes

    def _no_docker():
        raise OSError("docker is not listening")

    monkeypatch.setattr(group_routes, "containers_on_the_host", _no_docker)
    answer = client.post("/api/groups", json={"name": "Gameserver", "containers": ["alpha"]},
                         headers=AUTH)

    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert _config(tmp_path, "alpha") is None
